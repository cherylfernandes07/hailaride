"""
HailARide — Decider Service
===========================
FastAPI microservice that uses the Strands Agents SDK + Strands Decider 2B
to select the best available vehicle for a ride request.

Decision pattern demonstrated: TOOL SELECTION
  The agent is given a set of candidate vehicles and must decide which one
  to dispatch. Decider 2B scores each candidate against the pickup location
  and returns the winning vehicle ID. This is a repeated, high-frequency
  decision — every ride request triggers it — which is exactly where
  Decider 2B's speed (~115ms) and low cost shine.

Reusable decision pattern (drop into your own agent):
  See `vehicle_dispatch_decision()` below. The typed DecisionQuestion and
  option set can be adapted for any "pick the best item from a scored list"
  scenario: assigning support tickets, routing API calls, selecting tools.

Requirements:
  pip install -e ".[decider,dev]"
  AWS credentials with bedrock:InvokeModel permission
  BEDROCK_MODEL_ID=us.amazon.nova-micro-v1:0
  AWS_REGION=us-east-2
"""

import math
import json
import os
import logging
from typing import Optional

import boto3
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Strands Agents SDK — Decider 2B lives here
from strands import Agent
from strands.models import BedrockModel

load_dotenv()

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("decider")

# ── App setup ────────────────────────────────────────────────────────────────

app = FastAPI(title="HailARide Decider", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── AWS clients ──────────────────────────────────────────────────────────────

AWS_REGION = os.getenv("AWS_REGION", "us-east-2")
BEDROCK_MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "us.amazon.nova-micro-v1:0")
GUARDRAIL_ID = os.getenv("BEDROCK_GUARDRAIL_ID", "")
GUARDRAIL_VERSION = os.getenv("BEDROCK_GUARDRAIL_VERSION", "1")

# Bedrock client for Nova message generation
bedrock_runtime = boto3.client("bedrock-runtime", region_name=AWS_REGION)

# Strands BedrockModel — wraps the same Nova endpoint for Decider 2B
strands_model = BedrockModel(
    model_id=BEDROCK_MODEL_ID,
    region_name=AWS_REGION,
)


# ── Pydantic models ──────────────────────────────────────────────────────────

class LatLng(BaseModel):
    """Geographic coordinate pair."""
    lat: float
    lng: float


class Candidate(BaseModel):
    """
    A single vehicle candidate available for dispatch.
    The id field matches the vehicle ID in the Go fleet simulator.
    """
    id: str
    lat: float
    lng: float


class DecideRequest(BaseModel):
    """
    Incoming request body from the Go gateway's dispatchRide goroutine.
    Contains the ride ID, the rider's pickup location, and all available
    vehicle candidates at the moment of the request.
    """
    ride_id: str
    pickup: LatLng
    candidates: list[Candidate]


class DecideResponse(BaseModel):
    """
    Response sent back to the Go gateway after Decider 2B selects a vehicle.
    The gateway uses vehicle_id to mark that vehicle as en_route and
    broadcasts the message to the rider's dashboard via WebSocket.
    """
    vehicle_id: str
    distance_km: float
    message: str


# ── Haversine distance ───────────────────────────────────────────────────────

def haversine(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """
    Calculate the great-circle distance in kilometres between two points
    on Earth using the Haversine formula.

    This is used to:
      1. Pre-score candidates before passing them to Decider 2B (so the
         model receives meaningful numeric context, not raw coordinates).
      2. Calculate the final pickup distance for the ETA estimate in the
         rider message.

    Args:
        lat1, lng1: Starting point (vehicle position).
        lat2, lng2: Destination point (rider pickup).

    Returns:
        Distance in kilometres as a float.
    """
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = (math.sin(dphi / 2) ** 2
         + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ── Strands Decider 2B — vehicle dispatch decision ───────────────────────────

def vehicle_dispatch_decision(candidates: list[Candidate], pickup: LatLng) -> str:
    """
    ╔══════════════════════════════════════════════════════════════════╗
    ║  REUSABLE DECISION PATTERN: Tool Selection via Strands Decider   ║
    ╠══════════════════════════════════════════════════════════════════╣
    ║  Pattern: TOOL SELECTION                                         ║
    ║  Frequency: Every ride request (high-frequency, low-latency)     ║
    ║  Model: Strands Decider 2B via BedrockModel                      ║
    ╚══════════════════════════════════════════════════════════════════╝

    Given a set of available vehicles, uses Strands Decider 2B to select
    the best one for dispatch. Decider 2B evaluates each candidate against
    the pickup location and returns the optimal vehicle ID.

    HOW TO REUSE THIS PATTERN IN YOUR OWN AGENT:
      1. Build a scored list of options (here: vehicles ranked by distance).
      2. Format them as a natural-language decision question.
      3. Pass to a Strands Agent backed by a BedrockModel.
      4. Parse the agent's response for the selected option ID.

    This same pattern works for: routing support tickets to agents,
    selecting which API tool to call, picking a memory chunk to inject,
    or classifying an incoming request into a policy category.

    Args:
        candidates: List of available vehicles with their positions.
        pickup: The rider's requested pickup location.

    Returns:
        The vehicle ID string selected by Decider 2B.
        Falls back to the closest vehicle by haversine if Strands fails.
    """
    # Pre-score candidates by distance so Decider 2B has numeric context
    scored = sorted(
        candidates,
        key=lambda c: haversine(c.lat, c.lng, pickup.lat, pickup.lng)
    )

    # Build the decision question for Decider 2B
    # Format: present each option with its key scoring factor
    options_text = "\n".join([
        f"- Vehicle {c.id}: "
        f"{haversine(c.lat, c.lng, pickup.lat, pickup.lng):.2f} km away"
        for c in scored[:5]  # top 5 closest candidates
    ])

    decision_prompt = (
        f"You are dispatching an autonomous vehicle for a ride pickup.\n\n"
        f"Pickup location: {pickup.lat:.4f}, {pickup.lng:.4f}\n\n"
        f"Available vehicles (sorted by distance):\n{options_text}\n\n"
        f"Select the single best vehicle to dispatch. "
        f"Reply with ONLY the vehicle ID (e.g. 'abc12345'), nothing else."
    )

    try:
        # Instantiate a Strands Agent backed by Decider 2B via BedrockModel
        # The agent has no tools — it is purely a decision-making model call
        agent = Agent(model=strands_model)
        response = agent(decision_prompt)

        # Extract the vehicle ID from the response
        # Decider 2B is instructed to return only the ID, so we strip
        # whitespace and validate it against our known candidate list
        selected_id = str(response).strip().split()[0]
        known_ids = {c.id for c in candidates}

        if selected_id in known_ids:
            log.info(f"Strands Decider 2B selected vehicle: {selected_id}")
            return selected_id
        else:
            # Response contained extra text — find any matching ID in it
            for c in scored:
                if c.id in str(response):
                    log.info(f"Strands Decider 2B (parsed) selected: {c.id}")
                    return c.id
            raise ValueError(f"No valid vehicle ID found in response: {response}")

    except Exception as e:
        # Fallback: if Strands Decider 2B is unavailable, use closest vehicle
        fallback_id = scored[0].id
        log.warning(
            f"Strands Decider 2B failed, falling back to closest vehicle "
            f"{fallback_id}: {e}"
        )
        return fallback_id


# ── Bedrock message generation ───────────────────────────────────────────────

def generate_rider_message(vehicle_id: str, distance_km: float) -> str:
    """
    Generates a short, friendly rider-facing status message using Amazon
    Bedrock Nova Micro.

    This is a generative text task (not a decision), so it uses the Bedrock
    client directly rather than Strands Decider 2B. Nova Micro is ideal here:
    fast, cheap, and perfectly capable of writing a single sentence.

    The prompt instructs the model to write under 20 words with no quotes,
    suitable for display in the rider app's status card.

    Args:
        vehicle_id: The ID of the matched vehicle (shown to rider).
        distance_km: Distance from vehicle to pickup, used to estimate ETA.

    Returns:
        A friendly status string, e.g. "Your driver is 2 minutes away! 🚗"
        Falls back to a hardcoded message if Bedrock is unavailable.
    """
    eta_min = max(1, int(distance_km / 0.4))  # ~0.4 km/min in city traffic
    prompt = (
        f"You are a friendly autonomous ride assistant. "
        f"A rider just requested a pickup. Vehicle {vehicle_id} is "
        f"{distance_km:.1f} km away and will arrive in approximately "
        f"{eta_min} minutes. Write a single short, friendly status message "
        f"(under 20 words) for the rider app. Do not include quotation marks."
    )

    try:
        body = json.dumps({
            "messages": [
                {
                    "role": "user",
                    "content": [{"text": prompt}],  # Nova requires array format
                }
            ],
            "inferenceConfig": {
                "maxTokens": 60,
                "temperature": 0.7,
            },
        })

        # Build invoke_model kwargs — attach Guardrail if configured
        invoke_kwargs = dict(modelId=BEDROCK_MODEL_ID, body=body)
        if GUARDRAIL_ID:
            invoke_kwargs["guardrailIdentifier"] = GUARDRAIL_ID
            invoke_kwargs["guardrailVersion"] = GUARDRAIL_VERSION
            log.info(f"Applying Bedrock Guardrail {GUARDRAIL_ID} v{GUARDRAIL_VERSION}")

        resp = bedrock_runtime.invoke_model(**invoke_kwargs)
        result = json.loads(resp["body"].read())

        # Check if guardrail blocked the response
        if result.get("amazon-bedrock-guardrailAction") == "GUARDRAIL_INTERVENED":
            log.warning("Guardrail intervened on rider message — using safe fallback")
            return f"Your driver is on the way! Arriving in ~{eta_min} min. 🚗"

        return result["output"]["message"]["content"][0]["text"].strip()

    except Exception as e:
        log.warning(f"Bedrock message generation failed, using fallback: {e}")
        return f"Your ride is on the way — arriving in ~{eta_min} min. 🚗"


# ── Routes ───────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    """
    Health check endpoint. Called by the Go gateway on startup to verify
    the decider service is reachable before accepting ride requests.

    Returns a simple JSON object with service name and status.
    """
    return {"status": "ok", "service": "hailaride-decider", "model": BEDROCK_MODEL_ID}


@app.post("/decide", response_model=DecideResponse)
def decide(req: DecideRequest):
    """
    Main decision endpoint — called by the Go gateway's dispatchRide goroutine
    for every incoming ride request.

    Flow:
      1. Validate that at least one candidate vehicle exists.
      2. Call vehicle_dispatch_decision() — Strands Decider 2B picks the vehicle.
      3. Calculate the exact pickup distance for the selected vehicle.
      4. Call generate_rider_message() — Bedrock Nova writes the status message.
      5. Return the vehicle ID, distance, and message to the gateway.

    The gateway then:
      - Marks the vehicle as en_route in the fleet store
      - Updates the ride record with the matched vehicle ID and message
      - Broadcasts a ride_matched WebSocket event to the dashboard

    Args:
        req: DecideRequest containing ride_id, pickup location, and candidates.

    Returns:
        DecideResponse with vehicle_id, distance_km, and rider message.

    Raises:
        HTTPException 503 if no candidate vehicles are available.
    """
    if not req.candidates:
        raise HTTPException(status_code=503, detail="No available vehicles")

    log.info(
        f"Decision request: ride={req.ride_id} "
        f"candidates={len(req.candidates)} "
        f"pickup=({req.pickup.lat:.4f}, {req.pickup.lng:.4f})"
    )

    # Step 1: Strands Decider 2B selects the best vehicle
    selected_id = vehicle_dispatch_decision(req.candidates, req.pickup)

    # Step 2: Calculate exact distance for the selected vehicle
    selected = next(c for c in req.candidates if c.id == selected_id)
    dist = haversine(selected.lat, selected.lng, req.pickup.lat, req.pickup.lng)

    log.info(f"Vehicle selected: {selected_id} at {dist:.2f}km")

    # Step 3: Bedrock generates a friendly rider-facing message
    message = generate_rider_message(selected_id, dist)

    log.info(f"Rider message: {message}")

    return DecideResponse(
        vehicle_id=selected_id,
        distance_km=round(dist, 2),
        message=message,
    )
