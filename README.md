# HailARide 🚕

Autonomous ride-hailing service — Waymo + Zoox style, built with a polyglot architecture.

## Architecture

```
hailaride/
├── gateway/      Go — API gateway, fleet coordinator, WebSocket push
├── decider/      Python — FastAPI + Strands Decider 2B + Amazon Bedrock
└── dashboard/    TypeScript/React — Live Mapbox map, rider UI
```

## Stack

| Layer | Tech |
|-------|------|
| API Gateway | Go, goroutines, WebSockets |
| AI Decisions | Python, FastAPI, AWS Strands Decider 2B, Amazon Bedrock |
| Database | Amazon DynamoDB |
| Map | Mapbox GL JS |
| Frontend | React, TypeScript, Vite |

## Services

### gateway (`:8080`)
- `POST /rides` — request a ride
- `GET /rides/:id` — ride status
- `GET /vehicles` — fleet positions
- `WS /ws` — real-time vehicle location push to rider

### decider (`:8001`)
- `POST /decide` — Strands Decider 2B picks the best vehicle
- `POST /message` — Bedrock generates rider-facing status message

### dashboard
- Live map of simulated vehicles in Mountain View / San Jose
- Rider request flow: enter pickup → see nearest vehicle → track ride

## Getting Started

```bash
# Gateway
cd gateway && go run ./cmd/server

# Decider
cd decider && pip install -e ".[decider]" && uvicorn main:app --port 8001

# Dashboard
cd dashboard && npm install && npm run dev
```

## Simulated Area
Mountain View / San Jose, CA — 10 fake vehicles with randomized positions.
