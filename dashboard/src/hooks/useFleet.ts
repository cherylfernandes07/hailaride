/**
 * useFleet — custom React hook that maintains a live WebSocket connection
 * to the Go gateway and streams real-time vehicle positions to the map.
 *
 * Design decisions worth knowing for an interview:
 *
 * 1. Custom hook (not a component) — keeps connection logic out of the render
 *    tree. Any component can call useFleet() and get the same vehicle list
 *    without prop-drilling or a global store.
 *
 * 2. useCallback for `connect` — wraps the reconnect function so useEffect's
 *    dependency array stays stable. Without this, a new `connect` reference
 *    on every render would cause the effect to re-run and re-open the socket
 *    infinitely.
 *
 * 3. Auto-reconnect on close — the gateway or the network can drop the
 *    connection; `ws.onclose` schedules a reconnect after 2 s so the dashboard
 *    self-heals without a page reload.
 *
 * 4. Error handler closes — `ws.onerror` fires before `ws.onclose` in the
 *    browser. Explicitly calling ws.close() here triggers the onclose handler
 *    and therefore the reconnect path, keeping the two handlers in sync.
 *
 * 5. Cleanup on unmount — the useEffect return fn closes the socket so React
 *    StrictMode's double-invoke doesn't leave zombie connections open in dev.
 */
import { useEffect, useRef, useState, useCallback } from 'react';
import type { Vehicle, WsMessage } from '../types';

// VITE_GATEWAY_URL is injected at build time (see .env.example).
// Falls back to localhost so the app works without any env setup.
const GATEWAY = import.meta.env.VITE_GATEWAY_URL ?? 'http://localhost:8080';
const WS_URL = GATEWAY.replace('http', 'ws') + '/ws';

export function useFleet() {
  const [vehicles, setVehicles] = useState<Vehicle[]>([]);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);

  const connect = useCallback(() => {
    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;

    ws.onopen = () => setConnected(true);
    ws.onclose = () => {
      setConnected(false);
      // Auto-reconnect: schedule a fresh connect after 2 s.
      // This handles both network blips and gateway restarts.
      setTimeout(connect, 2000);
    };
    // onerror fires before onclose — close explicitly to trigger reconnect.
    ws.onerror = () => ws.close();

    ws.onmessage = (evt) => {
      try {
        const msg: WsMessage = JSON.parse(evt.data);
        // The gateway sends {type: "fleet_update", vehicles: [...]} every 500ms.
        // Other message types are ignored for forward-compatibility.
        if (msg.type === 'fleet_update') {
          setVehicles(msg.vehicles);
        }
      } catch {
        // ignore malformed frames — never crash on bad server data
      }
    };
  }, []);

  useEffect(() => {
    connect();
    // Cleanup: close on unmount (important for React StrictMode double-invoke)
    return () => wsRef.current?.close();
  }, [connect]);

  return { vehicles, connected };
}
