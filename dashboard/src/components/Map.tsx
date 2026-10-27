import { useEffect, useRef } from 'react';
import mapboxgl from 'mapbox-gl';
import type { Vehicle, LatLng } from '../types';
import 'mapbox-gl/dist/mapbox-gl.css';

mapboxgl.accessToken = import.meta.env.VITE_MAPBOX_TOKEN ?? '';

// Mountain View / San Jose center
const CENTER: [number, number] = [-121.97, 37.37];

interface Props {
  vehicles: Vehicle[];
  pickup: LatLng | null;
  dropoff: LatLng | null;
  matchedVehicleId: string | null;
  onMapClick: (latlng: LatLng) => void;
}

export default function Map({ vehicles, pickup, dropoff, matchedVehicleId, onMapClick }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<mapboxgl.Map | null>(null);
  const markersRef = useRef<Map<string, mapboxgl.Marker>>(new Map());
  const pickupRef = useRef<mapboxgl.Marker | null>(null);
  const dropoffRef = useRef<mapboxgl.Marker | null>(null);

  // Init map
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
      onMapClick({ lat: e.lngLat.lat, lng: e.lngLat.lng });
    });
    return () => map.remove();
  }, [onMapClick]);

  // Sync vehicle markers
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    const seen = new Set<string>();
    for (const v of vehicles) {
      seen.add(v.id);
      const isMatched = v.id === matchedVehicleId;
      const color = isMatched ? '#ff6b35' : v.status === 'available' ? '#4ade80' : '#facc15';

      if (markersRef.current.has(v.id)) {
        markersRef.current.get(v.id)!.setLngLat([v.lng, v.lat]);
      } else {
        const el = document.createElement('div');
        el.style.cssText = `
          width: 28px; height: 28px; border-radius: 50%;
          background: ${color}; border: 2px solid #fff;
          display: flex; align-items: center; justify-content: center;
          font-size: 14px; cursor: default; box-shadow: 0 2px 6px rgba(0,0,0,0.4);
        `;
        el.textContent = '🚕';
        const marker = new mapboxgl.Marker({ element: el })
          .setLngLat([v.lng, v.lat])
          .setPopup(new mapboxgl.Popup().setHTML(`<b>Vehicle ${v.id}</b><br/>${v.status}`))
          .addTo(map);
        markersRef.current.set(v.id, marker);
      }
    }

    // Remove stale markers
    for (const [id, marker] of markersRef.current) {
      if (!seen.has(id)) {
        marker.remove();
        markersRef.current.delete(id);
      }
    }
  }, [vehicles, matchedVehicleId]);

  // Pickup marker
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    pickupRef.current?.remove();
    if (pickup) {
      const el = document.createElement('div');
      el.style.cssText = 'font-size: 28px; cursor: default;';
      el.textContent = '📍';
      pickupRef.current = new mapboxgl.Marker({ element: el })
        .setLngLat([pickup.lng, pickup.lat])
        .addTo(map);
    }
  }, [pickup]);

  // Dropoff marker
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    dropoffRef.current?.remove();
    if (dropoff) {
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
