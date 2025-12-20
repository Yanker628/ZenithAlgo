package handlers

import (
	"log"
	"net/http"

	"github.com/gin-gonic/gin"
	"github.com/gorilla/websocket"
	"github.com/zenithalgo/api/internal/services"
)

var upgrader = websocket.Upgrader{
	CheckOrigin: func(r *http.Request) bool {
		return true // Allow all origins for local dev
	},
}

type WSHandler struct {
	hub *services.WSHub
}

func NewWSHandler(hub *services.WSHub) *WSHandler {
	return &WSHandler{hub: hub}
}

func (h *WSHandler) HandleWS(c *gin.Context) {
	conn, err := upgrader.Upgrade(c.Writer, c.Request, nil)
	if err != nil {
		log.Printf("Failed to upgrade WS: %v", err)
		return
	}

	h.hub.RegisterClient(conn)

	// Keep connection alive/reader loop
	// For this simple Hub, we only push data TO client.
	// But we need to read to detect disconnects.
	go func() {
		defer h.hub.UnregisterClient(conn)
		for {
			_, _, err := conn.ReadMessage()
			if err != nil {
				break
			}
		}
	}()
}
