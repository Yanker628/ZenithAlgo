package main

import (
	"log"

	"github.com/gin-gonic/gin"
	"github.com/zenithalgo/api/internal/database"
	"github.com/zenithalgo/api/internal/handlers"
	myredis "github.com/zenithalgo/api/internal/infrastructure/redis"
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

	// Initialize Redis
	rdb, err := myredis.NewClient(myredis.Config{
		Addr: "localhost:6379",
		DB:   0,
	})
	if err != nil {
		log.Fatalf("Failed to connect to Redis: %v", err)
	}
	log.Println("✅ Connected to Redis")

	// Initialize services
	backtestService := services.NewBacktestService(db)
	jobService := services.NewJobService(rdb)
	wsHub := services.NewWSHub(rdb)

	// Start WS Hub
	go wsHub.Run()

	// Initialize handlers
	backtestHandler := handlers.NewBacktestHandler(backtestService)
	jobHandler := handlers.NewJobHandler(jobService)
	wsHandler := handlers.NewWSHandler(wsHub)

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

		// RaaS Routes
		api.POST("/backtest", jobHandler.SubmitBacktest)
		api.GET("/ws", wsHandler.HandleWS)
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
