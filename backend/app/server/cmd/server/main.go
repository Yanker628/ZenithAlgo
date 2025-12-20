package main

import (
	"log"

	"github.com/gin-gonic/gin"
	"github.com/zenithalgo/api/internal/database"
	"github.com/zenithalgo/api/internal/handlers"
	"github.com/zenithalgo/api/internal/middleware"
	"github.com/zenithalgo/api/internal/services"
)

func main() {
	// Initialize database connection
	db, err := database.NewPostgresDB()
	if err != nil {
		log.Fatalf("Failed to connect to database: %v", err)
	}
	defer db.Close()

	log.Println("✅ Connected to PostgreSQL database")

	// Initialize services
	backtestService := services.NewBacktestService(db)

	// Initialize handlers
	backtestHandler := handlers.NewBacktestHandler(backtestService)

	// Setup router
	router := gin.Default()

	// Apply CORS middleware
	router.Use(middleware.SetupCORS())

	// API routes
	api := router.Group("/api")
	{
		api.GET("/sweep/results", backtestHandler.GetSweepResults)
		api.GET("/backtest/:id/equity", backtestHandler.GetEquityCurve)
		api.GET("/backtest/:id/trades", backtestHandler.GetTrades)
	}

	// Health check
	router.GET("/health", backtestHandler.HealthCheck)

	// Start server
	log.Println("🚀 Starting API server on http://localhost:8080")
	log.Println("   Database: PostgreSQL")
	if err := router.Run(":8080"); err != nil {
		log.Fatalf("Failed to start server: %v", err)
	}
}
