#
# Copyright (c) 2025, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

# server.py


import base64  # for calculating hmac signature
import hmac
import os  # for accessing environment variables
import time  # for setting expiration time
from typing import Any, Dict, List, Optional

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from loguru import logger
from pydantic import BaseModel, Field

load_dotenv(override=True)

app = FastAPI()


class RoomRequest(BaseModel):
    test: Optional[str] = Field(None, alias="Test", description="Test field")
    To: Optional[str] = Field(None, alias="to", description="Destination phone number")
    From: Optional[str] = Field(None, alias="from", description="Source phone number")
    callId: Optional[str] = Field(None, alias="call_id", description="Unique call identifier")
    callDomain: Optional[str] = Field(
        None, alias="call_domain", description="Call domain identifier"
    )
    dialout_settings: Optional[List[Dict[str, Any]]] = Field(
        None, description="An array of phone numbers or SIP URIs to dialout to"
    )
    voicemail_detection: Optional[Dict[str, Any]] = Field(
        None, description="A flag to perform voicemail or answeing-machine detection"
    )
    call_transfer: Optional[Dict[str, Any]] = Field(None, description="to initiate a call transfer")
    sipHeaders: Optional[Dict[str, Any]] = Field(
        None, alias="sip_headers", description="SIP headers to include in the call"
    )

    class Config:
        populate_by_name = True
        alias_generator = None


"""
    body can contain any fields, but for handling PSTN/SIP, 
    we recommend sending the following custom values:
    dialin, dialout, voicemail detection, and call transfer
    
    
    "To": "+14152251493",
    "From": "+14158483432",
    "callId": "string-contains-uuid",
    "callDomain": "string-contains-uuid"
    These need to be remapped to dialin_settings

    In addition, we may receive in the body that can be 
    sent to the bot as a custom field, sip_headers
    "sipHeaders": {
        "X-My-Custom-Header": "value",
        "x-caller": "+14158483432",
        "x-called": "+14152251493",
    },

    "dialout_settings": [
        {"phoneNumber": "+14158483432", "callerId": "uuid of +14152251493"}, 
        {"sipUri": "sip:username@sip.hostname"}
        ],
    },

    voicemail_detection:{
        testInPrebuilt: true
    },

    "call_transfer": {
        "mode": "dialout",
        "speakSummary": true,
        "storeSummary": true,
        "operatorNumber": "+14152250006",
        "testInPrebuilt": true
    }
"""


@app.get("/")
async def read_root():
    return {"message": "Hello, World!"}


@app.post("/api/dial")
async def dial(request: RoomRequest, raw_request: Request):
    start_time = time.time()

    logger.info("Incoming request to /dial:")
    logger.info(f"Headers: {dict(raw_request.headers)}")
    raw_body = await raw_request.body()
    raw_body_str = raw_body.decode()
    logger.info(f"Raw body: {raw_body_str}")
    logger.info(f"Parsed body: {request.dict()}")

    # calculate signature and compare/verify
    hmac_secret = os.getenv("PINLESS_HMAC_SECRET")
    timestamp = raw_request.headers.get("x-pinless-timestamp")
    signature = raw_request.headers.get("x-pinless-signature")

    if not hmac_secret:
        logger.debug("Skipping HMAC validation - PINLESS_HMAC_SECRET not set")
    elif timestamp and signature:
        message = timestamp + "." + raw_body_str

        base64_decoded_secret = base64.b64decode(hmac_secret)
        computed_signature = base64.b64encode(
            hmac.new(base64_decoded_secret, message.encode(), "sha256").digest()
        ).decode()

        if computed_signature != signature:
            logger.error(f"Invalid signature. Expected {signature}, got {computed_signature}")
            elapsed_time = time.time() - start_time
            logger.info(
                f"Request failed with 401 (Invalid signature) - Duration: {elapsed_time:.3f}s"
            )
            raise HTTPException(status_code=401, detail="Invalid signature")
    else:
        logger.debug("Skipping HMAC validation - no signature headers present")

    if request.test == "test":
        logger.debug("Test request received")
        elapsed_time = time.time() - start_time
        logger.info(f"Test request completed successfully - Duration: {elapsed_time:.3f}s")
        return {"status": "success", "message": "Test request received"}

    dialin_settings = None
    # these fields are camelCase in the request
    required_fields = ["To", "From", "callId", "callDomain"]
    if all(
        field in request.dict() and request.dict()[field] is not None for field in required_fields
    ):
        # transform from camelCase to snake_case because daily-python expects snake_case
        dialin_settings = {
            "From": request.From,
            "To": request.To,
            "call_id": request.callId,
            "call_domain": request.callDomain,
            # transform from camelCase to snake_case
        }
        logger.debug(f"Populated dialin_settings from request: {dialin_settings}")

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

    # Setting default expiry to 5 minutes from now
    daily_room_properties["exp"] = int(time.time()) + (5 * 60)

    logger.debug(f"Daily room properties: {daily_room_properties}")
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

    agent_name = os.getenv("AGENT_NAME", "my-first-agent")

    # Check if we're in local development mode
    if os.getenv("DAILY_ENV") == "local":
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
            room_response = requests.post(
                f"{daily_api_url}/v1/rooms",
                headers={
                    "Authorization": f"Bearer {daily_api_key}",
                    "Content-Type": "application/json",
                },
                json={"properties": daily_room_properties},
            )
            room_response.raise_for_status()
            room_data = room_response.json()
            room_url = room_data.get("url")
            room_name = room_data.get("name")

            # Create meeting token
            token_response = requests.post(
                f"{daily_api_url}/v1/meeting-tokens",
                headers={
                    "Authorization": f"Bearer {daily_api_key}",
                    "Content-Type": "application/json",
                },
                json={"properties": {"room_name": room_name, "is_owner": True}},
            )
            token_response.raise_for_status()
            token = token_response.json().get("token")

            # Add Daily API credentials to body (bot needs these for pinlessCallUpdate)
            payload["body"]["daily_api_key"] = daily_api_key
            payload["body"]["daily_api_url"] = daily_api_url

            # Call local bot /start endpoint
            # Include room_url/token in body as well for bots that use RunnerArguments
            local_body = payload["body"].copy()
            local_body["room_url"] = room_url
            local_body["token"] = token

            bot_response = requests.post(
                f"{local_server_url}/start",
                headers={"Content-Type": "application/json"},
                json={
                    "room_url": room_url,
                    "token": token,
                    "body": local_body,
                },
            )
            bot_response.raise_for_status()

            elapsed_time = time.time() - start_time
            logger.info(f"Local request completed successfully - Duration: {elapsed_time:.3f}s")

            return {
                "status": "success",
                "mode": "local",
                "room_url": room_url,
                "room_properties": daily_room_properties,
            }

        except requests.exceptions.RequestException as e:
            elapsed_time = time.time() - start_time
            logger.error(f"Local mode error: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

    elif os.getenv("DAILY_ENV") == "staging":
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
        raise HTTPException(status_code=500, detail="PIPECAT_CLOUD_API_KEY environment variable is not set")

    headers = {"Authorization": f"Bearer {pcc_api_key}", "Content-Type": "application/json"}

    logger.debug(f"Making API call to Pipecat Cloud: {url}")

    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        response_data = response.json()
        logger.debug(f"Response: {response_data}")
        elapsed_time = time.time() - start_time
        logger.info(f"Request completed successfully - Duration: {elapsed_time:.3f}s")
        return {
            "status": "success",
            "mode": "production",
            "data": response_data,
            "room_properties": daily_room_properties,
        }
    except requests.exceptions.HTTPError as e:
        # Pass through the status code and error details from the Daily API
        status_code = e.response.status_code
        error_detail = e.response.json() if e.response.content else str(e)
        elapsed_time = time.time() - start_time
        logger.error(f"HTTP error: {error_detail}")
        logger.info(
            f"Request failed with {status_code} (HTTP error from Pipecat Cloud) - Duration: {elapsed_time:.3f}s"
        )
        raise HTTPException(status_code=status_code, detail=error_detail)
    except requests.exceptions.RequestException as e:
        elapsed_time = time.time() - start_time
        logger.error(f"Request error: {str(e)}")
        logger.info(f"Request failed with 500 (Request exception) - Duration: {elapsed_time:.3f}s")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    try:
        import uvicorn

        port = int(os.getenv("PORT", "8080"))
        logger.info(f"Starting server on port {port}")
        uvicorn.run(app, host="0.0.0.0", port=port)
    except KeyboardInterrupt:
        logger.info("Server stopped manually")
