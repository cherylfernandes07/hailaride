"""
╔══════════════════════════════════════════════════════════════════════════╗
║  REUSABLE STRANDS DECIDER 2B PATTERN: Tool Selection                     ║
║  Pattern: Pick the best option from a scored candidate list              ║
║  Demonstrated by: HailARide — autonomous ride-hailing agent              ║
╚══════════════════════════════════════════════════════════════════════════╝

WHAT THIS PATTERN DOES
──────────────────────
Given a list of options that have already been pre-scored on a numeric
dimension (distance, cost, priority, confidence), this pattern uses Strands
Decider 2B to make the final selection. The model considers the scores AND
any contextual reasoning (e.g. traffic, availability, urgency) that pure
math cannot capture.

In HailARide, "options" are vehicles and the scoring dimension is distance
to the rider's pickup. You can swap in any domain:
  - Support tickets  →  assign to the best available agent
  - API tools        →  decide which tool to call from the user's intent
  - Memory chunks    →  pick the most relevant context to inject
  - Model routing    →  decide frontier vs. smaller model for a query

WHEN TO USE THIS PATTERN
────────────────────────
✅ You have 2–10 discrete options to choose between
✅ Options can be pre-ranked on at least one numeric dimension
✅ The decision repeats frequently (every request) — Decider 2B is fast
✅ You want explainability: the model can reason about its choice
❌ You have only 1 option (no decision needed)
❌ Options are continuous values (use a ranking algorithm instead)

HOW TO DROP THIS INTO YOUR OWN AGENT
─────────────────────────────────────
1. Install dependencies:
      pip install strands-agents strands-agents-tools boto3

2. Copy the `run_dispatch_decision()` function below into your agent.

3. Replace the `Candidate` dataclass with your own option type.

4. Replace the `score()` function with your own scoring logic.

5. Adjust the decision prompt to describe YOUR decision context.

6. Call `run_dispatch_decision(options, context)` wherever your agent
   needs to make the selection.

WIRING INTO A STRANDS AGENT
────────────────────────────
This pattern uses a bare `Agent(model=BedrockModel(...))` call — no tools,
no InterventionHandler needed. Decider 2B acts as a pure reasoning model.
To wire it as an InterventionHandler instead (to intercept every tool call),
see the Strands docs: https://strandsagents.com/docs/intervention-handlers

EXAMPLE OUTPUT
──────────────
Input candidates:
  Vehicle a1b2c3d4 — 1.2 km away
  Vehicle e5f6g7h8 — 3.4 km away
  Vehicle i9j0k1l2 — 0.9 km away

Decider 2B response: "i9j0k1l2"
Selected: i9j0k1l2 (closest, 0.9 km)
"""

import math
import logging
from dataclasses import dataclass

from strands import Agent
from strands.models import BedrockModel

log = logging.getLogger(__name__)

# ── Configure your Bedrock model ─────────────────────────────────────────────
# Swap model_id and region_name to match your AWS setup.
# Nova Micro is recommended: fast, cheap, text-only, ideal for decisions.

MODEL_ID = "us.amazon.nova-micro-v1:0"
AWS_REGION = "us-east-2"


# ── Option type ───────────────────────────────────────────────────────────────
# Replace this with your own option dataclass.
# The only requirement: each option needs a unique `id` field.

@dataclass
class Candidate:
    """
    Represents one selectable option.
    In HailARide this is a vehicle; in your agent it could be anything.
    """
    id: str        # unique identifier — Decider 2B returns this
    lat: float     # position (domain-specific; replace with your own fields)
    lng: float


# ── Scoring function ──────────────────────────────────────────────────────────
# Replace with your own scoring logic.
# Lower score = better candidate (sort ascending before passing to Decider 2B).

def score(candidate: Candidate, pickup_lat: float, pickup_lng: float) -> float:
    """
    Haversine distance in km — lower is better.
    Swap this for your own metric: latency, cost, priority score, etc.
    """
    R = 6371.0
    phi1 = math.radians(candidate.lat)
    phi2 = math.radians(pickup_lat)
    dphi = math.radians(pickup_lat - candidate.lat)
    dlambda = math.radians(pickup_lng - candidate.lng)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ── Core reusable pattern ─────────────────────────────────────────────────────

def run_dispatch_decision(
    candidates: list[Candidate],
    pickup_lat: float,
    pickup_lng: float,
    context: str = "",
) -> str:
    """
    Uses Strands Decider 2B to select the best candidate from a scored list.

    This is the drop-in function. Adapt the prompt and scoring to your domain.

    Args:
        candidates:  List of options to choose between (your Candidate type).
        pickup_lat:  Context value used for scoring (replace with your own).
        pickup_lng:  Context value used for scoring (replace with your own).
        context:     Optional extra context string passed to the model
                     (e.g. "rider is in a hurry", "prefer green vehicles").

    Returns:
        The `id` of the selected candidate as a string.
        Falls back to the top-scored candidate if Decider 2B is unavailable.

    Usage:
        candidates = [Candidate("v1", 37.37, -122.1), Candidate("v2", 37.40, -122.0)]
        winner = run_dispatch_decision(candidates, pickup_lat=37.38, pickup_lng=-122.05)
        print(winner)  # "v1"
    """
    if not candidates:
        raise ValueError("No candidates provided")

    if len(candidates) == 1:
        return candidates[0].id  # trivial case — no decision needed

    # Pre-score and sort so Decider 2B receives ranked options
    ranked = sorted(candidates, key=lambda c: score(c, pickup_lat, pickup_lng))

    # Build the decision prompt
    # ── CUSTOMISE THIS SECTION FOR YOUR DOMAIN ──
    options_text = "\n".join([
        f"- Option {c.id}: score={score(c, pickup_lat, pickup_lng):.2f}"
        for c in ranked[:5]
    ])

    prompt = (
        f"You are making a dispatch decision for an autonomous ride service.\n\n"
        f"Context: {context or 'standard pickup request'}\n\n"
        f"Available options (lower score = closer to pickup):\n{options_text}\n\n"
        f"Select the single best option. "
        f"Reply with ONLY the option ID, nothing else."
    )
    # ── END CUSTOMISE ──

    try:
        model = BedrockModel(model_id=MODEL_ID, region_name=AWS_REGION)
        agent = Agent(model=model)
        response = agent(prompt)

        selected_id = str(response).strip().split()[0]
        known_ids = {c.id for c in candidates}

        if selected_id in known_ids:
            log.info(f"Decider 2B selected: {selected_id}")
            return selected_id

        # Fallback: scan response text for any known ID
        for c in ranked:
            if c.id in str(response):
                log.info(f"Decider 2B (parsed) selected: {c.id}")
                return c.id

        raise ValueError(f"No valid ID in response: {response}")

    except Exception as e:
        fallback = ranked[0].id
        log.warning(f"Decider 2B unavailable, using top-scored option {fallback}: {e}")
        return fallback


# ── Standalone demo ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    """
    Run this file directly to test the pattern:
        python patterns/vehicle_dispatch.py

    Make sure AWS credentials are set and Nova Micro is enabled in Bedrock.
    """
    logging.basicConfig(level=logging.INFO)

    demo_candidates = [
        Candidate("alpha-01", lat=37.38, lng=-122.08),
        Candidate("bravo-02", lat=37.41, lng=-122.05),
        Candidate("charlie-03", lat=37.35, lng=-122.12),
    ]
    pickup_lat, pickup_lng = 37.37, -122.10

    print("\n── HailARide Vehicle Dispatch — Strands Decider 2B Demo ──\n")
    for c in demo_candidates:
        d = score(c, pickup_lat, pickup_lng)
        print(f"  {c.id}: {d:.2f} km away")

    print("\nCalling Strands Decider 2B...\n")
    winner = run_dispatch_decision(demo_candidates, pickup_lat, pickup_lng)
    print(f"\n✅ Selected vehicle: {winner}")
