#
# Copyright (c) 2025, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

"""Pydantic models for webhook request/response handling."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# =============================================================================
# Daily Webhook Models (for /api/dial endpoint)
# =============================================================================


class DailyDialRequest(BaseModel):
    """Request model for Daily pinless dial-in webhook.

    Handles both dial-in (incoming calls) and dial-out (outgoing calls) scenarios.
    Field names support both camelCase (from Daily) and snake_case.
    """

    test: Optional[str] = Field(None, alias="Test", description="Test field")
    To: Optional[str] = Field(None, alias="to", description="Destination phone number")
    From: Optional[str] = Field(None, alias="from", description="Source phone number")
    callId: Optional[str] = Field(None, alias="call_id", description="Unique call identifier")
    callDomain: Optional[str] = Field(
        None, alias="call_domain", description="Call domain identifier"
    )
    dialout_settings: Optional[List[Dict[str, Any]]] = Field(
        None, description="Array of phone numbers or SIP URIs for dial-out"
    )
    voicemail_detection: Optional[Dict[str, Any]] = Field(
        None, description="Voicemail/answering-machine detection settings"
    )
    call_transfer: Optional[Dict[str, Any]] = Field(
        None, description="Call transfer configuration"
    )
    sipHeaders: Optional[Dict[str, Any]] = Field(
        None, alias="sip_headers", description="Custom SIP headers"
    )

    class Config:
        populate_by_name = True


# =============================================================================
# Twilio Webhook Models (for /api/twilio/call endpoint)
# =============================================================================


class TwilioCallData(BaseModel):
    """Data extracted from Twilio call webhook.

    Twilio sends form-encoded data, which is parsed into this model.
    """

    call_sid: str = Field(..., description="Unique identifier for the Twilio call")
    from_phone: str = Field(..., description="Caller's phone number")
    to_phone: str = Field(..., description="Dialed phone number")


class AgentRequest(BaseModel):
    """Request data sent to bot start endpoint (local or Pipecat Cloud).

    Used for Twilio flow where room is created first, then bot is started.
    """

    room_url: str = Field(..., description="Daily room URL for the bot to join")
    token: str = Field(..., description="Authentication token for the Daily room")
    call_sid: str = Field(..., description="Twilio call identifier")
    sip_uri: str = Field(..., description="SIP URI for call forwarding")
