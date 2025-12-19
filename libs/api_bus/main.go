package main

import (
	"bufio"
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"flag"
	"io"
	"log"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"github.com/gorilla/websocket"
	"gopkg.in/yaml.v3"
	_ "modernc.org/sqlite"
)

// RunRequest 定义触发回测/扫参的请求体。
type RunRequest struct {
	Config string `json:"config"`
	TopN   int    `json:"top_n,omitempty"`
}

// RunResponse 定义统一返回结构。
type RunResponse struct {
	OK         bool   `json:"ok"`
	ExitCode   int    `json:"exit_code"`
	Stdout     string `json:"stdout"`
	Stderr     string `json:"stderr"`
	DurationMs int64  `json:"duration_ms"`
	Error      string `json:"error,omitempty"`
}

// TaskStatus 任务状态枚举。
type TaskStatus string

const (
	TaskPending   TaskStatus = "pending"
	TaskRunning   TaskStatus = "running"
	TaskSucceeded TaskStatus = "succeeded"
	TaskFailed    TaskStatus = "failed"
)

// Task 异步任务对象。
type Task struct {
	ID         string       `json:"id"`
	Type       string       `json:"type"`
	Request    RunRequest   `json:"request"`
	Status     TaskStatus   `json:"status"`
	Result     *RunResponse `json:"result,omitempty"`
	LastError  string       `json:"last_error,omitempty"`
	Attempts   int          `json:"attempts"`
	MaxRetries int          `json:"max_retries"`
	CreatedAt  time.Time    `json:"created_at"`
	StartedAt  *time.Time   `json:"started_at,omitempty"`
	FinishedAt *time.Time   `json:"finished_at,omitempty"`
}

// TaskResponse 任务提交时的返回结构。
type TaskResponse struct {
	OK     bool       `json:"ok"`
	TaskID string     `json:"task_id"`
	Status TaskStatus `json:"status"`
	Error  string     `json:"error,omitempty"`
}

type ServerConfig struct {
	Addr         string
	RepoRoot     string
	PythonBin    string
	Timeout      time.Duration
	DBPath       string
	MaxRetries   int
	RetryBackoff time.Duration
}

func main() {
	var addr string
	var repoRoot string
	var pythonBin string
	var timeoutSec int
	var workers int
	var dbPath string
	var maxRetries int
	var retryBackoffMs int

	flag.StringVar(&addr, "addr", ":8000", "监听地址，例如 :8000")
	flag.StringVar(&repoRoot, "repo", "", "仓库根目录，留空则使用当前工作目录")
	flag.StringVar(&pythonBin, "python", "", "Python 解释器路径（默认优先使用 .venv/bin/python）")
	flag.IntVar(&timeoutSec, "timeout", 0, "单次任务超时秒数（0 表示不限时）")
	flag.IntVar(&workers, "workers", 1, "并发 worker 数")
	flag.StringVar(&dbPath, "db", "", "SQLite 路径（留空则放在 results/api_bus.sqlite3）")
	flag.IntVar(&maxRetries, "max-retries", 0, "失败重试次数（0 表示不重试）")
	flag.IntVar(&retryBackoffMs, "retry-backoff-ms", 1000, "重试延迟（毫秒）")
	flag.Parse()

	if repoRoot == "" {
		cwd, err := os.Getwd()
		if err != nil {
			log.Fatalf("读取当前目录失败: %v", err)
		}
		repoRoot = cwd
	}
	repoRoot, _ = filepath.Abs(repoRoot)

	if pythonBin == "" {
		venvPython := filepath.Join(repoRoot, ".venv", "bin", "python")
		if _, err := os.Stat(venvPython); err == nil {
			pythonBin = venvPython
		} else {
			pythonBin = "python3"
		}
	}

	cfg := ServerConfig{
		Addr:         addr,
		RepoRoot:     repoRoot,
		PythonBin:    pythonBin,
		Timeout:      time.Duration(timeoutSec) * time.Second,
		DBPath:       dbPath,
		MaxRetries:   maxRetries,
		RetryBackoff: time.Duration(retryBackoffMs) * time.Millisecond,
	}

	if cfg.DBPath == "" {
		cfg.DBPath = filepath.Join(cfg.RepoRoot, "results", "api_bus.sqlite3")
	}
	store, err := newStorage(cfg.DBPath)
	if err != nil {
		log.Fatalf("初始化 SQLite 失败: %v", err)
	}
	queue := newTaskQueue(cfg, workers, store)
	hub := newHub()
	queue.hub = hub

	mux := http.NewServeMux()
	mux.HandleFunc("/health", handleHealth)
	mux.HandleFunc("/api/v1/backtest", handleBacktest(queue))
	mux.HandleFunc("/api/v1/sweep", handleSweep(queue))
	mux.HandleFunc("/api/v1/tasks/", handleTaskGet(queue))
	mux.HandleFunc("/api/v1/runs", handleRuns(queue))
	mux.HandleFunc("/ws", handleWS(hub))

	log.Printf("API Bus 启动: addr=%s repo=%s python=%s", cfg.Addr, cfg.RepoRoot, cfg.PythonBin)
	if err := http.ListenAndServe(cfg.Addr, mux); err != nil {
		log.Fatalf("HTTP 服务启动失败: %v", err)
	}
}

func handleHealth(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, http.StatusOK, map[string]any{"ok": true, "message": "ok"})
}

func handleBacktest(queue *TaskQueue) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			writeJSON(w, http.StatusMethodNotAllowed, map[string]any{"ok": false, "error": "仅支持 POST"})
			return
		}
		req, err := parseRequest(r)
		if err != nil {
			writeJSON(w, http.StatusBadRequest, map[string]any{"ok": false, "error": err.Error()})
			return
		}
		if strings.TrimSpace(req.Config) == "" {
			req.Config = "config/config.yml"
		}
		task := queue.Enqueue("backtest", req)
		writeJSON(w, http.StatusOK, TaskResponse{OK: true, TaskID: task.ID, Status: task.Status})
	}
}

func handleSweep(queue *TaskQueue) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			writeJSON(w, http.StatusMethodNotAllowed, map[string]any{"ok": false, "error": "仅支持 POST"})
			return
		}
		req, err := parseRequest(r)
		if err != nil {
			writeJSON(w, http.StatusBadRequest, map[string]any{"ok": false, "error": err.Error()})
			return
		}
		if strings.TrimSpace(req.Config) == "" {
			req.Config = "config/config.yml"
		}
		task := queue.Enqueue("sweep", req)
		writeJSON(w, http.StatusOK, TaskResponse{OK: true, TaskID: task.ID, Status: task.Status})
	}
}

func handleTaskGet(queue *TaskQueue) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet {
			writeJSON(w, http.StatusMethodNotAllowed, map[string]any{"ok": false, "error": "仅支持 GET"})
			return
		}
		id := strings.TrimPrefix(r.URL.Path, "/api/v1/tasks/")
		if strings.TrimSpace(id) == "" {
			writeJSON(w, http.StatusBadRequest, map[string]any{"ok": false, "error": "缺少 task_id"})
			return
		}
		task, ok := queue.Get(id)
		if !ok {
			writeJSON(w, http.StatusNotFound, map[string]any{"ok": false, "error": "task_id 不存在"})
			return
		}
		writeJSON(w, http.StatusOK, task)
	}
}

func handleRuns(queue *TaskQueue) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet {
			writeJSON(w, http.StatusMethodNotAllowed, map[string]any{"ok": false, "error": "仅支持 GET"})
			return
		}
		if queue.store == nil {
			writeJSON(w, http.StatusServiceUnavailable, map[string]any{"ok": false, "error": "未启用存储"})
			return
		}
		limit := 20
		if v := r.URL.Query().Get("limit"); v != "" {
			if n, err := strconv.Atoi(v); err == nil && n > 0 && n <= 200 {
				limit = n
			}
		}
		filter := RunFilter{
			Limit:  limit,
			TaskID: strings.TrimSpace(r.URL.Query().Get("task_id")),
			Symbol: strings.TrimSpace(r.URL.Query().Get("symbol")),
			From:   strings.TrimSpace(r.URL.Query().Get("from")),
			To:     strings.TrimSpace(r.URL.Query().Get("to")),
		}
		runs, err := queue.store.ListRuns(filter)
		if err != nil {
			writeJSON(w, http.StatusInternalServerError, map[string]any{"ok": false, "error": err.Error()})
			return
		}
		writeJSON(w, http.StatusOK, map[string]any{"ok": true, "runs": runs})
	}
}

func parseRequest(r *http.Request) (RunRequest, error) {
	var req RunRequest
	dec := json.NewDecoder(r.Body)
	dec.DisallowUnknownFields()
	if err := dec.Decode(&req); err != nil {
		if errors.Is(err, io.EOF) {
			return req, nil
		}
		return RunRequest{}, err
	}
	return req, nil
}

type logCallback func(stream string, line string)

func runMain(cfg ServerConfig, logFn logCallback, args ...string) RunResponse {
	start := time.Now()
	ctx := context.Background()
	if cfg.Timeout > 0 {
		var cancel context.CancelFunc
		ctx, cancel = context.WithTimeout(ctx, cfg.Timeout)
		defer cancel()
	}
	pyArgs := append([]string{"main.py"}, args...)
	cmd := exec.CommandContext(ctx, cfg.PythonBin, pyArgs...)
	cmd.Dir = cfg.RepoRoot

	stdoutPipe, _ := cmd.StdoutPipe()
	stderrPipe, _ := cmd.StderrPipe()

	if err := cmd.Start(); err != nil {
		return RunResponse{
			OK:         false,
			ExitCode:   -1,
			Stdout:     "",
			Stderr:     "",
			DurationMs: time.Since(start).Milliseconds(),
			Error:      err.Error(),
		}
	}

	var stdoutBuf strings.Builder
	var stderrBuf strings.Builder
	var wg sync.WaitGroup
	wg.Add(2)
	go func() {
		defer wg.Done()
		streamLogs(stdoutPipe, &stdoutBuf, "stdout", logFn)
	}()
	go func() {
		defer wg.Done()
		streamLogs(stderrPipe, &stderrBuf, "stderr", logFn)
	}()

	err := cmd.Wait()
	wg.Wait()
	duration := time.Since(start).Milliseconds()

	resp := RunResponse{
		OK:         err == nil,
		ExitCode:   exitCode(err),
		Stdout:     stdoutBuf.String(),
		Stderr:     stderrBuf.String(),
		DurationMs: duration,
	}
	if err != nil {
		resp.Error = err.Error()
	}
	return resp
}

func streamLogs(r io.Reader, buf *strings.Builder, stream string, logFn logCallback) {
	scanner := bufio.NewScanner(r)
	scanner.Buffer(make([]byte, 0, 64*1024), 1024*1024)
	for scanner.Scan() {
		line := scanner.Text()
		buf.WriteString(line)
		buf.WriteString("\n")
		if logFn != nil {
			logFn(stream, line)
		}
	}
}

func exitCode(err error) int {
	if err == nil {
		return 0
	}
	var exitErr *exec.ExitError
	if errors.As(err, &exitErr) {
		return exitErr.ExitCode()
	}
	return -1
}

func writeJSON(w http.ResponseWriter, status int, payload any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	enc := json.NewEncoder(w)
	enc.SetEscapeHTML(false)
	_ = enc.Encode(payload)
}

// TaskQueue 负责任务排队与状态管理（内存版）。
type TaskQueue struct {
	cfg     ServerConfig
	queue   chan *Task
	mu      sync.RWMutex
	tasks   map[string]*Task
	seq     uint64
	workers int
	store   *Storage
	hub     *Hub
}

func newTaskQueue(cfg ServerConfig, workers int, store *Storage) *TaskQueue {
	if workers <= 0 {
		workers = 1
	}
	tq := &TaskQueue{
		cfg:     cfg,
		queue:   make(chan *Task, 128),
		tasks:   make(map[string]*Task),
		workers: workers,
		store:   store,
	}
	if store != nil {
		loaded, err := store.LoadTasks()
		if err != nil {
			log.Printf("加载历史任务失败: %v", err)
		} else {
			for _, task := range loaded {
				tq.tasks[task.ID] = task
				// 服务重启后，把未完成任务重新入队
				if task.Status == TaskPending || task.Status == TaskRunning {
					task.Status = TaskPending
					task.StartedAt = nil
					task.FinishedAt = nil
					tq.queue <- task
				}
			}
		}
	}
	for i := 0; i < workers; i++ {
		go tq.worker(i + 1)
	}
	return tq
}

// Enqueue 创建任务并入队。
func (tq *TaskQueue) Enqueue(taskType string, req RunRequest) *Task {
	id := tq.nextID()
	task := &Task{
		ID:         id,
		Type:       taskType,
		Request:    req,
		Status:     TaskPending,
		MaxRetries: tq.cfg.MaxRetries,
		CreatedAt:  time.Now(),
	}
	tq.mu.Lock()
	tq.tasks[id] = task
	tq.mu.Unlock()

	if tq.store != nil {
		if err := tq.store.SaveTask(task); err != nil {
			log.Printf("保存任务失败: %v", err)
		}
	}
	tq.broadcastTask(task)

	tq.queue <- task
	return task
}

// Get 查询任务状态。
func (tq *TaskQueue) Get(id string) (*Task, bool) {
	tq.mu.RLock()
	defer tq.mu.RUnlock()
	task, ok := tq.tasks[id]
	return task, ok
}

func (tq *TaskQueue) nextID() string {
	seq := atomic.AddUint64(&tq.seq, 1)
	return time.Now().Format("20060102150405") + "-" + strconv.FormatUint(seq, 10)
}

func (tq *TaskQueue) worker(_ int) {
	for task := range tq.queue {
		tq.update(task.ID, func(t *Task) {
			t.Status = TaskRunning
			t.Attempts += 1
			now := time.Now()
			t.StartedAt = &now
		})
		tq.broadcastTask(task)
		if tq.store != nil {
			if err := tq.store.UpdateTask(task.ID, task); err != nil {
				log.Printf("更新任务失败: %v", err)
			}
		}

		var args []string
		switch task.Type {
		case "backtest":
			args = []string{"backtest", "--config", task.Request.Config}
		case "sweep":
			args = []string{"sweep", "--config", task.Request.Config}
			if task.Request.TopN > 0 {
				args = append(args, "--top-n", strconv.Itoa(task.Request.TopN))
			}
		default:
			tq.update(task.ID, func(t *Task) {
				t.Status = TaskFailed
				t.Result = &RunResponse{OK: false, ExitCode: -1, Error: "未知任务类型"}
				now := time.Now()
				t.FinishedAt = &now
			})
			tq.broadcastTask(task)
			if tq.store != nil {
				if err := tq.store.UpdateTask(task.ID, task); err != nil {
					log.Printf("更新任务失败: %v", err)
				}
			}
			continue
		}

		result := runMain(tq.cfg, func(stream, line string) {
			tq.broadcastLog(task.ID, stream, line)
		}, args...)
		tq.update(task.ID, func(t *Task) {
			if result.OK {
				t.Status = TaskSucceeded
			} else {
				t.Status = TaskFailed
				t.LastError = result.Error
			}
			t.Result = &result
			now := time.Now()
			t.FinishedAt = &now
		})
		tq.broadcastTask(task)
		if !result.OK && task.Attempts <= task.MaxRetries {
			tq.update(task.ID, func(t *Task) {
				t.Status = TaskPending
				t.StartedAt = nil
				t.FinishedAt = nil
				t.Result = nil
			})
			tq.broadcastTask(task)
			delay := tq.cfg.RetryBackoff
			if delay <= 0 {
				delay = time.Second
			}
			time.AfterFunc(delay, func() {
				tq.queue <- task
			})
		}
		if tq.store != nil {
			if err := tq.store.UpdateTask(task.ID, task); err != nil {
				log.Printf("更新任务失败: %v", err)
			}
			if result.OK {
				if err := tq.store.SaveRunIndex(tq.cfg.RepoRoot, task); err != nil {
					log.Printf("写入结果索引失败: %v", err)
				}
			}
		}
	}
}

func (tq *TaskQueue) update(id string, fn func(*Task)) {
	tq.mu.Lock()
	defer tq.mu.Unlock()
	if task, ok := tq.tasks[id]; ok {
		fn(task)
	}
}

func (tq *TaskQueue) broadcastTask(task *Task) {
	if tq.hub == nil {
		return
	}
	payload := map[string]any{
		"type": "task_update",
		"task": task,
	}
	tq.hub.Broadcast(payload)
}

func (tq *TaskQueue) broadcastLog(taskID string, stream string, line string) {
	if tq.hub == nil {
		return
	}
	payload := map[string]any{
		"type":    "task_log",
		"task_id": taskID,
		"stream":  stream,
		"line":    line,
	}
	tq.hub.Broadcast(payload)
}

type Hub struct {
	mu       sync.Mutex
	clients  map[*websocket.Conn]struct{}
	upgrader websocket.Upgrader
}

func newHub() *Hub {
	return &Hub{
		clients: make(map[*websocket.Conn]struct{}),
		upgrader: websocket.Upgrader{
			ReadBufferSize:  1024,
			WriteBufferSize: 1024,
			CheckOrigin:     func(r *http.Request) bool { return true },
		},
	}
}

func (h *Hub) Add(conn *websocket.Conn) {
	h.mu.Lock()
	defer h.mu.Unlock()
	h.clients[conn] = struct{}{}
}

func (h *Hub) Remove(conn *websocket.Conn) {
	h.mu.Lock()
	defer h.mu.Unlock()
	delete(h.clients, conn)
}

func (h *Hub) Broadcast(payload any) {
	h.mu.Lock()
	defer h.mu.Unlock()
	for conn := range h.clients {
		if err := conn.WriteJSON(payload); err != nil {
			_ = conn.Close()
			delete(h.clients, conn)
		}
	}
}

func handleWS(hub *Hub) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		conn, err := hub.upgrader.Upgrade(w, r, nil)
		if err != nil {
			return
		}
		hub.Add(conn)
		defer func() {
			hub.Remove(conn)
			_ = conn.Close()
		}()

		for {
			if _, _, err := conn.ReadMessage(); err != nil {
				return
			}
		}
	}
}

// Storage 负责持久化任务与结果索引。
type Storage struct {
	db *sql.DB
}

// RunIndex 结果索引记录。
type RunIndex struct {
	TaskID     string `json:"task_id"`
	TaskType   string `json:"task_type"`
	ConfigPath string `json:"config_path"`
	ResultDir  string `json:"result_dir"`
	RunID      string `json:"run_id"`
	Symbol     string `json:"symbol"`
	Interval   string `json:"interval"`
	Start      string `json:"start"`
	End        string `json:"end"`
	Summary    string `json:"summary_json"`
	CreatedAt  string `json:"created_at"`
}

func newStorage(dbPath string) (*Storage, error) {
	if err := os.MkdirAll(filepath.Dir(dbPath), 0o755); err != nil {
		return nil, err
	}
	db, err := sql.Open("sqlite", dbPath)
	if err != nil {
		return nil, err
	}
	if err := initSchema(db); err != nil {
		return nil, err
	}
	return &Storage{db: db}, nil
}

func initSchema(db *sql.DB) error {
	ddl := []string{
		`CREATE TABLE IF NOT EXISTS tasks (
			id TEXT PRIMARY KEY,
			type TEXT NOT NULL,
			request_json TEXT NOT NULL,
			status TEXT NOT NULL,
			result_json TEXT,
			last_error TEXT,
			attempts INTEGER DEFAULT 0,
			max_retries INTEGER DEFAULT 0,
			created_at TEXT NOT NULL,
			started_at TEXT,
			finished_at TEXT
		);`,
		`CREATE TABLE IF NOT EXISTS runs (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			task_id TEXT NOT NULL,
			task_type TEXT NOT NULL,
			config_path TEXT NOT NULL,
			result_dir TEXT NOT NULL,
			run_id TEXT,
			symbol TEXT,
			interval TEXT,
			start TEXT,
			end TEXT,
			summary_json TEXT,
			created_at TEXT NOT NULL
		);`,
	}
	for _, stmt := range ddl {
		if _, err := db.Exec(stmt); err != nil {
			return err
		}
	}
	if err := ensureTasksColumns(db); err != nil {
		return err
	}
	if err := ensureRunsColumns(db); err != nil {
		return err
	}
	return nil
}

func (s *Storage) SaveTask(task *Task) error {
	reqJSON, _ := json.Marshal(task.Request)
	var resultJSON []byte
	if task.Result != nil {
		resultJSON, _ = json.Marshal(task.Result)
	}
	_, err := s.db.Exec(
		`INSERT OR REPLACE INTO tasks(id, type, request_json, status, result_json, last_error, attempts, max_retries, created_at, started_at, finished_at)
		 VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);`,
		task.ID,
		task.Type,
		string(reqJSON),
		string(task.Status),
		string(resultJSON),
		task.LastError,
		task.Attempts,
		task.MaxRetries,
		task.CreatedAt.Format(time.RFC3339),
		timePtrToString(task.StartedAt),
		timePtrToString(task.FinishedAt),
	)
	return err
}

func (s *Storage) UpdateTask(id string, task *Task) error {
	reqJSON, _ := json.Marshal(task.Request)
	var resultJSON []byte
	if task.Result != nil {
		resultJSON, _ = json.Marshal(task.Result)
	}
	_, err := s.db.Exec(
		`UPDATE tasks SET type=?, request_json=?, status=?, result_json=?, last_error=?, attempts=?, max_retries=?, started_at=?, finished_at=? WHERE id=?;`,
		task.Type,
		string(reqJSON),
		string(task.Status),
		string(resultJSON),
		task.LastError,
		task.Attempts,
		task.MaxRetries,
		timePtrToString(task.StartedAt),
		timePtrToString(task.FinishedAt),
		id,
	)
	return err
}

func (s *Storage) LoadTasks() ([]*Task, error) {
	rows, err := s.db.Query(`SELECT id, type, request_json, status, result_json, last_error, attempts, max_retries, created_at, started_at, finished_at FROM tasks;`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var tasks []*Task
	for rows.Next() {
		var id, taskType, reqJSON, status, createdAt string
		var resultJSON sql.NullString
		var lastError sql.NullString
		var startedAt sql.NullString
		var finishedAt sql.NullString
		var attempts, maxRetries int
		if err := rows.Scan(&id, &taskType, &reqJSON, &status, &resultJSON, &lastError, &attempts, &maxRetries, &createdAt, &startedAt, &finishedAt); err != nil {
			return nil, err
		}
		task := &Task{
			ID:         id,
			Type:       taskType,
			Status:     TaskStatus(status),
			LastError:  lastError.String,
			Attempts:   attempts,
			MaxRetries: maxRetries,
		}
		_ = json.Unmarshal([]byte(reqJSON), &task.Request)
		if resultJSON.Valid && resultJSON.String != "" {
			var result RunResponse
			_ = json.Unmarshal([]byte(resultJSON.String), &result)
			task.Result = &result
		}
		task.CreatedAt = parseTime(createdAt)
		task.StartedAt = parseTimePtr(startedAt.String)
		task.FinishedAt = parseTimePtr(finishedAt.String)
		tasks = append(tasks, task)
	}
	return tasks, nil
}

type configSnapshot struct {
	Backtest struct {
		Symbol   string `yaml:"symbol"`
		Interval string `yaml:"interval"`
		Start    string `yaml:"start"`
		End      string `yaml:"end"`
	} `yaml:"backtest"`
}

func (s *Storage) SaveRunIndex(repoRoot string, task *Task) error {
	cfgPath := task.Request.Config
	if !filepath.IsAbs(cfgPath) {
		cfgPath = filepath.Join(repoRoot, cfgPath)
	}
	cfgData, err := os.ReadFile(cfgPath)
	if err != nil {
		return err
	}
	var snapshot configSnapshot
	if err := yaml.Unmarshal(cfgData, &snapshot); err != nil {
		return err
	}
	symbol := snapshot.Backtest.Symbol
	interval := snapshot.Backtest.Interval
	start := snapshot.Backtest.Start
	end := snapshot.Backtest.End
	if symbol == "" || interval == "" || start == "" || end == "" {
		return errors.New("配置缺少 backtest 关键字段")
	}
	baseDir := filepath.Join(repoRoot, "results", task.Type, symbol, interval, start+"_"+end)
	latestDir, err := findLatestDir(baseDir)
	if err != nil {
		return err
	}
	if latestDir == "" {
		return errors.New("未找到结果目录")
	}

	runID := filepath.Base(latestDir)
	metaPath := filepath.Join(latestDir, "meta.json")
	if metaData, err := os.ReadFile(metaPath); err == nil {
		var meta map[string]any
		if json.Unmarshal(metaData, &meta) == nil {
			if v, ok := meta["run_id"]; ok {
				runID = toString(v)
			}
		}
	}

	summaryPath := filepath.Join(latestDir, "summary.json")
	summaryJSON := ""
	if summaryData, err := os.ReadFile(summaryPath); err == nil {
		summaryJSON = string(summaryData)
	}

	_, err = s.db.Exec(
		`INSERT INTO runs(task_id, task_type, config_path, result_dir, run_id, symbol, interval, start, end, summary_json, created_at)
		 VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);`,
		task.ID,
		task.Type,
		cfgPath,
		latestDir,
		runID,
		symbol,
		interval,
		start,
		end,
		summaryJSON,
		time.Now().Format(time.RFC3339),
	)
	return err
}

func (s *Storage) ListRuns(filter RunFilter) ([]RunIndex, error) {
	where, args := buildRunQuery(filter)
	query := `SELECT task_id, task_type, config_path, result_dir, run_id, symbol, interval, start, end, summary_json, created_at
		FROM runs` + where + ` ORDER BY id DESC LIMIT ?;`
	args = append(args, filter.Limit)
	rows, err := s.db.Query(query, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var runs []RunIndex
	for rows.Next() {
		var item RunIndex
		if err := rows.Scan(
			&item.TaskID,
			&item.TaskType,
			&item.ConfigPath,
			&item.ResultDir,
			&item.RunID,
			&item.Symbol,
			&item.Interval,
			&item.Start,
			&item.End,
			&item.Summary,
			&item.CreatedAt,
		); err != nil {
			return nil, err
		}
		runs = append(runs, item)
	}
	return runs, nil
}

type RunFilter struct {
	Limit  int
	TaskID string
	Symbol string
	From   string
	To     string
}

func buildRunQuery(filter RunFilter) (string, []any) {
	var clauses []string
	var args []any
	if filter.TaskID != "" {
		clauses = append(clauses, "task_id = ?")
		args = append(args, filter.TaskID)
	}
	if filter.Symbol != "" {
		clauses = append(clauses, "symbol = ?")
		args = append(args, filter.Symbol)
	}
	if filter.From != "" {
		clauses = append(clauses, "created_at >= ?")
		args = append(args, filter.From)
	}
	if filter.To != "" {
		clauses = append(clauses, "created_at <= ?")
		args = append(args, filter.To)
	}
	if len(clauses) == 0 {
		return " ", args
	}
	return " WHERE " + strings.Join(clauses, " AND "), args
}

func ensureRunsColumns(db *sql.DB) error {
	cols, err := listColumns(db, "runs")
	if err != nil {
		return err
	}
	need := []string{"symbol", "interval", "start", "end"}
	for _, col := range need {
		if !cols[col] {
			if _, err := db.Exec(`ALTER TABLE runs ADD COLUMN ` + col + ` TEXT;`); err != nil {
				return err
			}
		}
	}
	return nil
}

func ensureTasksColumns(db *sql.DB) error {
	cols, err := listColumns(db, "tasks")
	if err != nil {
		return err
	}
	type add struct {
		name string
		stmt string
	}
	need := []add{
		{"last_error", "ALTER TABLE tasks ADD COLUMN last_error TEXT;"},
		{"attempts", "ALTER TABLE tasks ADD COLUMN attempts INTEGER DEFAULT 0;"},
		{"max_retries", "ALTER TABLE tasks ADD COLUMN max_retries INTEGER DEFAULT 0;"},
	}
	for _, item := range need {
		if !cols[item.name] {
			if _, err := db.Exec(item.stmt); err != nil {
				return err
			}
		}
	}
	return nil
}

func listColumns(db *sql.DB, table string) (map[string]bool, error) {
	rows, err := db.Query(`PRAGMA table_info(` + table + `);`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	cols := make(map[string]bool)
	for rows.Next() {
		var cid int
		var name, ctype string
		var notnull int
		var dflt sql.NullString
		var pk int
		if err := rows.Scan(&cid, &name, &ctype, &notnull, &dflt, &pk); err != nil {
			return nil, err
		}
		cols[name] = true
	}
	return cols, nil
}

func findLatestDir(baseDir string) (string, error) {
	entries, err := os.ReadDir(baseDir)
	if err != nil {
		return "", err
	}
	var latestPath string
	var latestTime time.Time
	for _, entry := range entries {
		if !entry.IsDir() {
			continue
		}
		info, err := entry.Info()
		if err != nil {
			continue
		}
		if latestPath == "" || info.ModTime().After(latestTime) {
			latestPath = filepath.Join(baseDir, entry.Name())
			latestTime = info.ModTime()
		}
	}
	return latestPath, nil
}

func timePtrToString(t *time.Time) string {
	if t == nil {
		return ""
	}
	return t.Format(time.RFC3339)
}

func parseTime(val string) time.Time {
	if val == "" {
		return time.Time{}
	}
	t, err := time.Parse(time.RFC3339, val)
	if err != nil {
		return time.Time{}
	}
	return t
}

func parseTimePtr(val string) *time.Time {
	if val == "" {
		return nil
	}
	t, err := time.Parse(time.RFC3339, val)
	if err != nil {
		return nil
	}
	return &t
}

func toString(v any) string {
	switch val := v.(type) {
	case string:
		return val
	case float64:
		return strconv.FormatInt(int64(val), 10)
	case int64:
		return strconv.FormatInt(val, 10)
	case int:
		return strconv.Itoa(val)
	default:
		return ""
	}
}
