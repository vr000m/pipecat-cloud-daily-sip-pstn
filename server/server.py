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
from typing import Any, Dict, Optional

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
    dialout_settings: Optional[Dict[str, Any]] = Field(
        None, description="An array of phone numbers to dialout to"
    )
    voicemail_detection: Optional[Dict[str, Any]] = Field(
        None, description="A flag to perform voicemail detection"
    )
    call_transfer: Optional[Dict[str, Any]] = Field(None, description="to initiate a call transfer")

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

    "dialout_settings": [
        {"phoneNumber": "+14158483432", "callerId": "+14152251493"}, 
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


@app.post("/dial")
async def dial(raw_request: Request):
    logger.info("Incoming request to /dial:")
    raw_body = await raw_request.body()
    raw_body_str = raw_body.decode()
    logger.debug(f"Headers: {dict(raw_request.headers)}")
    request_data = await raw_request.json()
    logger.debug(f"Body: {request_data}")

    # calculate signature and compare/verify
    hmac_secret = os.getenv("PINLESS_HMAC_SECRET")
    timestamp = raw_request.headers.get("x-pinless-timestamp")

    if timestamp:
        signature = timestamp + "." + raw_body_str
        logger.debug(f"Signature: {signature}")

        base64_decoded_secret = base64.b64decode(hmac_secret)
        computed_signature = base64.b64encode(
            hmac.new(base64_decoded_secret, signature.encode(), "sha256").digest()
        ).decode()

        if computed_signature != raw_request.headers.get("x-pinless-signature"):
            logger.error("Invalid signature")
            raise HTTPException(status_code=401, detail="Invalid signature")

    if request_data.get("test") == "test":
        logger.debug("Test request received")
        return {"status": "success", "message": "Test request received"}

    # Parse raw body and check for dialin properties
    dialin_settings = None
    # these fields are camelCase in the request
    required_fields = ["To", "From", "callId", "callDomain"]
    if all(field in request_data for field in required_fields):
        # transform from camelCase to snake_case because daily-python expects snake_case
        dialin_settings = {
            "from": request_data["From"],
            "to": request_data["To"],
            "call_id": request_data["callId"],
            "call_domain": request_data["callDomain"],
            # transform from camelCase to snake_case
        }
        logger.debug(f"Populated dialin_settings from request: {dialin_settings}")

    daily_room_properties = {
        "enable_dialout": "dialout_settings" in request_data,
    }

    if dialin_settings is not None:
        sip_config = {
            "display_name": "sip-dialin",
            "sip_mode": "dial-in",
            "num_endpoints": 2 if "call_transfer" in request_data else 1,
        }
        daily_room_properties["sip"] = sip_config
        daily_room_properties["exp"] = int(time.time()) + (5 * 60)

    logger.debug(f"Daily room properties: {daily_room_properties}")
    payload = {
        "createDailyRoom": True,
        "dailyRoomProperties": daily_room_properties,
        "body": {
            "dialin_settings": dialin_settings,
            "dialout_settings": request_data.get("dialout_settings"),
            "voicemail_detection": request_data.get("voicemail_detection"),
            "call_transfer": request_data.get("call_transfer"),
        },
    }

    daily_api_key = os.getenv("DAILY_API_KEY")
    agent_name = os.getenv("AGENT_NAME", "my-first-agent")

    logger.debug(f"Agent name: {agent_name}")
    logger.debug(f"Daily API Key: {daily_api_key}")

    if not daily_api_key:
        raise HTTPException(status_code=500, detail="DAILY_API_KEY environment variable is not set")

    headers = {"Authorization": f"Bearer {daily_api_key}", "Content-Type": "application/json"}

    url = f"https://api.pipecat.daily.co/v1/public/{agent_name}/start"

    Makecall = True
    if Makecall:
        try:
            response = requests.post(url, json=payload, headers=headers)
            response.raise_for_status()
            response_data = response.json()
            logger.debug(f"Response: {response_data}")
            return {
                "status": "success",
                "data": response_data,
                "room_properties": daily_room_properties,
            }
        except requests.exceptions.HTTPError as e:
            # Pass through the status code and error details from the Daily API
            status_code = e.response.status_code
            error_detail = e.response.json() if e.response.content else str(e)
            logger.error(f"HTTP error: {error_detail}")
            raise HTTPException(status_code=status_code, detail=error_detail)
        except requests.exceptions.RequestException as e:
            logger.error(f"Request error: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))
    else:
        logger.debug(f"Skipping API call to Daily: {url}")
        return {
            "status": "success",
            "data": payload,
            "room_properties": daily_room_properties,
        }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
