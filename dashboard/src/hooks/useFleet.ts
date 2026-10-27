import { useEffect, useRef, useState, useCallback } from 'react';
import type { Vehicle, WsMessage } from '../types';

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
      // Reconnect after 2s
      setTimeout(connect, 2000);
    };
    ws.onerror = () => ws.close();

    ws.onmessage = (evt) => {
      try {
        const msg: WsMessage = JSON.parse(evt.data);
        if (msg.type === 'fleet_update') {
          setVehicles(msg.vehicles);
        }
      } catch {
        // ignore malformed frames
      }
    };
  }, []);

  useEffect(() => {
    connect();
    return () => wsRef.current?.close();
  }, [connect]);

  return { vehicles, connected };
}
