#
# Copyright (c) 2025, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

"""Unified Webhook Server for Daily and Twilio PSTN calls.

This server handles both:
1. Daily-native PSTN via /api/dial endpoint (pinless dial-in)
2. Twilio+Daily SIP via /api/twilio/call endpoint

The server is deployment-agnostic and can be deployed to:
- Cloudflare Workers
- AWS Lambda
- Google Cloud Run
- Any platform that supports FastAPI/ASGI
"""

import os
from contextlib import asynccontextmanager

import aiohttp
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from loguru import logger

from handlers import daily_router, twilio_router

load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle and shared resources.

    Creates a shared aiohttp session for making HTTP requests.
    The session is reused across requests for better performance.
    """
    # Create shared HTTP session for API calls
    app.state.http_session = aiohttp.ClientSession()
    logger.info("Created shared HTTP session")
    yield
    # Clean up: close the session on shutdown
    await app.state.http_session.close()
    logger.info("Closed shared HTTP session")


app = FastAPI(
    title="Unified Webhook Server",
    description="Handles Daily-native PSTN and Twilio+Daily SIP webhooks",
    version="1.0.0",
    lifespan=lifespan,
)

# Include routers for each webhook type
app.include_router(daily_router, tags=["Daily"])
app.include_router(twilio_router, tags=["Twilio"])


@app.get("/")
async def root():
    """Root endpoint with server info."""
    return {
        "name": "Unified Webhook Server",
        "endpoints": {
            "/api/dial": "Daily pinless dial-in webhook",
            "/api/twilio/call": "Twilio call webhook",
            "/health": "Health check",
        },
    }


@app.get("/health")
async def health_check():
    """Health check endpoint.

    Returns:
        dict: Status indicating server health
    """
    return {"status": "healthy"}


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    logger.info(f"Starting Unified Webhook Server on port {port}")
    uvicorn.run("server:app", host="0.0.0.0", port=port, reload=True)
