# HailARide 🚕

Autonomous ride-hailing service — Waymo + Zoox style, built with a polyglot architecture.
Submitted to the **Strands Decider 2B Hackathon**.

## Decision Pattern: Tool Selection

Every ride request triggers a **Strands Decider 2B** decision: given a fleet of available
vehicles, the agent selects the best one to dispatch. This is a high-frequency, repeated
decision made on every ride — exactly where Decider 2B's ~115ms latency and low cost
show their advantage over a frontier model.

```
Rider requests pickup
       │
       ▼
Go gateway collects available vehicles
       │
       ▼
Python decider: Strands Decider 2B scores candidates → selects vehicle  ← THE DECISION
       │
       ▼
Bedrock Nova Micro writes rider-facing status message
       │
       ▼
Gateway marks vehicle en_route, pushes match via WebSocket to dashboard
```

**Pattern declared:** Tool Selection — the agent decides which vehicle (tool) to dispatch.

**Reusable pattern:** [`patterns/vehicle_dispatch.py`](patterns/vehicle_dispatch.py) —
a self-contained, drop-in Strands Decider 2B decision you can adapt for any
"pick best option from scored list" scenario.

---

## Architecture

```
hailaride/
├── gateway/      Go — API gateway, fleet coordinator, WebSocket push
├── decider/      Python — FastAPI + Strands Decider 2B + Amazon Bedrock Nova
├── dashboard/    TypeScript/React — Live Mapbox map, rider UI
└── patterns/     Reusable Strands Decider 2B decision patterns
```

## Stack

| Layer | Tech |
|-------|------|
| API Gateway | Go, goroutines, WebSockets |
| AI Decisions | Python, FastAPI, Strands Agents SDK, Strands Decider 2B |
| Message Generation | Amazon Bedrock Nova Micro (`us.amazon.nova-micro-v1:0`) |
| Database | In-memory (DynamoDB-ready) |
| Map | Mapbox GL JS |
| Frontend | React, TypeScript, Vite |

## Services

### gateway (`:8080`)
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/vehicles` | All fleet positions |
| POST | `/rides` | Request a ride |
| GET | `/rides/:id` | Ride status |
| WS | `/ws` | Real-time vehicle location push |

### decider (`:8001`)
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |
| POST | `/decide` | Strands Decider 2B picks vehicle + Bedrock writes message |

### dashboard (`:3000`)
- Dark Mapbox map centered on Mountain View / San Jose
- 10 simulated vehicles drifting in real time
- Tap map → set pickup → set dropoff → Hail a Ride → see matched driver

## Getting Started

### Prerequisites
- Go 1.22+
- Python 3.11+
- Node.js 20+
- AWS account with Bedrock Nova Micro enabled (`us.amazon.nova-micro-v1:0`)
- Mapbox token (free at mapbox.com)

### Setup

**Gateway**
```bash
cd gateway
go mod tidy
go run ./cmd/server
```

**Decider**
```bash
cd decider
python -m venv .venv && source .venv/bin/activate
pip install -e ".[decider,dev]"

# Create .env
cp /dev/null .env
echo "AWS_ACCESS_KEY_ID=your_key" >> .env
echo "AWS_SECRET_ACCESS_KEY=your_secret" >> .env
echo "AWS_REGION=us-east-2" >> .env
echo "BEDROCK_MODEL_ID=us.amazon.nova-micro-v1:0" >> .env

uvicorn main:app --port 8001 --reload
```

**Dashboard**
```bash
cd dashboard
cp .env.example .env
# Edit .env — add your Mapbox token
npm install && npm run dev
```

Open **http://localhost:3000**

### Try the reusable pattern standalone
```bash
cd decider
source .venv/bin/activate
python ../patterns/vehicle_dispatch.py
```

## Reusable Decision Pattern

[`patterns/vehicle_dispatch.py`](patterns/vehicle_dispatch.py) is a standalone,
documented Strands Decider 2B pattern that any builder can drop into their own agent.

It demonstrates:
- Pre-scoring candidates on a numeric dimension before passing to Decider 2B
- Formatting a clear decision prompt with ranked options
- Parsing the model's response robustly with a fallback
- Wiring a bare `Agent(model=BedrockModel(...))` call for pure decision tasks

Adapt it for: ticket routing, tool selection, model routing, memory ranking.

---

## What's Working

- 10 simulated vehicles drifting in real time across Mountain View / San Jose
- Tap map → set pickup → set dropoff → Hail a Ride
- Strands Decider 2B selects the best vehicle on every request
- Matched vehicle turns orange, pulses, and drives toward your pickup pin
- Bedrock Nova Micro generates a friendly rider status message
- Bedrock Guardrail filters all rider-facing messages for content safety
- WebSocket push keeps the map live without polling

## Track 3 — Million-Scale Architecture

> **Vercel + AWS Databases hackathon** — scaling HailARide to 1M+ concurrent rides.

### What changed

| Layer | Before | After |
|-------|--------|-------|
| Ride store | In-memory Go map | **DynamoDB** (serverless, on-demand, TTL 24h) |
| WebSocket fan-out | Single goroutine | **ElastiCache Redis** pub/sub across ECS replicas |
| Frontend deploy | `npm run dev` | **Vercel** (global CDN, zero-config) |
| Services | Bare processes | **Docker containers** (ECS Fargate ready) |

### Run the full stack locally

```bash
cp .env.example .env
# Fill in AWS credentials + Mapbox token
docker compose up --build
# open http://localhost:3000
```

DynamoDB Local runs in the stack — no AWS account needed for local dev.

### Deploy to production

**Dashboard → Vercel**
```bash
cd dashboard
vercel          # connects repo, sets env vars in dashboard
```
Set `VITE_GATEWAY_URL` to your ALB endpoint in Vercel project settings.

**Backend → ECS Fargate** (after pushing images to ECR)
```bash
# Gateway
docker build -t hailaride-gateway ./gateway
# Decider
docker build -t hailaride-decider ./decider
```
Point the ECS task definitions at your ECR images. Set `DYNAMODB_TABLE=hailaride-rides` (no `DYNAMODB_ENDPOINT` = real DynamoDB).

### Architecture

```
Rider browser (React · Vercel CDN)
        │  HTTPS + WSS
        ▼
    AWS ALB  (sticky sessions, TLS termination)
        │
   ┌────┴────────────────────┐
   ▼                         ▼
Go Gateway (ECS)    Python Decider (ECS)
   │  WebSocket hub       Strands Decider 2B
   │  Fleet coordinator   Bedrock Nova Micro
   │                      Bedrock Guardrails
   ├──── ElastiCache Redis  (WS pub/sub, fleet state)
   └──── DynamoDB           (ride records, TTL 24h)
                   │
            Amazon Bedrock (Nova Micro · Guardrails)
```

**Why DynamoDB scales to 1M+ rides:**
- On-demand capacity — no pre-provisioning; AWS scales reads/writes automatically
- Single-digit millisecond latency at any throughput
- Ride records TTL-expire after 24 hours — no cleanup job needed
- Each ECS replica talks directly to DynamoDB — no connection pooling bottleneck

**Why ElastiCache Redis for WebSockets:**
- A single Go WebSocket hub can't span multiple ECS containers
- Redis pub/sub broadcasts a gateway message to all connected hubs across all replicas
- Sub-millisecond fan-out to all connected riders regardless of which container their WebSocket is on

### Future Work

- **Authentication** — add Cognito for rider and driver identities
- **Real routing** — replace haversine straight-line with Mapbox Directions API for turn-by-turn navigation
- **Surge pricing decision** — second Decider 2B pattern: classify demand level and adjust pricing tier
- **Multi-region fleet** — Route 53 latency routing, replicate DynamoDB globally
- **Serverless decider** — `template.yaml` (AWS SAM) deploys the Python decider as Lambda behind API Gateway
- **Observability** — CloudWatch metrics + Bedrock invocation logs for latency and cost per decision
- **Load testing** — k6 script to simulate 1M concurrent ride requests against the ECS stack
