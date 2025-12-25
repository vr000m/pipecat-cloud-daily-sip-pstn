#
# Copyright (c) 2025, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

"""Daily pinless dial-in webhook handler.

Handles incoming calls via Daily's native PSTN infrastructure.
Endpoint: /api/dial
"""

import os
import time

from fastapi import APIRouter, HTTPException, Request
from loguru import logger

from models import DailyDialRequest
from utils import validate_hmac_signature

router = APIRouter()


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
            "codecs": {"audio": ["PCMU"]},
            "video": False,
        }
        daily_room_properties["sip"] = sip_config

    # Set room expiry (5 minutes from now)
    daily_room_properties["exp"] = int(time.time()) + (5 * 60)

    logger.debug(f"Daily room properties: {daily_room_properties}")

    # Build payload for Pipecat Cloud API
    payload = {
        "createDailyRoom": True,
        "dailyRoomProperties": daily_room_properties,
        "body": {
            "dialin_settings": dialin_settings,
            "dialout_settings": request.dialout_settings,
            "voicemail_detection": request.voicemail_detection,
            "call_transfer": request.call_transfer,
            "sip_headers": request.sipHeaders,
        },
    }

    # Get API configuration
    agent_name = os.getenv("AGENT_NAME", "my-first-agent")

    if os.getenv("DAILY_ENV") == "staging":
        pcc_api_key = os.getenv("PIPECAT_CLOUD_API_KEY_STAGING")
        url = f"https://staging.qa.pipecat.cloud/v1/public/{agent_name}/start"
    else:
        pcc_api_key = os.getenv("PIPECAT_CLOUD_API_KEY")
        url = f"https://api.pipecat.daily.co/v1/public/{agent_name}/start"

    if not pcc_api_key:
        elapsed_time = time.time() - start_time
        logger.error(
            f"Request failed with 500 (PIPECAT_CLOUD_API_KEY not set) - Duration: {elapsed_time:.3f}s"
        )
        raise HTTPException(status_code=500, detail="PIPECAT_CLOUD_API_KEY not set")

    headers = {"Authorization": f"Bearer {pcc_api_key}", "Content-Type": "application/json"}

    logger.debug(f"Making API call to Pipecat Cloud: {url}")

    # Make async HTTP request to Pipecat Cloud
    http_session = raw_request.app.state.http_session

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
                "data": response_data,
                "room_properties": daily_room_properties,
            }

    except HTTPException:
        raise
    except Exception as e:
        elapsed_time = time.time() - start_time
        logger.error(f"Request error: {str(e)}")
        logger.info(f"Request failed with 500 (Request exception) - Duration: {elapsed_time:.3f}s")
        raise HTTPException(status_code=500, detail=str(e))
