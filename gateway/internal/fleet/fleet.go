// Package fleet manages simulated vehicles in Mountain View / San Jose.
package fleet

import (
	"math/rand"
	"sync"
	"time"

	"github.com/google/uuid"
)

type Status string

const (
	StatusAvailable Status = "available"
	StatusEnRoute   Status = "en_route"
	StatusPickup    Status = "pickup"
)

type Vehicle struct {
	ID     string  `json:"id"`
	Lat    float64 `json:"lat"`
	Lng    float64 `json:"lng"`
	Status Status  `json:"status"`
}

// Bounding box: Mountain View / San Jose area
const (
	minLat = 37.30
	maxLat = 37.45
	minLng = -122.10
	maxLng = -121.85
)

type Fleet struct {
	mu       sync.RWMutex
	vehicles map[string]*Vehicle
}

func New(count int) *Fleet {
	f := &Fleet{vehicles: make(map[string]*Vehicle, count)}
	for i := 0; i < count; i++ {
		id := uuid.New().String()[:8]
		f.vehicles[id] = &Vehicle{
			ID:     id,
			Lat:    minLat + rand.Float64()*(maxLat-minLat),
			Lng:    minLng + rand.Float64()*(maxLng-minLng),
			Status: StatusAvailable,
		}
	}
	return f
}

// StartSimulation drifts vehicles slightly every tick.
func (f *Fleet) StartSimulation(interval time.Duration) {
	go func() {
		for range time.Tick(interval) {
			f.mu.Lock()
			for _, v := range f.vehicles {
				if v.Status == StatusAvailable {
					v.Lat += (rand.Float64() - 0.5) * 0.002
					v.Lng += (rand.Float64() - 0.5) * 0.002
					// clamp
					if v.Lat < minLat { v.Lat = minLat }
					if v.Lat > maxLat { v.Lat = maxLat }
					if v.Lng < minLng { v.Lng = minLng }
					if v.Lng > maxLng { v.Lng = maxLng }
				}
			}
			f.mu.Unlock()
		}
	}()
}

func (f *Fleet) All() []Vehicle {
	f.mu.RLock()
	defer f.mu.RUnlock()
	out := make([]Vehicle, 0, len(f.vehicles))
	for _, v := range f.vehicles {
		out = append(out, *v)
	}
	return out
}

func (f *Fleet) Get(id string) (Vehicle, bool) {
	f.mu.RLock()
	defer f.mu.RUnlock()
	v, ok := f.vehicles[id]
	if !ok {
		return Vehicle{}, false
	}
	return *v, true
}

func (f *Fleet) SetStatus(id string, s Status) {
	f.mu.Lock()
	defer f.mu.Unlock()
	if v, ok := f.vehicles[id]; ok {
		v.Status = s
	}
}
