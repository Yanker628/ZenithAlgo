package services

import (
	"context"
	"encoding/json"
	"fmt"

	"github.com/google/uuid"
	"github.com/redis/go-redis/v9"
	"github.com/zenithalgo/api/internal/models"
)

type JobService struct {
	redis *redis.Client
}

func NewJobService(redis *redis.Client) *JobService {
	return &JobService{redis: redis}
}

// SubmitBacktest 提交回测任务
func (s *JobService) SubmitBacktest(ctx context.Context, req models.JobRequest) (string, error) {
	jobID := uuid.New().String()

	// 构造 Python Worker 识别的 Payload
	// 对应 Python 端的 BacktestJob: { job_id: str, config: dict }
	payload := map[string]interface{}{
		"job_id": jobID,
		"config": req.Config,
	}

	data, err := json.Marshal(payload)
	if err != nil {
		return "", fmt.Errorf("failed to marshal job payload: %w", err)
	}

	// Push 到 Redis 队列 (zenith:jobs:queue)
	if err := s.redis.LPush(ctx, "zenith:jobs:queue", data).Err(); err != nil {
		return "", fmt.Errorf("failed to push job to redis: %w", err)
	}

	return jobID, nil
}
