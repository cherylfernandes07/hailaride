export interface Vehicle {
  id: string;
  lat: number;
  lng: number;
  status: 'available' | 'en_route' | 'pickup';
}

export interface LatLng {
  lat: number;
  lng: number;
}

export interface Ride {
  id: string;
  pickup: LatLng;
  dropoff: LatLng;
  vehicle_id?: string;
  status: 'requested' | 'matched' | 'en_route' | 'completed';
  message?: string;
  created_at: string;
}

export type WsMessage =
  | { type: 'fleet_update'; vehicles: Vehicle[] }
  | { type: 'ride_matched'; ride_id: string; vehicle_id: string; message: string };
