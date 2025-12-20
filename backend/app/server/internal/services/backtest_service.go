package services

import (
	"fmt"
	"sync"

	"github.com/jmoiron/sqlx"
	"github.com/zenithalgo/api/internal/models"
)

type BacktestService struct {
	db *sqlx.DB
	mu sync.RWMutex
}

func NewBacktestService(db *sqlx.DB) *BacktestService {
	return &BacktestService{
		db: db,
	}
}

// GetAllResults returns all backtest results with optional filters
func (s *BacktestService) GetAllResults(limit int, offset int, sortBy string, order string) ([]*models.BacktestResult, int, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()

	// Validate sort column
	validSorts := map[string]bool{
		"score": true, "total_return": true, "sharpe_ratio": true,
		"max_drawdown": true, "created_at": true,
	}
	if !validSorts[sortBy] {
		sortBy = "score"
	}

	if order != "ASC" && order != "DESC" {
		order = "DESC"
	}

	// Get total count
	var total int
	err := s.db.Get(&total, "SELECT COUNT(*) FROM backtests")
	if err != nil {
		return nil, 0, fmt.Errorf("failed to get total count: %w", err)
	}

	// Get results
	query := fmt.Sprintf(`
		SELECT 
			id, run_id, symbol, timeframe, start_date, end_date,
			strategy_name, params,
			total_return, sharpe_ratio, max_drawdown, win_rate, total_trades,
			score, passed, created_at
		FROM backtests
		ORDER BY %s %s
		LIMIT $1 OFFSET $2
	`, sortBy, order)

	rows, err := s.db.Queryx(query, limit, offset)
	if err != nil {
		return nil, 0, fmt.Errorf("failed to query backtests: %w", err)
	}
	defer rows.Close()

	results := make([]*models.BacktestResult, 0, limit)
	for rows.Next() {
		var result models.BacktestResult
		err := rows.StructScan(&result)
		if err != nil {
			continue
		}
		results = append(results, &result)
	}

	return results, total, nil
}

// GetResult returns a single backtest by ID
func (s *BacktestService) GetResult(id string) (*models.BacktestResult, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()

	var result models.BacktestResult
	err := s.db.Get(&result, `
		SELECT 
			id, run_id, symbol, timeframe, start_date, end_date,
			strategy_name, params,
			total_return, sharpe_ratio, max_drawdown, win_rate, total_trades,
			score, passed, created_at
		FROM backtests
		WHERE id = $1 OR run_id = $2
	`, id, id)

	if err != nil {
		return nil, fmt.Errorf("backtest not found: %w", err)
	}

	return &result, nil
}

// GetEquityCurve returns equity curve data for a backtest
func (s *BacktestService) GetEquityCurve(backtestID string) ([]models.EquityPoint, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()

	// First get the backtest to get the internal ID
	result, err := s.GetResult(backtestID)
	if err != nil {
		return nil, err
	}

	var points []models.EquityPoint
	err = s.db.Select(&points, `
		SELECT timestamp, equity, drawdown, drawdown_pct
		FROM equity_curves
		WHERE backtest_id = $1
		ORDER BY timestamp ASC
	`, result.ID)

	if err != nil {
		return nil, fmt.Errorf("failed to get equity curve: %w", err)
	}

	return points, nil
}

// GetTrades returns trade data for a backtest
func (s *BacktestService) GetTrades(backtestID string) ([]models.Trade, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()

	// First get the backtest to get the internal ID
	result, err := s.GetResult(backtestID)
	if err != nil {
		return nil, err
	}

	var trades []models.Trade
	err = s.db.Select(&trades, `
		SELECT timestamp, symbol, side, price, qty, pnl, commission, cumulative_pnl
		FROM trades
		WHERE backtest_id = $1
		ORDER BY timestamp ASC
	`, result.ID)

	if err != nil {
		return nil, fmt.Errorf("failed to get trades: %w", err)
	}

	return trades, nil
}
