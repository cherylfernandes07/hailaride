// Package rides manages ride lifecycle.
package rides

import (
	"sync"
	"time"

	"github.com/google/uuid"
)

type RideStatus string

const (
	RideRequested RideStatus = "requested"
	RideMatched   RideStatus = "matched"
	RideEnRoute   RideStatus = "en_route"
	RideCompleted RideStatus = "completed"
)

type Location struct {
	Lat float64 `json:"lat"`
	Lng float64 `json:"lng"`
}

type Ride struct {
	ID        string     `json:"id"`
	Pickup    Location   `json:"pickup"`
	Dropoff   Location   `json:"dropoff"`
	VehicleID string     `json:"vehicle_id,omitempty"`
	Status    RideStatus `json:"status"`
	Message   string     `json:"message,omitempty"` // Bedrock-generated rider message
	CreatedAt time.Time  `json:"created_at"`
}

type Store struct {
	mu    sync.RWMutex
	rides map[string]*Ride
}

func NewStore() *Store {
	return &Store{rides: make(map[string]*Ride)}
}

func (s *Store) Create(pickup, dropoff Location) *Ride {
	r := &Ride{
		ID:        uuid.New().String()[:8],
		Pickup:    pickup,
		Dropoff:   dropoff,
		Status:    RideRequested,
		CreatedAt: time.Now(),
	}
	s.mu.Lock()
	s.rides[r.ID] = r
	s.mu.Unlock()
	return r
}

func (s *Store) Get(id string) (*Ride, bool) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	r, ok := s.rides[id]
	return r, ok
}

func (s *Store) Update(id string, fn func(*Ride)) bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	r, ok := s.rides[id]
	if !ok {
		return false
	}
	fn(r)
	return true
}
