package services

import (
	"context"
	"log"
	"sync"

	"github.com/gorilla/websocket"
	"github.com/redis/go-redis/v9"
)

type WSHub struct {
	clients    map[*websocket.Conn]bool
	broadcast  chan []byte
	register   chan *websocket.Conn
	unregister chan *websocket.Conn
	redis      *redis.Client
	mu         sync.Mutex
}

func NewWSHub(rdb *redis.Client) *WSHub {
	return &WSHub{
		clients:    make(map[*websocket.Conn]bool),
		broadcast:  make(chan []byte),
		register:   make(chan *websocket.Conn),
		unregister: make(chan *websocket.Conn),
		redis:      rdb,
	}
}

func (h *WSHub) Run() {
	// Start Redis Subscriber in background
	go h.subscribeRedis()

	for {
		select {
		case client := <-h.register:
			h.mu.Lock()
			h.clients[client] = true
			h.mu.Unlock()
			log.Println("WS: Client connected")

		case client := <-h.unregister:
			h.mu.Lock()
			if _, ok := h.clients[client]; ok {
				delete(h.clients, client)
				client.Close()
				log.Println("WS: Client disconnected")
			}
			h.mu.Unlock()

		case message := <-h.broadcast:
			h.mu.Lock()
			for client := range h.clients {
				err := client.WriteMessage(websocket.TextMessage, message)
				if err != nil {
					log.Printf("WS: Write error: %v, closing client", err)
					client.Close()
					delete(h.clients, client)
				}
			}
			h.mu.Unlock()
		}
	}
}

func (h *WSHub) subscribeRedis() {
	ctx := context.Background()
	pubsub := h.redis.Subscribe(ctx, "zenith:jobs:updates")
	defer pubsub.Close()

	ch := pubsub.Channel()
	for msg := range ch {
		// msg.Payload is the JSON string
		h.broadcast <- []byte(msg.Payload)
	}
}

// 辅助结构，用于 WS Handler 调用
func (h *WSHub) RegisterClient(conn *websocket.Conn) {
	h.register <- conn
}

func (h *WSHub) UnregisterClient(conn *websocket.Conn) {
	h.unregister <- conn
}
