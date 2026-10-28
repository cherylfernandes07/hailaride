// Package ws manages WebSocket connections for real-time vehicle push.
//
// Why WebSockets instead of HTTP polling?
// Polling means the dashboard fires a GET /vehicles every N seconds — even when
// nothing changed. At 50 connected dashboards polling every second, that's 50
// req/s of wasted work. With WebSockets, the server pushes only when the
// simulation tick fires (every 500ms), and each message goes to ALL clients in
// one broadcast loop — far more efficient.
//
// Scale note: this single-process Hub works fine for a demo, but breaks at
// multiple ECS replicas — a client connected to replica A won't receive
// broadcasts from replica B. The production fix is a Redis pub/sub fan-out:
// each replica subscribes to a "fleet_updates" channel; any replica that runs
// the simulation tick publishes there; all replicas forward to their local
// clients. That's documented in the README architecture section.
package ws

import (
	"encoding/json"
	"log"
	"net/http"
	"sync"

	"github.com/gorilla/websocket"
)

// upgrader promotes a plain HTTP connection to a WebSocket connection.
// CheckOrigin returns true unconditionally — safe for local dev and demos,
// but in production you'd validate r.Header.Get("Origin") against an allowlist.
var upgrader = websocket.Upgrader{
	CheckOrigin: func(r *http.Request) bool { return true }, // allow all origins in dev
}

// Hub tracks every connected dashboard browser tab.
// mu guards the clients map so concurrent upgrades and broadcasts don't race.
type Hub struct {
	mu      sync.RWMutex
	clients map[*websocket.Conn]bool
}

func NewHub() *Hub {
	return &Hub{clients: make(map[*websocket.Conn]bool)}
}

// ServeWS upgrades the HTTP request to a WebSocket and registers the connection.
// Each connection gets its own read-loop goroutine — the goroutine blocks on
// ReadMessage (the keep-alive heartbeat), and cleans up when the browser tab
// closes or the connection drops.
func (h *Hub) ServeWS(w http.ResponseWriter, r *http.Request) {
	conn, err := upgrader.Upgrade(w, r, nil)
	if err != nil {
		log.Println("ws upgrade:", err)
		return
	}
	h.mu.Lock()
	h.clients[conn] = true
	h.mu.Unlock()

	// Keep alive — read loop discards incoming messages but detects disconnects.
	// When the browser closes the tab, ReadMessage returns an error, the defer
	// removes the connection from the Hub, and the goroutine exits cleanly.
	go func() {
		defer func() {
			h.mu.Lock()
			delete(h.clients, conn)
			h.mu.Unlock()
			conn.Close()
		}()
		for {
			if _, _, err := conn.ReadMessage(); err != nil {
				break
			}
		}
	}()
}

// Broadcast serialises v to JSON and sends it to every connected client.
// Uses RLock (read lock) because multiple goroutines could call Broadcast
// concurrently — we're only iterating the map, not modifying it.
// Note: WriteMessage is NOT goroutine-safe per connection, but each conn is
// only written to from this one broadcast path, so there's no concurrent write.
func (h *Hub) Broadcast(v any) {
	data, err := json.Marshal(v)
	if err != nil {
		return
	}
	h.mu.RLock()
	defer h.mu.RUnlock()
	for conn := range h.clients {
		if err := conn.WriteMessage(websocket.TextMessage, data); err != nil {
			log.Println("ws write:", err)
		}
	}
}
