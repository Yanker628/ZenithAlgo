package handlers

import (
	"fmt"
	"net/http"
	"strconv"

	"github.com/gin-gonic/gin"
	"github.com/zenithalgo/api/internal/services"
)

type BacktestHandler struct {
	service *services.BacktestService
}

func NewBacktestHandler(service *services.BacktestService) *BacktestHandler {
	return &BacktestHandler{service: service}
}

// GetSweepResults handles GET /api/sweep/results
func (h *BacktestHandler) GetSweepResults(c *gin.Context) {
	// Parse query parameters
	limit, _ := strconv.Atoi(c.DefaultQuery("limit", "20"))
	offset, _ := strconv.Atoi(c.DefaultQuery("offset", "0"))
	sortBy := c.DefaultQuery("sort", "score")
	order := c.DefaultQuery("order", "DESC")

	results, total, err := h.service.GetAllResults(limit, offset, sortBy, order)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}

	// Populate metrics for each result
	for _, r := range results {
		r.PopulateMetrics()
	}

	c.JSON(http.StatusOK, gin.H{
		"total":   total,
		"limit":   limit,
		"offset":  offset,
		"results": results,
	})
}

// GetEquityCurve handles GET /api/backtest/:id/equity
func (h *BacktestHandler) GetEquityCurve(c *gin.Context) {
	id := c.Param("id")

	result, err := h.service.GetResult(id)
	if err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "Backtest not found"})
		return
	}

	// Get equity curve
	equityData, err := h.service.GetEquityCurve(id)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": fmt.Sprintf("Failed to load equity data: %v", err),
		})
		return
	}

	if len(equityData) == 0 {
		c.JSON(http.StatusOK, gin.H{
			"backtest_id": id,
			"symbol":      result.Symbol,
			"data":        []interface{}{},
			"message":     "No equity curve available for this backtest",
		})
		return
	}

	result.PopulateMetrics()

	c.JSON(http.StatusOK, gin.H{
		"backtest_id": id,
		"symbol":      result.Symbol,
		"params":      result.Params,
		"metrics":     result.Metrics,
		"data":        equityData,
	})
}

// GetTrades handles GET /api/backtest/:id/trades
func (h *BacktestHandler) GetTrades(c *gin.Context) {
	id := c.Param("id")

	result, err := h.service.GetResult(id)
	if err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "Backtest not found"})
		return
	}

	// Get trades
	trades, err := h.service.GetTrades(id)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": fmt.Sprintf("Failed to load trades: %v", err),
		})
		return
	}

	c.JSON(http.StatusOK, gin.H{
		"backtest_id": id,
		"symbol":      result.Symbol,
		"total":       len(trades),
		"trades":      trades, // Already includes pnl, commission, cumulative_pnl from DB
	})
}

// HealthCheck handles GET /health
func (h *BacktestHandler) HealthCheck(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{
		"status":   "ok",
		"version":  "2.0.0",
		"database": "postgresql",
	})
}
