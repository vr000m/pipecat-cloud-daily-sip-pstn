#
# Copyright (c) 2024–2025, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

"""Twilio + Daily voice bot implementation."""

import os

from dotenv import load_dotenv
from loguru import logger
from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import LLMRunFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair
from pipecat.runner.types import RunnerArguments
from pipecat.services.cartesia.tts import CartesiaTTSService
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.transports.base_transport import BaseTransport
from pipecat.transports.daily.transport import DailyParams, DailyTransport
from twilio.rest import Client

from server_utils import AgentRequest

load_dotenv(override=True)


async def run_bot(transport: BaseTransport, request: AgentRequest, handle_sigint: bool) -> None:
    """Run the voice bot with the given parameters.

    Args:
        transport: The Daily transport instance
        request: The agent request containing the call details
        handle_sigint: Whether to handle SIGINT
    """
    stt = DeepgramSTTService(api_key=os.getenv("DEEPGRAM_API_KEY"))
    llm = OpenAILLMService(api_key=os.getenv("OPENAI_API_KEY"))
    tts = CartesiaTTSService(
        api_key=os.getenv("CARTESIA_API_KEY"),
        voice_id="71a7ad14-091c-4e8e-a314-022ece01c121",  # British Reading Lady
    )

    # Initialize LLM context with system prompt
    messages = [
        {
            "role": "system",
            "content": (
                "You are a friendly phone assistant. Your responses will be read aloud, "
                "so keep them concise and conversational. Avoid special characters or "
                "formatting. Begin by greeting the caller and asking how you can help them today."
            ),
        },
    ]

    # Setup the conversational context
    context = LLMContext(messages)
    context_aggregator = LLMContextAggregatorPair(context)

    # Build the pipeline
    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            context_aggregator.user(),
            llm,
            tts,
            transport.output(),
            context_aggregator.assistant(),
        ]
    )

    # Create the pipeline task
    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            enable_metrics=True,
            enable_usage_metrics=True,
            audio_in_sample_rate=8000,
            audio_out_sample_rate=8000,
        ),
    )

    # Handle call ready to forward
    @transport.event_handler("on_dialin_ready")
    async def on_dialin_ready(transport, sip_endpoint):
        logger.info(f"Forwarding call {request.call_sid} to {request.sip_uri}")

        try:
            # twilio_client = Client(os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN"))

            # Select Twilio credentials based on the dialed phone number
            # +1 numbers (US/Canada) use US credentials, others use EU credentials
            # TODO: send to_phone from server in AgentRequest

            if request.to_phone.startswith("+1"):
                account_sid = os.getenv("TWILIO_ACCOUNT_SID_US")
                auth_token = os.getenv("TWILIO_AUTH_TOKEN_US")
                twilio_region = "us1"
                logger.info(f"Using US Twilio credentials for {request.to_phone}")
            else:
                account_sid = os.getenv("TWILIO_ACCOUNT_SID_EU")
                auth_token = os.getenv("TWILIO_AUTH_TOKEN_EU")
                twilio_region = "ie1"
                logger.info(f"Using EU Twilio credentials for {request.to_phone}")
            # auth_token = os.getenv("TWILIO_AUTH_TOKEN")
            # twilio_region = "us1"
            logger.info(f"Using {twilio_region} Twilio credentials for {request}")

            twilio_client = Client(
                account_sid,
                auth_token,
                region=twilio_region,
            )

            # Update the Twilio call with TwiML to forward to the Daily SIP endpoint
            twilio_client.calls(request.call_sid).update(
                twiml=f'<Response><Dial><Sip>{request.sip_uri}?x-daily-fromName=Peter</Sip></Dial></Response>'
            )
            logger.info("Twilio forwarded successfully")
        except Exception as e:
            logger.error(f"Failed to forward call: {str(e)}")
            await task.cancel()

    @transport.event_handler("on_dialin_connected")
    async def on_dialin_connected(transport, data):
        logger.info(f"Dial-in connected: {data}")

    @transport.event_handler("on_dialin_error")
    async def on_dialin_error(transport, data):
        logger.error(f"Dial-in error: {data}")
        await task.cancel()

    @transport.event_handler("on_dialin_stopped")
    async def on_dialin_stopped(transport, data):
        logger.info(f"Dial-in stopped: {data}")

    @transport.event_handler("on_dialin_warning")
    async def on_dialin_warning(transport, data):
        logger.warning(f"Dial-in warning: {data}")

    # Dial-out: initiate call after bot joins the room
    @transport.event_handler("on_joined")
    async def on_joined(transport, data):
        if request.dialout_settings:
            logger.info(f"Bot joined, starting dialout to {request.dialout_settings.sip_uri}")
            dialout_params = {"sipUri": request.dialout_settings.sip_uri}
            if request.dialout_settings.provider:
                dialout_params["provider"] = request.dialout_settings.provider
            session_id, error = await transport.start_dialout(dialout_params)
            if error:
                logger.error(f"Dialout failed: {error}")
                await task.cancel()
            else:
                logger.info(f"Dialout started, session_id: {session_id}")

    @transport.event_handler("on_dialout_answered")
    async def on_dialout_answered(transport, data):
        logger.info(f"Dialout answered: {data}")
        await task.queue_frame(LLMRunFrame())

    @transport.event_handler("on_dialout_connected")
    async def on_dialout_connected(transport, data):
        logger.info(f"Dialout connected: {data}")

    @transport.event_handler("on_dialout_stopped")
    async def on_dialout_stopped(transport, data):
        logger.info(f"Dialout stopped: {data}")

    @transport.event_handler("on_dialout_error")
    async def on_dialout_error(transport, data):
        logger.error(f"Dialout error: {data}")
        await task.cancel()

    @transport.event_handler("on_dialout_warning")
    async def on_dialout_warning(transport, data):
        logger.warning(f"Dialout warning: {data}")

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        logger.info("Client connected")
        # Only auto-start LLM for dial-in (dialout waits for on_dialout_answered)
        if not request.dialout_settings:
            await task.queue_frame(LLMRunFrame())

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        logger.info("Client disconnected")
        await task.cancel()

    runner = PipelineRunner(handle_sigint=handle_sigint)

    await runner.run(task)


async def bot(runner_args: RunnerArguments):
    """Main bot entry point."""
    try:
        request = AgentRequest.model_validate(runner_args.body)

        transport = DailyTransport(
            request.room_url,
            request.token,
            "SIP Dial-in Bot",
            params=DailyParams(
                audio_in_enabled=True,
                audio_out_enabled=True,
                vad_analyzer=SileroVADAnalyzer(params=VADParams(stop_secs=0.2)),
                turn_analyzer=LocalSmartTurnAnalyzerV3(),
            ),
        )
        # print (f"Starting bot for call SID: {request}")

        await run_bot(transport, request, runner_args.handle_sigint)
    except Exception as e:
        logger.error(f"Invalid request: {e}")
        return


if __name__ == "__main__":
    from pipecat.runner.run import main

    main()
