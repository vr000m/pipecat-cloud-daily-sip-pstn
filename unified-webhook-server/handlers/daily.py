#
# Copyright (c) 2025, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

"""Daily pinless dial-in webhook handler.

Handles incoming calls via Daily's native PSTN infrastructure.
Endpoint: /api/dial

Supports two modes:
- Production: Calls Pipecat Cloud API to start the bot
- Local: Creates room via Daily API and calls local bot's /start endpoint
"""

import os
import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from loguru import logger

from models import DailyDialRequest
from utils import validate_hmac_signature

router = APIRouter()


async def create_daily_room(
    http_session,
    room_properties: Dict[str, Any],
    daily_api_key: str,
    daily_api_url: str = "https://api.daily.co/v1",
) -> Dict[str, Any]:
    """Create a Daily room for local development.

    Args:
        http_session: aiohttp ClientSession
        room_properties: Room configuration (exp, sip, enable_dialout, etc.)
        daily_api_key: Daily API key
        daily_api_url: Daily API URL (default: production, includes /v1)

    Returns:
        Dict with room_url, token, and room details

    Raises:
        HTTPException: If room creation fails
    """
    # Create the room
    async with http_session.post(
        f"{daily_api_url}/rooms",
        headers={
            "Authorization": f"Bearer {daily_api_key}",
            "Content-Type": "application/json",
        },
        json={"properties": room_properties},
    ) as response:
        if response.status != 200:
            error_text = await response.text()
            raise HTTPException(
                status_code=500,
                detail=f"Failed to create Daily room: {error_text}",
            )
        room_data = await response.json()

    room_url = room_data.get("url")
    room_name = room_data.get("name")

    # Create a meeting token
    async with http_session.post(
        f"{daily_api_url}/meeting-tokens",
        headers={
            "Authorization": f"Bearer {daily_api_key}",
            "Content-Type": "application/json",
        },
        json={
            "properties": {
                "room_name": room_name,
                "is_owner": True,
            }
        },
    ) as response:
        if response.status != 200:
            error_text = await response.text()
            raise HTTPException(
                status_code=500,
                detail=f"Failed to create meeting token: {error_text}",
            )
        token_data = await response.json()

    return {
        "room_url": room_url,
        "token": token_data.get("token"),
        "room_name": room_name,
    }


async def start_bot_local(
    http_session,
    room_url: str,
    token: str,
    body: Dict[str, Any],
    local_server_url: str = "http://localhost:7860",
) -> None:
    """Start the bot via local /start endpoint.

    Args:
        http_session: aiohttp ClientSession
        room_url: Daily room URL
        token: Meeting token
        body: Request body containing dialin_settings, etc.
        local_server_url: URL of local bot server

    Raises:
        HTTPException: If bot start fails
    """
    logger.debug(f"Starting bot via local /start endpoint: {local_server_url}")

    # Include room_url/token in body as well for bots that use RunnerArguments
    local_body = body.copy()
    local_body["room_url"] = room_url
    local_body["token"] = token

    async with http_session.post(
        f"{local_server_url}/start",
        headers={"Content-Type": "application/json"},
        json={
            "room_url": room_url,
            "token": token,
            "body": local_body,
        },
    ) as response:
        if response.status != 200:
            error_text = await response.text()
            raise HTTPException(
                status_code=500,
                detail=f"Failed to start bot locally: {error_text}",
            )
        logger.debug("Bot started successfully via local /start endpoint")


@router.post("/api/dial")
async def dial(request: DailyDialRequest, raw_request: Request):
    """Handle Daily pinless dial-in webhook.

    This endpoint:
    1. Validates HMAC signature (if configured)
    2. Builds Daily room properties based on request
    3. Calls Pipecat Cloud API to start the bot
    4. Returns room properties and response data

    Returns:
        JSON response with status and room properties
    """
    start_time = time.time()

    # Get raw body for logging and HMAC validation
    raw_body = await raw_request.body()
    raw_body_str = raw_body.decode()

    logger.info("Incoming request to /api/dial")
    logger.debug(f"Headers: {dict(raw_request.headers)}")
    logger.debug(f"Raw body: {raw_body_str}")
    logger.debug(f"Parsed body: {request.model_dump()}")

    # Validate HMAC signature
    hmac_secret = os.getenv("PINLESS_HMAC_SECRET")
    timestamp = raw_request.headers.get("x-pinless-timestamp")
    signature = raw_request.headers.get("x-pinless-signature")

    if not validate_hmac_signature(hmac_secret, timestamp, raw_body_str, signature):
        elapsed_time = time.time() - start_time
        logger.info(f"Request failed with 401 (Invalid signature) - Duration: {elapsed_time:.3f}s")
        raise HTTPException(status_code=401, detail="Invalid signature")

    # Handle test requests
    if request.test == "test":
        logger.debug("Test request received")
        elapsed_time = time.time() - start_time
        logger.info(f"Test request completed successfully - Duration: {elapsed_time:.3f}s")
        return {"status": "success", "message": "Test request received"}

    # Build dialin_settings from request fields
    dialin_settings = None
    request_dict = request.model_dump()
    required_fields = ["To", "From", "callId", "callDomain"]

    if all(field in request_dict and request_dict[field] is not None for field in required_fields):
        dialin_settings = {
            "From": request.From,
            "To": request.To,
            "call_id": request.callId,
            "call_domain": request.callDomain,
        }
        logger.debug(f"Populated dialin_settings from request: {dialin_settings}")

    # Build Daily room properties
    daily_room_properties = {
        "enable_dialout": request.dialout_settings is not None,
    }

    if dialin_settings is not None:
        sip_config = {
            "display_name": request.From,
            "sip_mode": "dial-in",
            "num_endpoints": 2 if request.call_transfer is not None else 1,
            # "codecs": {"audio": ["PCMU"]},
            "video": False,
        }
        daily_room_properties["sip"] = sip_config

    # Set room expiry (5 minutes from now)
    daily_room_properties["exp"] = int(time.time()) + (5 * 60)

    logger.debug(f"Daily room properties: {daily_room_properties}")

    # Build the body to send to the bot
    bot_body = {
        "dialin_settings": dialin_settings,
        "dialout_settings": request.dialout_settings,
        "voicemail_detection": request.voicemail_detection,
        "call_transfer": request.call_transfer,
        "sip_headers": request.sipHeaders,
    }

    http_session = raw_request.app.state.http_session

    # Check if we're in local development mode
    if os.getenv("ENV") == "local":
        # Local mode: Create room via Daily API and call local bot
        daily_api_key = os.getenv("DAILY_API_KEY")
        if not daily_api_key:
            elapsed_time = time.time() - start_time
            logger.error("DAILY_API_KEY not set for local mode")
            raise HTTPException(status_code=500, detail="DAILY_API_KEY required for local mode")

        daily_api_url = os.getenv("DAILY_API_URL", "https://api.daily.co")
        local_server_url = os.getenv("LOCAL_SERVER_URL", "http://localhost:7860")

        logger.info(f"Local mode: Creating Daily room and calling bot at {local_server_url}")

        try:
            # Create Daily room
            room_data = await create_daily_room(
                http_session,
                daily_room_properties,
                daily_api_key,
                daily_api_url,
            )

            # Add Daily API credentials to body (bot needs these for pinlessCallUpdate)
            bot_body["daily_api_key"] = daily_api_key
            bot_body["daily_api_url"] = daily_api_url

            # Start the local bot
            await start_bot_local(
                http_session,
                room_data["room_url"],
                room_data["token"],
                bot_body,
                local_server_url,
            )

            elapsed_time = time.time() - start_time
            logger.info(f"Local request completed successfully - Duration: {elapsed_time:.3f}s")

            return {
                "status": "success",
                "mode": "local",
                "room_url": room_data["room_url"],
                "room_properties": daily_room_properties,
            }

        except HTTPException:
            raise
        except Exception as e:
            elapsed_time = time.time() - start_time
            logger.error(f"Local mode error: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

    else:
        # Production mode: Call Pipecat Cloud API
        payload = {
            "createDailyRoom": True,
            "dailyRoomProperties": daily_room_properties,
            "body": bot_body,
        }

        agent_name = os.getenv("AGENT_NAME", "my-first-agent")

        if os.getenv("DAILY_ENV") == "staging":
            pcc_api_key = os.getenv("PIPECAT_CLOUD_API_KEY_STAGING")
            url = f"https://staging.qa.pipecat.cloud/v1/public/{agent_name}/start"
        else:
            pcc_api_key = os.getenv("PIPECAT_CLOUD_API_KEY")
            url = f"https://api.pipecat.daily.co/v1/public/{agent_name}/start"

        if not pcc_api_key:
            elapsed_time = time.time() - start_time
            logger.error("PIPECAT_CLOUD_API_KEY not set")
            raise HTTPException(status_code=500, detail="PIPECAT_CLOUD_API_KEY not set")

        headers = {"Authorization": f"Bearer {pcc_api_key}", "Content-Type": "application/json"}

        logger.debug(f"Making API call to Pipecat Cloud: {url}")

        try:
            async with http_session.post(url, json=payload, headers=headers) as response:
                response_text = await response.text()

                if response.status != 200:
                    elapsed_time = time.time() - start_time
                    logger.error(f"HTTP error: {response_text}")
                    logger.info(
                        f"Request failed with {response.status} (HTTP error from Pipecat Cloud) - Duration: {elapsed_time:.3f}s"
                    )
                    raise HTTPException(status_code=response.status, detail=response_text)

                response_data = await response.json()
                logger.debug(f"Response: {response_data}")

                elapsed_time = time.time() - start_time
                logger.info(f"Request completed successfully - Duration: {elapsed_time:.3f}s")

                return {
                    "status": "success",
                    "mode": "production",
                    "data": response_data,
                    "room_properties": daily_room_properties,
                }

        except HTTPException:
            raise
        except Exception as e:
            elapsed_time = time.time() - start_time
            logger.error(f"Request error: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))
