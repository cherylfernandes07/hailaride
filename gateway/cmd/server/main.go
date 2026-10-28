package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"time"

	"github.com/gorilla/mux"
	"github.com/hailaride/gateway/internal/fleet"
	"github.com/hailaride/gateway/internal/rides"
	"github.com/hailaride/gateway/internal/ws"
)

// RideStorer is the interface both in-memory and DynamoDB stores satisfy.
// Go interfaces are implicit — a type doesn't declare that it implements one,
// it just has matching method signatures. This lets us swap the backing store
// at startup without changing any of the handler code that calls it.
// Pattern: "program to an interface, not an implementation" — same idea as
// a Repository pattern in Java/C#, just expressed as a Go interface.
type RideStorer interface {
	Create(pickup, dropoff rides.Location) *rides.Ride
	Get(id string) (*rides.Ride, bool)
	Update(id string, fn func(*rides.Ride)) bool
}

var (
	deciderURL = envOr("DECIDER_URL", "http://localhost:8001")
	f          = fleet.New(10)
	rideStore  RideStorer
	hub        = ws.NewHub()
)

// initRideStore selects the ride store implementation at startup based on
// environment variables, so the same binary works in three contexts:
//   - Local dev (no env vars)  → in-memory store, zero setup
//   - Docker Compose           → DYNAMODB_ENDPOINT=http://dynamodb-local:8000
//   - Production ECS           → DYNAMODB_TABLE=hailaride-rides (real AWS)
func initRideStore() {
	// Use DynamoDB when a table name or local endpoint is configured.
	// Falls back to in-memory for plain local dev (no Docker required).
	if os.Getenv("DYNAMODB_TABLE") != "" || os.Getenv("DYNAMODB_ENDPOINT") != "" {
		store, err := rides.NewDynamoStore(context.Background())
		if err != nil {
			log.Fatalf("DynamoDB init failed: %v — set DYNAMODB_TABLE or DYNAMODB_ENDPOINT", err)
		}
		log.Printf("Ride store: DynamoDB table=%s", envOr("DYNAMODB_TABLE", "hailaride-rides"))
		rideStore = store
	} else {
		log.Printf("Ride store: in-memory (set DYNAMODB_TABLE to use DynamoDB)")
		rideStore = rides.NewStore()
	}
}

func main() {
	initRideStore()

	// Start simulated vehicle drift
	f.StartSimulation(3 * time.Second)

	// Broadcast fleet positions every 2 seconds
	go func() {
		for range time.Tick(2 * time.Second) {
			hub.Broadcast(map[string]any{
				"type":     "fleet_update",
				"vehicles": f.All(),
			})
		}
	}()

	r := mux.NewRouter()
	r.Use(corsMiddleware)

	r.HandleFunc("/vehicles", handleVehicles).Methods("GET", "OPTIONS")
	r.HandleFunc("/rides", handleRequestRide).Methods("POST", "OPTIONS")
	r.HandleFunc("/rides/{id}", handleGetRide).Methods("GET", "OPTIONS")
	r.HandleFunc("/ws", hub.ServeWS)

	port := envOr("PORT", "8080")
	log.Printf("HailARide gateway listening on :%s", port)
	log.Fatal(http.ListenAndServe(":"+port, r))
}

// GET /vehicles
func handleVehicles(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, f.All())
}

// GET /rides/:id
func handleGetRide(w http.ResponseWriter, r *http.Request) {
	id := mux.Vars(r)["id"]
	ride, ok := rideStore.Get(id)
	if !ok {
		http.Error(w, "ride not found", http.StatusNotFound)
		return
	}
	writeJSON(w, ride)
}

// POST /rides — body: { pickup: {lat,lng}, dropoff: {lat,lng} }
func handleRequestRide(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Pickup  rides.Location `json:"pickup"`
		Dropoff rides.Location `json:"dropoff"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, "bad request", http.StatusBadRequest)
		return
	}

	ride := rideStore.Create(req.Pickup, req.Dropoff)

	// Async: call decider, then update ride
	go dispatchRide(ride.ID, req.Pickup)

	w.WriteHeader(http.StatusAccepted)
	writeJSON(w, ride)
}

// dispatchRide calls the Python decider service to pick the best vehicle.
func dispatchRide(rideID string, pickup rides.Location) {
	vehicles := f.All()

	// Build candidate list for decider
	type Candidate struct {
		ID  string  `json:"id"`
		Lat float64 `json:"lat"`
		Lng float64 `json:"lng"`
	}
	candidates := make([]Candidate, 0, len(vehicles))
	for _, v := range vehicles {
		if v.Status == fleet.StatusAvailable {
			candidates = append(candidates, Candidate{v.ID, v.Lat, v.Lng})
		}
	}

	payload := map[string]any{
		"ride_id":    rideID,
		"pickup":     pickup,
		"candidates": candidates,
	}
	body, _ := json.Marshal(payload)

	resp, err := http.Post(deciderURL+"/decide", "application/json", bytes.NewReader(body))
	if err != nil {
		log.Printf("decider error for ride %s: %v", rideID, err)
		return
	}
	defer resp.Body.Close()

	var result struct {
		VehicleID string `json:"vehicle_id"`
		Message   string `json:"message"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		log.Printf("decider decode error: %v", err)
		return
	}

	// Update ride and vehicle status
	rideStore.Update(rideID, func(ride *rides.Ride) {
		ride.VehicleID = result.VehicleID
		ride.Status = rides.RideMatched
		ride.Message = result.Message
	})
	f.SetStatus(result.VehicleID, fleet.StatusEnRoute)

	// Tell the vehicle to drive toward the pickup point
	f.SetTarget(result.VehicleID, pickup.Lat, pickup.Lng)

	// Notify dashboard
	hub.Broadcast(map[string]any{
		"type":       "ride_matched",
		"ride_id":    rideID,
		"vehicle_id": result.VehicleID,
		"message":    result.Message,
	})

	log.Printf("ride %s matched to vehicle %s — driving to pickup (%.4f, %.4f)",
		rideID, result.VehicleID, pickup.Lat, pickup.Lng)
}

// helpers

func writeJSON(w http.ResponseWriter, v any) {
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(v)
}

func corsMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Access-Control-Allow-Origin", "*")
		w.Header().Set("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
		w.Header().Set("Access-Control-Allow-Headers", "Content-Type")
		if r.Method == http.MethodOptions {
			w.WriteHeader(http.StatusNoContent)
			return
		}
		next.ServeHTTP(w, r)
	})
}

func envOr(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

// suppress unused import warning during dev
var _ = fmt.Sprintf
var _ = io.Discard
