import os
from typing import Any, Dict, Optional

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from loguru import logger
from pydantic import BaseModel

load_dotenv(override=True)

app = FastAPI()


class RoomRequest(BaseModel):
    dialin_settings: Optional[Dict[str, Any]] = None
    dialout_settings: Optional[Dict[str, Any]] = None
    voicemail_detection: Optional[Dict[str, Any]] = None
    call_transfer: Optional[Dict[str, Any]] = None


"""
    body can contain any fields, but for handling PSTN/SIP, 
    we recommend sending the following custom values:
    dialin, dialout, voicemail detection, and call transfer
    
    "dialin_settings": {
        "to": "+14152251493",
        "from": "+14158483432",
        "callId": "djhdhdf",
        "callDomain": "djfhfhs"
    },
    "dialout_settings": [{
        "phoneNumber": "+14158483432",
        "callerId": "+14152251493"}, 
        {"sipURI": "fhdhdhd"}],
    "voicemail_detection": {
        "testInPrebuilt": true
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
async def dial(request: RoomRequest):
    daily_room_properties = {
        "enable_dialout": request.dialout_settings is not None,
    }

    if request.dialin_settings is not None:
        sip_config = {
            "display_name": "sip-dialin",
            "sip_mode": "dial-in",
            "num_endpoints": 2 if request.call_transfer else 1,
        }
        daily_room_properties["sip"] = sip_config

    payload = {
        "createDailyRoom": True,
        "body": {
            "dialin_settings": request.dialin_settings,
            "dialout_settings": request.dialout_settings,
            "voicemail_detection": request.voicemail_detection,
            "call_transfer": request.call_transfer,
        },
        "dailyRoomProperties": daily_room_properties,
    }

    daily_api_key = os.getenv("DAILY_API_KEY")
    agent_name = os.getenv("AGENT_NAME", "my-first-agent")

    logger.debug(f"Agent name: {agent_name}")
    logger.debug(f"Daily API Key: {daily_api_key}")

    if not daily_api_key:
        raise HTTPException(status_code=500, detail="DAILY_API_KEY environment variable is not set")

    headers = {"Authorization": f"Bearer {daily_api_key}", "Content-Type": "application/json"}

    url = f"https://api.pipecat.daily.co/v1/public/{agent_name}/start"

    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        logger.debug(f"Response: {response.json()}")
        return {"status": "success"}
    except requests.exceptions.HTTPError as e:
        # Pass through the status code and error details from the Daily API
        status_code = e.response.status_code
        error_detail = e.response.json() if e.response.content else str(e)
        logger.error(f"HTTP error: {error_detail}")
        raise HTTPException(status_code=status_code, detail=error_detail)
    except requests.exceptions.RequestException as e:
        logger.error(f"Request error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
