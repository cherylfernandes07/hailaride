"""
HailARide — Lambda Entry Point
==============================
Wraps the FastAPI decider app for AWS Lambda + API Gateway deployment.

Locally the app runs with uvicorn (uvicorn main:app --port 8001).
In Lambda, API Gateway events are translated to ASGI by Mangum.

Deploy:
  sam build && sam deploy --guided

The SAM output prints the API Gateway URL — set that as DECIDER_URL
in the Go gateway's environment.
"""

from dotenv import load_dotenv
load_dotenv()

from mangum import Mangum
from main import app

# Mangum translates API Gateway HTTP events → ASGI → FastAPI
handler = Mangum(app, lifespan="off")
