"""
HailARide — Decider Service
FastAPI service that picks the best vehicle using distance scoring.
Bedrock generates the rider-facing status message.
"""

import math
import json
import os
import logging
from typing import Optional

import boto3
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("decider")

app = FastAPI(title="HailARide Decider", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Bedrock client — uses AWS env vars or instance role
bedrock = boto3.client(
    "bedrock-runtime",
    region_name=os.getenv("AWS_REGION", "us-west-2"),
)

MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "amazon.titan-text-lite-v1")


# ── Models ──────────────────────────────────────────────────────────────────

class LatLng(BaseModel):
    lat: float
    lng: float


class Candidate(BaseModel):
    id: str
    lat: float
    lng: float


class DecideRequest(BaseModel):
    ride_id: str
    pickup: LatLng
    candidates: list[Candidate]


class DecideResponse(BaseModel):
    vehicle_id: str
    distance_km: float
    message: str


# ── Helpers ──────────────────────────────────────────────────────────────────

def haversine(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in km."""
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def score_vehicle(candidate: Candidate, pickup: LatLng) -> float:
    """
    Lower is better.
    Primary: distance to pickup.
    Future: add ETA, battery level, rating, demand zone weighting.
    """
    dist = haversine(candidate.lat, candidate.lng, pickup.lat, pickup.lng)
    return dist


def generate_message(vehicle_id: str, distance_km: float) -> str:
    """Ask Bedrock to generate a friendly rider status message."""
    eta_min = max(1, int(distance_km / 0.4))  # rough: 0.4 km/min in city
    prompt = (
        f"You are a friendly autonomous ride assistant. "
        f"A rider just requested a pickup. Vehicle {vehicle_id} is {distance_km:.1f} km away "
        f"and will arrive in approximately {eta_min} minutes. "
        f"Write a single short, friendly status message (under 20 words) for the rider app. "
        f"Do not include quotation marks."
    )

    try:
        body = json.dumps({
            "inputText": prompt,
            "textGenerationConfig": {
                "maxTokenCount": 60,
                "temperature": 0.7,
            },
        })
        resp = bedrock.invoke_model(modelId=MODEL_ID, body=body)
        result = json.loads(resp["body"].read())
        return result["results"][0]["outputText"].strip()
    except Exception as e:
        log.warning(f"Bedrock call failed, using fallback message: {e}")
        eta_min = max(1, int(distance_km / 0.4))
        return f"Your ride is on the way — arriving in ~{eta_min} min. 🚗"


# ── Routes ───────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "service": "decider"}


@app.post("/decide", response_model=DecideResponse)
def decide(req: DecideRequest):
    if not req.candidates:
        raise HTTPException(status_code=503, detail="No available vehicles")

    # Score each candidate — pick lowest
    best = min(req.candidates, key=lambda c: score_vehicle(c, req.pickup))
    dist = haversine(best.lat, best.lng, req.pickup.lat, req.pickup.lng)

    log.info(f"ride={req.ride_id} → vehicle={best.id} dist={dist:.2f}km")

    message = generate_message(best.id, dist)

    return DecideResponse(
        vehicle_id=best.id,
        distance_km=round(dist, 2),
        message=message,
    )
