#
# Copyright (c) 2025, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

"""Twilio webhook handler for PSTN calls via Daily SIP.

Handles incoming Twilio calls and bridges them to Daily via SIP.
Endpoint: /api/twilio/call
"""

import os

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse
from loguru import logger
from pipecat.runner.daily import configure
from twilio.twiml.voice_response import VoiceResponse

from models import AgentRequest, TwilioCallData

router = APIRouter()


async def extract_twilio_call_data(request: Request) -> TwilioCallData:
    """Extract call data from Twilio webhook form data.

    Args:
        request: FastAPI request containing Twilio form data

    Returns:
        TwilioCallData with call_sid, from_phone, and to_phone

    Raises:
        HTTPException: If required fields are missing
    """
    form_data = await request.form()
    data = dict(form_data)

    call_sid = data.get("CallSid")
    if not call_sid:
        raise HTTPException(status_code=400, detail="Missing CallSid in request")

    from_phone = data.get("From")
    if not from_phone:
        raise HTTPException(status_code=400, detail="Missing From in request")

    to_phone = data.get("To")
    if not to_phone:
        raise HTTPException(status_code=400, detail="Missing To in request")

    return TwilioCallData(call_sid=call_sid, from_phone=from_phone, to_phone=to_phone)


async def start_bot_production(agent_request: AgentRequest, http_session) -> None:
    """Start the bot via Pipecat Cloud API.

    Args:
        agent_request: Agent configuration with room_url, token, and call details
        http_session: aiohttp ClientSession for making HTTP requests

    Raises:
        HTTPException: If API call fails or required env vars are missing
    """
    pipecat_api_key = os.getenv("PIPECAT_API_KEY")
    agent_name = os.getenv("PIPECAT_AGENT_NAME")

    if not pipecat_api_key or not agent_name:
        raise HTTPException(
            status_code=500,
            detail="PIPECAT_API_KEY and PIPECAT_AGENT_NAME required for production mode",
        )

    logger.debug(f"Starting bot via Pipecat Cloud for call {agent_request.call_sid}")

    body_data = agent_request.model_dump(exclude_none=True)

    # Support staging environment
    pipecat_hostname = os.getenv("PIPECAT_HOSTNAME", "api.pipecat.daily.co")

    async with http_session.post(
        f"https://{pipecat_hostname}/v1/public/{agent_name}/start",
        headers={
            "Authorization": f"Bearer {pipecat_api_key}",
            "Content-Type": "application/json",
        },
        json={
            "createDailyRoom": False,  # Room already created
            "body": body_data,
        },
    ) as response:
        if response.status != 200:
            error_text = await response.text()
            raise HTTPException(
                status_code=500,
                detail=f"Failed to start bot via Pipecat Cloud: {error_text}",
            )
        logger.debug("Bot started successfully via Pipecat Cloud")


async def start_bot_local(agent_request: AgentRequest, http_session) -> None:
    """Start the bot via local /start endpoint for development.

    Args:
        agent_request: Agent configuration with room_url, token, and call details
        http_session: aiohttp ClientSession for making HTTP requests

    Raises:
        HTTPException: If API call fails
    """
    local_server_url = os.getenv("LOCAL_SERVER_URL", "http://localhost:7860")

    logger.debug(f"Starting bot via local /start endpoint for call {agent_request.call_sid}")

    body_data = agent_request.model_dump(exclude_none=True)

    async with http_session.post(
        f"{local_server_url}/start",
        headers={"Content-Type": "application/json"},
        json={
            "createDailyRoom": False,  # Room already created
            "body": body_data,
        },
    ) as response:
        if response.status != 200:
            error_text = await response.text()
            raise HTTPException(
                status_code=500,
                detail=f"Failed to start bot via local /start endpoint: {error_text}",
            )
        logger.debug("Bot started successfully via local /start endpoint")


@router.post("/api/twilio/call", response_class=PlainTextResponse)
async def handle_twilio_call(request: Request):
    """Handle incoming Twilio call webhook.

    This endpoint:
    1. Extracts call data from Twilio webhook
    2. Creates a Daily room with SIP capabilities
    3. Starts the bot (locally or via Pipecat Cloud)
    4. Returns TwiML to put caller on hold while bot connects

    Returns:
        TwiML response with hold music for the caller
    """
    logger.debug("Received call webhook from Twilio")

    # Extract call data from Twilio form data
    call_data = await extract_twilio_call_data(request)
    logger.info(f"Twilio call: {call_data.call_sid} from {call_data.from_phone} to {call_data.to_phone}")

    # Create Daily room with SIP capabilities
    http_session = request.app.state.http_session

    try:
        sip_config = await configure(http_session, sip_caller_phone=call_data.from_phone)
    except Exception as e:
        logger.error(f"Error creating Daily room: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create Daily room: {e!s}")

    # Ensure we have a SIP endpoint
    if not sip_config.sip_endpoint:
        raise HTTPException(status_code=500, detail="No SIP endpoint provided by Daily")

    # Build agent request
    agent_request = AgentRequest(
        room_url=sip_config.room_url,
        token=sip_config.token,
        call_sid=call_data.call_sid,
        sip_uri=sip_config.sip_endpoint,
    )
    logger.debug(f"Agent request: {agent_request}")

    # Start bot (locally or in production)
    try:
        if os.getenv("ENV") == "production":
            await start_bot_production(agent_request, http_session)
        else:
            await start_bot_local(agent_request, http_session)
    except Exception as e:
        logger.error(f"Error starting bot: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to start bot: {e!s}")

    # Generate TwiML response with hold music
    # The caller hears this while the bot connects to the Daily room
    try:
        resp = VoiceResponse()
        resp.play(
            url="https://therapeutic-crayon-2467.twil.io/assets/US_ringback_tone.mp3",
            loop=10,
        )
        return str(resp)
    except Exception as e:
        logger.error(f"Unexpected error: {e!s}")
        raise HTTPException(status_code=500, detail=f"Server error: {e!s}")
