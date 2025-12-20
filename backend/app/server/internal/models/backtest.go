package models

import (
	"database/sql/driver"
	"encoding/json"
	"time"
)

// BacktestResult represents a complete backtest result
type BacktestResult struct {
	ID           int          `json:"id" db:"id"`
	RunID        string       `json:"run_id" db:"run_id"`
	Symbol       string       `json:"symbol" db:"symbol"`
	Timeframe    string       `json:"timeframe" db:"timeframe"`
	StartDate    time.Time    `json:"start_date" db:"start_date"`
	EndDate      time.Time    `json:"end_date" db:"end_date"`
	StrategyName string       `json:"strategy_name" db:"strategy_name"`
	Params       SweepParams  `json:"params" db:"params"`
	Metrics      SweepMetrics `json:"metrics"`
	Score        float64      `json:"score" db:"score"`
	Passed       bool         `json:"passed" db:"passed"`
	CreatedAt    time.Time    `json:"created_at" db:"created_at"`

	// Embedded metrics
	TotalReturn *float64 `json:"-" db:"total_return"`
	SharpeRatio *float64 `json:"-" db:"sharpe_ratio"`
	MaxDrawdown *float64 `json:"-" db:"max_drawdown"`
	WinRate     *float64 `json:"-" db:"win_rate"`
	TotalTrades *int     `json:"-" db:"total_trades"`
}

// SweepParams stored as JSONB in database
type SweepParams map[string]interface{}

// Value implements driver.Valuer for database storage
func (p SweepParams) Value() (driver.Value, error) {
	return json.Marshal(p)
}

// Scan implements sql.Scanner for database retrieval
func (p *SweepParams) Scan(value interface{}) error {
	if value == nil {
		*p = make(SweepParams)
		return nil
	}

	bytes, ok := value.([]byte)
	if !ok {
		return nil
	}

	return json.Unmarshal(bytes, p)
}

// SweepMetrics contains performance metrics
type SweepMetrics struct {
	TotalReturn float64 `json:"total_return"`
	Sharpe      float64 `json:"sharpe"`
	MaxDrawdown float64 `json:"max_drawdown"`
	WinRate     float64 `json:"win_rate"`
	TotalTrades int     `json:"total_trades"`
}

// PopulateMetrics fills Metrics from embedded fields
func (b *BacktestResult) PopulateMetrics() {
	b.Metrics = SweepMetrics{
		TotalReturn: getFloatValue(b.TotalReturn),
		Sharpe:      getFloatValue(b.SharpeRatio),
		MaxDrawdown: getFloatValue(b.MaxDrawdown),
		WinRate:     getFloatValue(b.WinRate),
		TotalTrades: getIntValue(b.TotalTrades),
	}
}

func getFloatValue(ptr *float64) float64 {
	if ptr == nil {
		return 0.0
	}
	return *ptr
}

func getIntValue(ptr *int) int {
	if ptr == nil {
		return 0
	}
	return *ptr
}

// EquityPoint represents a point in the equity curve
type EquityPoint struct {
	Timestamp   time.Time `json:"timestamp" db:"timestamp"`
	Equity      float64   `json:"equity" db:"equity"`
	Drawdown    float64   `json:"drawdown,omitempty" db:"drawdown"`
	DrawdownPct float64   `json:"drawdown_pct,omitempty" db:"drawdown_pct"`
}

// Trade represents a single trade
type Trade struct {
	Timestamp     time.Time `json:"timestamp" db:"timestamp"`
	Symbol        string    `json:"symbol" db:"symbol"`
	Side          string    `json:"side" db:"side"`
	Price         float64   `json:"price" db:"price"`
	Qty           float64   `json:"qty" db:"qty"`
	PnL           *float64  `json:"pnl" db:"pnl"`
	Commission    *float64  `json:"commission" db:"commission"`
	CumulativePnL *float64  `json:"cumulative_pnl" db:"cumulative_pnl"`
}
