/**
 * App — root component and ride-booking state machine.
 *
 * The UI is a finite state machine with five states:
 *
 *   set_pickup → set_dropoff → confirm → waiting → matched
 *                                          ↑ on error, back to confirm
 *
 * Each state change is triggered by either a map click (set_pickup/set_dropoff)
 * or a button click (confirm → waiting, matched → set_pickup via reset).
 *
 * Why a state machine instead of boolean flags?
 * Booleans like `hasPickup`, `isWaiting`, `isMatched` quickly get contradictory
 * ("what does isWaiting=true AND isMatched=true mean?"). A single `step` string
 * makes illegal states unrepresentable — only the current step's UI renders.
 *
 * Polling for ride status:
 * After POST /rides, the decider service assigns a vehicle asynchronously.
 * We poll GET /rides/:id every 1.5 s until status becomes "matched" or
 * "en_route". In production this would be a WebSocket subscription to avoid
 * polling, but for a demo the extra HTTP traffic is negligible.
 */
import { useState, useCallback } from 'react';
import RideMap from './components/RideMap';
import { useFleet } from './hooks/useFleet';
import type { LatLng, Ride } from './types';
import './App.css';

const GATEWAY = import.meta.env.VITE_GATEWAY_URL ?? 'http://localhost:8080';

// Step is the complete set of UI states — exhaustive union prevents typos.
type Step = 'set_pickup' | 'set_dropoff' | 'confirm' | 'waiting' | 'matched';

export default function App() {
  const { vehicles, connected } = useFleet();
  const [step, setStep] = useState<Step>('set_pickup');
  const [pickup, setPickup] = useState<LatLng | null>(null);
  const [dropoff, setDropoff] = useState<LatLng | null>(null);
  const [ride, setRide] = useState<Ride | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleMapClick = useCallback((latlng: LatLng) => {
    if (step === 'set_pickup') {
      setPickup(latlng);
      setStep('set_dropoff');
    } else if (step === 'set_dropoff') {
      setDropoff(latlng);
      setStep('confirm');
    }
  }, [step]);

  const requestRide = async () => {
    if (!pickup || !dropoff) return;
    setStep('waiting');
    setError(null);
    try {
      const res = await fetch(`${GATEWAY}/rides`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pickup, dropoff }),
      });
      if (!res.ok) throw new Error('Failed to request ride');
      const data: Ride = await res.json();
      setRide(data);

      // Poll for match
      const poll = setInterval(async () => {
        const r = await fetch(`${GATEWAY}/rides/${data.id}`);
        const updated: Ride = await r.json();
        setRide(updated);
        if (updated.status === 'matched' || updated.status === 'en_route') {
          clearInterval(poll);
          setStep('matched');
        }
      }, 1500);
    } catch (e) {
      setError('Could not connect to gateway. Is it running?');
      setStep('confirm');
    }
  };

  const reset = () => {
    setStep('set_pickup');
    setPickup(null);
    setDropoff(null);
    setRide(null);
    setError(null);
  };

  const stepLabel: Record<Step, string> = {
    set_pickup: '📍 Tap the map to set your pickup',
    set_dropoff: '🏁 Now tap to set your dropoff',
    confirm: '✅ Ready to request your ride',
    waiting: '⏳ Finding your driver…',
    matched: '🚕 Driver matched!',
  };

  return (
    <div className="app">
      {/* Header */}
      <header className="header">
        <div className="logo">🚕 HailARide</div>
        <div className={`status-dot ${connected ? 'live' : 'offline'}`} title={connected ? 'Live' : 'Connecting…'} />
      </header>

      {/* Map */}
      <div className="map-wrap">
        <RideMap
          vehicles={vehicles}
          pickup={pickup}
          dropoff={dropoff}
          matchedVehicleId={ride?.vehicle_id ?? null}
          onMapClick={handleMapClick}
        />
      </div>

      {/* Panel */}
      <div className="panel">
        <p className="step-label">{stepLabel[step]}</p>

        {pickup && (
          <div className="coord-row">
            <span>📍 Pickup</span>
            <span>{pickup.lat.toFixed(4)}, {pickup.lng.toFixed(4)}</span>
          </div>
        )}
        {dropoff && (
          <div className="coord-row">
            <span>🏁 Dropoff</span>
            <span>{dropoff.lat.toFixed(4)}, {dropoff.lng.toFixed(4)}</span>
          </div>
        )}

        {step === 'confirm' && (
          <button className="btn-primary" onClick={requestRide}>
            Hail a Ride
          </button>
        )}

        {step === 'waiting' && (
          <div className="spinner-row">
            <span className="spinner" />
            <span>Dispatching…</span>
          </div>
        )}

        {step === 'matched' && ride && (
          <div className="match-card">
            <div className="match-message">{ride.message}</div>
            <div className="match-meta">Vehicle: <strong>{ride.vehicle_id}</strong></div>
            <button className="btn-secondary" onClick={reset}>New Ride</button>
          </div>
        )}

        {error && <p className="error">{error}</p>}

        <div className="fleet-count">
          {vehicles.filter(v => v.status === 'available').length} vehicles available · {vehicles.length} total
        </div>
      </div>
    </div>
  );
}
