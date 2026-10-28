import { useEffect, useRef } from 'react';
import mapboxgl from 'mapbox-gl';
import type { Vehicle, LatLng } from '../types';
import 'mapbox-gl/dist/mapbox-gl.css';

mapboxgl.accessToken = import.meta.env.VITE_MAPBOX_TOKEN ?? '';

// Inject pulse keyframe into the document once — Mapbox markers live outside
// React's render tree so App.css never reaches them.
const styleId = 'hailaride-pulse-style';
if (!document.getElementById(styleId)) {
  const s = document.createElement('style');
  s.id = styleId;
  s.textContent = `
    @keyframes hailaride-pulse {
      0%   { box-shadow: 0 0 0 0   rgba(255,107,53,0.8), 0 2px 6px rgba(0,0,0,0.4); }
      70%  { box-shadow: 0 0 0 12px rgba(255,107,53,0),   0 2px 6px rgba(0,0,0,0.4); }
      100% { box-shadow: 0 0 0 0   rgba(255,107,53,0),   0 2px 6px rgba(0,0,0,0.4); }
    }
  `;
  document.head.appendChild(s);
}

// Mountain View / San Jose center
const CENTER: [number, number] = [-121.97, 37.37];

interface Props {
  vehicles: Vehicle[];
  pickup: LatLng | null;
  dropoff: LatLng | null;
  matchedVehicleId: string | null;
  onMapClick: (latlng: LatLng) => void;
}

export default function RideMap({ vehicles, pickup, dropoff, matchedVehicleId, onMapClick }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<mapboxgl.Map | null>(null);
  const markersRef = useRef<Map<string, mapboxgl.Marker>>(new Map());
  const pickupRef = useRef<mapboxgl.Marker | null>(null);
  const dropoffRef = useRef<mapboxgl.Marker | null>(null);
  // Keep a stable ref to onMapClick so the map init effect never re-runs
  const onMapClickRef = useRef(onMapClick);
  useEffect(() => { onMapClickRef.current = onMapClick; }, [onMapClick]);

  // Init map — runs once only (no deps that change)
  useEffect(() => {
    if (!containerRef.current) return;
    const map = new mapboxgl.Map({
      container: containerRef.current,
      style: 'mapbox://styles/mapbox/dark-v11',
      center: CENTER,
      zoom: 11,
    });
    mapRef.current = map;
    map.on('click', (e) => {
      onMapClickRef.current({ lat: e.lngLat.lat, lng: e.lngLat.lng });
    });
    return () => map.remove();
  }, []);  // stable — never re-runs

  // Sync vehicle markers — update position and color in place, never remove
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    for (const v of vehicles) {
      const isMatched = v.id === matchedVehicleId;
      const color = isMatched ? '#ff6b35' : v.status === 'available' ? '#4ade80' : '#facc15';

      if (markersRef.current.has(v.id)) {
        // Update position
        markersRef.current.get(v.id)!.setLngLat([v.lng, v.lat]);
        // Update color and pulse state without removing/re-adding
        const el = markersRef.current.get(v.id)!.getElement();
        el.style.background = color;
        el.style.boxShadow = isMatched
          ? '0 0 0 4px rgba(255,107,53,0.4), 0 2px 6px rgba(0,0,0,0.4)'
          : '0 2px 6px rgba(0,0,0,0.4)';
        el.style.transform = isMatched ? 'scale(1.25)' : 'scale(1)';
        el.style.zIndex = isMatched ? '10' : '1';
        el.style.animation = isMatched ? 'hailaride-pulse 1.2s ease-in-out infinite' : 'none';
      } else {
        const el = document.createElement('div');
        el.style.cssText = `
          width: 28px; height: 28px; border-radius: 50%;
          background: ${color}; border: 2px solid #fff;
          display: flex; align-items: center; justify-content: center;
          font-size: 14px; cursor: default; box-shadow: 0 2px 6px rgba(0,0,0,0.4);
          transition: transform 0.3s ease, background 0.3s ease;
        `;
        el.textContent = '🚕';
        const marker = new mapboxgl.Marker({ element: el })
          .setLngLat([v.lng, v.lat])
          .setPopup(new mapboxgl.Popup().setHTML(`<b>Vehicle ${v.id}</b><br/>${v.status}`))
          .addTo(map);
        markersRef.current.set(v.id, marker);
      }
    }
    // Note: we intentionally keep old markers rather than pruning —
    // vehicles stay visible throughout the entire ride lifecycle.
  }, [vehicles, matchedVehicleId]);

  // Pickup marker — persists until explicitly cleared (pickup becomes null on reset)
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    if (!pickup) {
      pickupRef.current?.remove();
      pickupRef.current = null;
      return;
    }
    if (pickupRef.current) {
      // Already placed — just move it (handles edge case of re-setting pickup)
      pickupRef.current.setLngLat([pickup.lng, pickup.lat]);
    } else {
      const el = document.createElement('div');
      el.style.cssText = 'font-size: 28px; cursor: default;';
      el.textContent = '📍';
      pickupRef.current = new mapboxgl.Marker({ element: el })
        .setLngLat([pickup.lng, pickup.lat])
        .addTo(map);
    }
  }, [pickup]);

  // Dropoff marker — same pattern
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    if (!dropoff) {
      dropoffRef.current?.remove();
      dropoffRef.current = null;
      return;
    }
    if (dropoffRef.current) {
      dropoffRef.current.setLngLat([dropoff.lng, dropoff.lat]);
    } else {
      const el = document.createElement('div');
      el.style.cssText = 'font-size: 28px; cursor: default;';
      el.textContent = '🏁';
      dropoffRef.current = new mapboxgl.Marker({ element: el })
        .setLngLat([dropoff.lng, dropoff.lat])
        .addTo(map);
    }
  }, [dropoff]);

  return <div ref={containerRef} style={{ width: '100%', height: '100%' }} />;
}
