package services

import (
	"context"
	"encoding/json"
	"log"
	"time"

	"github.com/redis/go-redis/v9"
	"github.com/zenithalgo/api/internal/models"
)

type ResultPersister struct {
	redis           *redis.Client
	backtestService *BacktestService
}

func NewResultPersister(rdb *redis.Client, bs *BacktestService) *ResultPersister {
	return &ResultPersister{
		redis:           rdb,
		backtestService: bs,
	}
}

func (p *ResultPersister) Start() {
	go p.listenLoop()
}

func (p *ResultPersister) listenLoop() {
	ctx := context.Background()
	pubsub := p.redis.Subscribe(ctx, "zenith:jobs:updates")
	defer pubsub.Close()

	ch := pubsub.Channel()
	for msg := range ch {
		var data map[string]interface{}
		if err := json.Unmarshal([]byte(msg.Payload), &data); err != nil {
			log.Printf("Persister: failed to unmarshal msg: %v", err)
			continue
		}

		if data["type"] == "success" {
			log.Printf("Persister: Received success for job %v, saving...", data["job_id"])
			p.handleSuccess(data)
		}
	}
}

func (p *ResultPersister) handleSuccess(data map[string]interface{}) {
	// Parse Summary
	summary, ok := data["summary"].(map[string]interface{})
	if !ok {
		log.Println("Persister: summary missing or invalid")
		return
	}

	// 1. Map BacktestResult
	metrics, _ := summary["metrics"].(map[string]interface{})

	result := &models.BacktestResult{
		RunID:        data["job_id"].(string), // Use job_id as run_id
		Symbol:       getString(summary["data_health"], "symbol"),
		Timeframe:    getString(summary["data_health"], "interval"),
		StartDate:    parseTime(getString(summary["data_health"], "start")),
		EndDate:      parseTime(getString(summary["data_health"], "end")),
		StrategyName: "unknown",            // TODO: Get from job config if available, here hardcode or infer
		Params:       models.SweepParams{}, // Empty for now, Python summary doesn't carry full params back yet
		Metrics: models.SweepMetrics{
			TotalReturn: getFloat(metrics, "total_return"),
			Sharpe:      getFloat(metrics, "sharpe"),
			MaxDrawdown: getFloat(metrics, "max_drawdown"),
			WinRate:     getFloat(metrics, "win_rate"),
			TotalTrades: int(getFloat(metrics, "total_trades")),
		},
		Score:  getFloat(metrics, "total_return"), // Default score = return
		Passed: true,
	}

	// 2. Map Trades
	var trades []models.Trade
	if rawTrades, ok := summary["trades"].([]interface{}); ok {
		for _, t := range rawTrades {
			tm := t.(map[string]interface{})
			trades = append(trades, models.Trade{
				Timestamp:     parseTime(getString(tm, "ts")),
				Symbol:        getString(tm, "symbol"),
				Side:          getString(tm, "side"),
				Price:         getFloat(tm, "price"),
				Qty:           getFloat(tm, "qty"),
				PnL:           getFloatPtr(tm, "pnl"),
				Commission:    getFloatPtr(tm, "commission"),
				CumulativePnL: getFloatPtr(tm, "cumulative_pnl"), // Assuming python calculates simple cum sum or we do it
			})
		}
	}

	// 3. Map Equity Curve
	var equity []models.EquityPoint
	if rawEq, ok := summary["equity_curve"].([]interface{}); ok {
		peak := -1e9
		for _, e := range rawEq {
			em := e.(map[string]interface{})
			eqVal := getFloat(em, "equity")
			if eqVal > peak {
				peak = eqVal
			}
			dd := peak - eqVal
			ddPct := 0.0
			if peak > 0 {
				ddPct = dd / peak
			}

			equity = append(equity, models.EquityPoint{
				Timestamp:   parseTime(getString(em, "ts")),
				Equity:      eqVal,
				Drawdown:    dd,
				DrawdownPct: ddPct,
			})
		}
	}

	// Save
	if err := p.backtestService.SaveResult(result, trades, equity); err != nil {
		log.Printf("Persister: Failed to save result: %v", err)
	} else {
		log.Printf("Persister: Result saved successfully for job %v", result.RunID)
	}
}

// Helpers
func getString(obj interface{}, key string) string {
	if m, ok := obj.(map[string]interface{}); ok {
		if v, ok := m[key].(string); ok {
			return v
		}
	}
	return ""
}

func getFloat(m map[string]interface{}, key string) float64 {
	if v, ok := m[key].(float64); ok {
		return v
	}
	return 0.0
}

func getFloatPtr(m map[string]interface{}, key string) *float64 {
	if v, ok := m[key].(float64); ok {
		return &v
	}
	return nil
}

func parseTime(s string) time.Time {
	// Try parsing ISO/RFC3339
	t, _ := time.Parse(time.RFC3339, s)
	return t
}
