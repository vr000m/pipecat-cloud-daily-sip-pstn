#
# Copyright (c) 2025, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

import os
import re
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger
from openai.types.chat import ChatCompletionToolParam
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import (
    EndTaskFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext
from pipecat.processors.frame_processor import FrameDirection
from pipecat.processors.frameworks.rtvi import RTVIConfig, RTVIObserver, RTVIProcessor
from pipecat.services.cartesia.tts import CartesiaTTSService
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.llm_service import LLMService
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.transports.services.daily import DailyParams, DailyTransport
from pipecatcloud.agent import DailySessionArguments

now = datetime.now()
weekday = now.strftime("%A")  # e.g., "Friday"
formatted_time = now.strftime("%A, %B %d, %Y at %I:%M %p")
hour = now.hour

load_dotenv(override=True)
logger.remove()
logger.add(sys.stderr, level="DEBUG")


# Add environment variable validation
def validate_env_vars():
    required_vars = ["DAILY_API_KEY", "DEEPGRAM_API_KEY", "OPENAI_API_KEY", "CARTESIA_API_KEY"]
    missing = [var for var in required_vars if not os.getenv(var)]
    if missing:
        raise ValueError(f"Missing required environment variables: {', '.join(missing)}")


dialled_name = ""
caller_phonenum = "+16504771871"


def load_prompt(template_path: str, **kwargs) -> str:
    """Load a prompt template and replace placeholders with values."""
    prompt_path = Path(__file__).parent / "prompts" / template_path
    with open(prompt_path) as f:
        template = f.read()

    # Find all unique placeholders in the template
    placeholders = set(re.findall(r"\{(\w+)\}", template))

    # Check if all placeholders have corresponding values
    missing = placeholders - set(kwargs.keys())
    if missing:
        raise ValueError(f"Missing values for placeholders: {missing}")

    # Replace all {variable_name} with their values
    for key, value in kwargs.items():
        template = re.sub(r"\{" + key + r"\}", str(value), template)

    return template.strip()


def get_time_of_day(hour):
    if 5 <= hour < 12:
        return "morning"
    elif 12 <= hour < 17:
        return "afternoon"
    elif 17 <= hour < 21:
        return "evening"
    else:
        return "night"


def get_day_style(weekday, date):
    if weekday in ["Friday", "Saturday", "Sunday"]:
        return "long weekend"
    elif weekday in ["Monday", "Tuesday"]:
        return "quick start"
    else:
        return "midweek"


# Time-aware storytelling tone
time_of_day = get_time_of_day(hour)
day_style = get_day_style(weekday, now)

# Tone mapping based on time of day and day style
# This is used to set the mood of the story
tone_intro = {
    "morning": "a fresh start to your day",
    "afternoon": "a colorful moment to drift into imagination",
    "evening": "a gentle escape as the day winds down",
    "night": "a cozy tale to end the night",
}

story_type = {
    "long weekend": "a whimsical adventure with time to explore",
    "quick start": "a fast-paced story to energize your Monday",
    "midweek": "a small journey to spark midweek joy",
}

caller_name = "Kai from Daily"
system_prompt = f"""
You are {caller_name}, a curious and friendly storyteller. Greet the caller warmly using {time_of_day} and introduce yourself as {caller_name}. 
Let them know that together, you're going to create a short story—something magical, surprising, or soothing, depending on the mood of the day.

Today is {formatted_time}, a {time_of_day} that's perfect for {tone_intro[time_of_day]}. 
It's also part of a {story_type[day_style]}.

Your job is to guide the caller into the story with a short vivid introduction and then ask what happens next. 
Let the caller shape the journey, while you add delightful twists or imagery in a few sentences at a time.

This conversation will be spoken aloud, so use clear and simple language. Avoid symbols or anything hard to pronounce.

- If the caller says they’re done or no longer wants to continue, call `terminate_call` right away.
- Always end your responses with a question, choice, or invitation to continue the story.
"""


# Function call for the bot to terminate the call.
# Needed in the case of dial-in and dial-out for the bot to hang up
async def terminate_call(
    function_name, tool_call_id, args, llm: LLMService, context, result_callback
):
    """Function the bot can call to terminate the call; e.g. upon completion of a voicemail message."""
    await llm.queue_frame(EndTaskFrame(), FrameDirection.UPSTREAM)
    await result_callback("""Say: 'Okay, thank you! Have a great day!'""")


class DialInHandler:
    """Handles all dial-in related functionality and event handling.

    This class encapsulates the logic for incoming calls and handling
    all dial-in related events from the Daily platform.
    """

    def __init__(self, transport, task, context_aggregator):
        """Initialize the DialInHandler.

        Args:
            transport: The Daily transport instance
            task: The PipelineTask instance
            context_aggregator: The context aggregator for the LLM
        """
        self.transport = transport
        self.task = task
        self.context_aggregator = context_aggregator
        self._register_handlers()

    def _register_handlers(self):
        """Register all event handlers related to dial-in functionality."""

        @self.transport.event_handler("on_dialin_ready")
        async def on_dialin_ready(transport, data):
            """Handler for when the dial-in is ready (SIP addresses registered with the SIP network)."""
            # For Twilio, Telnyx, etc. You need to update the state of the call
            # and forward it to the sip_uri.
            logger.debug(f"Dial-in ready: {data}")

        @self.transport.event_handler("on_dialin_connected")
        async def on_dialin_connected(transport, data):
            """Handler for when a dial-in call is connected."""
            session_id = data.get("sessionId")
            logger.debug(f"Dial-in connected: {data} and set_bot_ready")
            logger.info(f"Dial-in session ID: {session_id}")

        @self.transport.event_handler("on_dialin_stopped")
        async def on_dialin_stopped(transport, data):
            """Handler for when a dial-in call is stopped."""
            logger.debug(f"Dial-in stopped: {data}")

        @self.transport.event_handler("on_dialin_error")
        async def on_dialin_error(transport, data):
            """Handler for dial-in errors."""
            logger.error(f"Dial-in error: {data}")
            # The bot should leave the call if there is an error
            await self.task.cancel()

        @self.transport.event_handler("on_dialin_warning")
        async def on_dialin_warning(transport, data):
            """Handler for dial-in warnings."""
            logger.warning(f"Dial-in warning: {data}")

        @self.transport.event_handler("on_first_participant_joined")
        async def on_first_participant_joined(transport, participant):
            """Handler for when the first participant joins the call."""
            logger.info("First participant joined: {}", participant["id"])
            # Capture the participant's transcription
            await transport.capture_participant_transcription(participant["id"])

            # For the dial-in case, we want the bot to greet the user.
            # We can prompt the bot to speak by putting the context into the pipeline.
            await self.task.queue_frames([self.context_aggregator.user().get_context_frame()])


class DialOutHandler:
    """Handles a single dial-out call and it is also managing retry attempts.
    In addition handling all dial-out related events from the Daily platform."""

    def __init__(self, transport, task, dialout_setting, max_attempts=5):
        """Initialize the DialOutHandler for a single call.

        Args:
            transport: The Daily transport instance
            task: The PipelineTask instance
            dialout_setting: Configuration for this specific outbound call
            max_attempts: Maximum number of dial-out attempts on a specific number
        """
        self.transport = transport
        self.task = task
        self.dialout_setting = dialout_setting
        self.max_attempts = max_attempts
        self.attempt_count = 0
        self.status = "pending"  # pending, connected, answered, failed, stopped
        self._register_handlers()
        logger.info(f"Initialized DialOutHandler for call: {dialout_setting}")

    async def start(self):
        """Initiates an outbound call using the configured dial-out settings."""
        self.attempt_count += 1

        if self.attempt_count > self.max_attempts:
            logger.error(
                f"Max dialout attempts ({self.max_attempts}) reached for {self.dialout_setting}"
            )
            self.status = "failed"
            return

        logger.debug(
            f"Dialout attempt {self.attempt_count}/{self.max_attempts} for {self.dialout_setting}"
        )

        try:
            if "phoneNumber" in self.dialout_setting:
                logger.info(f"Dialing number: {self.dialout_setting['phoneNumber']}")
                if "callerId" in self.dialout_setting:
                    await self.transport.start_dialout(
                        {
                            "phoneNumber": self.dialout_setting["phoneNumber"],
                            "callerId": self.dialout_setting["callerId"],
                        }
                    )
                else:
                    await self.transport.start_dialout(
                        {"phoneNumber": self.dialout_setting["phoneNumber"]}
                    )
            elif "sipUri" in self.dialout_setting:
                logger.info(f"Dialing sipUri: {self.dialout_setting['sipUri']}")
                await self.transport.start_dialout({"sipUri": self.dialout_setting["sipUri"]})
        except Exception as e:
            logger.error(f"Error starting dialout: {e}")
            self.status = "failed"

    def _register_handlers(self):
        """Register all event handlers related to the dial-out functionality."""

        @self.transport.event_handler("on_dialout_connected")
        async def on_dialout_connected(transport, data):
            """Handler for when a dial-out call is connected (starts ringing)."""
            self.status = "connected"
            logger.debug(f"Dial-out connected: {data}")

        @self.transport.event_handler("on_dialout_answered")
        async def on_dialout_answered(transport, data):
            """Handler for when a dial-out call is answered (off hook). We capture the transcription, but we do not
            queue up a context frame, because we are waiting for the user to speak first."""
            self.status = "answered"
            session_id = data.get("sessionId")
            await transport.capture_participant_transcription(session_id)
            logger.debug(f"Dial-out answered: {data}")
            logger.info(f"Dial-out session ID: {session_id}")

        @self.transport.event_handler("on_dialout_stopped")
        async def on_dialout_stopped(transport, data):
            """Handler for when a dial-out call is stopped."""
            self.status = "stopped"
            logger.debug(f"Dial-out stopped: {data}")

        @self.transport.event_handler("on_dialout_error")
        async def on_dialout_error(transport, data):
            """Handler for dial-out errors. Will retry this specific call."""
            self.status = "failed"
            await self.start()  # Retry could cause infinite loop if error persists
            logger.error(f"Dial-out error: {data}, retrying...")

        @self.transport.event_handler("on_dialout_warning")
        async def on_dialout_warning(transport, data):
            """Handler for dial-out warnings."""
            logger.warning(f"Dial-out warning: {data}")


async def main(room_url: str, token: str, body: dict):
    logger.debug("Starting bot in room: {}", room_url)

    # Validate environment variables
    validate_env_vars()

    # Dial-in configuration:
    # dialin_settings are received when a call is triggered to
    # Daily via pinless_dialin. This can be a phone number on Daily or a
    # sip interconnect from Twilio or Telnyx.
    dialin_settings = None
    dialled_phonenum = None
    if raw_dialin_settings := body.get("dialin_settings"):
        # these fields can capitalize the first letter
        dialled_phonenum = raw_dialin_settings.get("To") or raw_dialin_settings.get("to")
        caller_phonenum = raw_dialin_settings.get("From") or raw_dialin_settings.get("from")
        dialin_settings = {
            # these fields can be received as snake_case or camelCase.
            "call_id": raw_dialin_settings.get("callId") or raw_dialin_settings.get("call_id"),
            "call_domain": raw_dialin_settings.get("callDomain")
            or raw_dialin_settings.get("call_domain"),
        }
        logger.debug(
            f"Dialin settings: To: {dialled_phonenum}, From: {caller_phonenum}, dialin_settings: {dialin_settings}"
        )

    # Dial-out configuration
    dialout_settings = body.get("dialout_settings")
    logger.debug(f"Dialout settings: {dialout_settings}")

    # Voicemail detection configuration
    voicemail_detection = body.get("voicemail_detection")
    using_voicemail_detection = bool(voicemail_detection and dialout_settings)

    logger.debug(f"Using voicemail detection: {using_voicemail_detection}")

    transport = DailyTransport(
        room_url,
        token,
        "Voice AI Bot",
        DailyParams(
            api_key=os.getenv("DAILY_API_KEY"),  # needed for dial-in
            dialin_settings=dialin_settings,
            audio_out_enabled=True,
            vad_enabled=True,
            vad_analyzer=SileroVADAnalyzer(),
            vad_audio_passthrough=True,
        ),
    )

    # Configure your STT, LLM, and TTS services here
    # Swap out different processors or properties to customize your bot
    stt = DeepgramSTTService(api_key=os.getenv("DEEPGRAM_API_KEY"))
    llm = OpenAILLMService(api_key=os.getenv("OPENAI_API_KEY"), model="gpt-4o")
    tts = CartesiaTTSService(
        api_key=os.getenv("CARTESIA_API_KEY"),
        voice_id="71a7ad14-091c-4e8e-a314-022ece01c121",
    )

    # Format phone number for better TTS pronunciation
    if caller_phonenum:
        # Remove any non-digit characters
        cleaned = "".join(filter(str.isdigit, caller_phonenum))
        # Format as +1 (XXX) XXX XXXX
        if len(cleaned) == 11 and cleaned.startswith("1"):
            caller_phonenum = f"+1 ({cleaned[1:4]}) {cleaned[4:7]} {cleaned[7:]}"
        elif len(cleaned) == 10:
            caller_phonenum = f"+1 ({cleaned[0:3]}) {cleaned[3:6]} {cleaned[6:]}"

    # Set up the initial context for the conversation
    # You can specified initial system and assistant messages here
    # or register tools for the LLM to use
    if using_voicemail_detection:
        # If voicemail detection is enabled, we need to set up the context
        # to handle voicemail messages

        # You may have to do a lookup unless you pass this info into dialout_settings
        vm_prompt = load_prompt(
            "voicemail_prompt.txt",
            caller_name=caller_name,
            dialled_name=dialled_name,
            caller_phonenum=caller_phonenum,
        )

        messages = [
            {
                "role": "system",
                "content": vm_prompt,
            }
        ]
    else:
        messages = [
            {
                "role": "system",
                "content": system_prompt.strip(),
            },
        ]

    # Registering the terminate_call function as a tool
    # This is used to terminate the call when the bot is done
    llm.register_function("terminate_call", terminate_call)
    tools = [
        ChatCompletionToolParam(
            type="function",
            function={
                "name": "terminate_call",
                "description": "Terminate the call",
            },
        )
    ]
    # tools = NotGiven()

    # This sets up the LLM context by providing messages and tools
    context = OpenAILLMContext(messages, tools)
    context_aggregator = llm.create_context_aggregator(context)

    # RTVI events for Pipecat client UI
    rtvi = RTVIProcessor(config=RTVIConfig(config=[]))

    # A core voice AI pipeline
    # Add additional processors to customize the bot's behavior
    pipeline = Pipeline(
        [
            transport.input(),
            rtvi,
            stt,
            context_aggregator.user(),
            llm,
            tts,
            transport.output(),
            context_aggregator.assistant(),
        ]
    )

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            allow_interruptions=True,
            audio_in_sample_rate=8000,
            audio_out_sample_rate=8000,
            enable_metrics=True,
            enable_usage_metrics=True,
        ),
        observers=[RTVIObserver(rtvi)],
    )

    # Initialize handlers dict to keep references
    handlers = {}

    # Initialize appropriate handlers based on the call type
    if dialin_settings:
        handlers["dialin"] = DialInHandler(transport, task, context_aggregator)

    if dialout_settings:
        # Create a handler for each dial-out setting
        # i.e., each phone number/sip address gets its own handler
        # allows more control on retries and state management
        handlers["dialout"] = [
            DialOutHandler(transport, task, setting) for setting in dialout_settings
        ]

    # Set up general event handlers
    @transport.event_handler("on_call_state_updated")
    async def on_call_state_updated(transport, state):
        logger.info(f"on_call_state_updated, state: {state}")
        if state == "joined" and dialout_settings:
            # Start all dial-out calls once we're joined to the room
            if "dialout" in handlers:
                for handler in handlers["dialout"]:
                    await handler.start()
        if state == "left":
            await task.cancel()

    @transport.event_handler("on_joined")
    async def on_joined(transport, data):
        session_id = data["meetingSession"]["id"]
        bot_id = data["participants"]["local"]["id"]
        logger.info(f"Session ID: {session_id}, Bot ID: {bot_id}")

    @transport.event_handler("on_participant_left")
    async def on_participant_left(transport, participant, reason):
        logger.debug(f"Participant left: {participant}, reason: {reason}")
        await task.cancel()

    runner = PipelineRunner(handle_sigint=False, force_gc=True)
    await runner.run(task)


async def bot(args: DailySessionArguments):
    """Main bot entry point compatible with the FastAPI route handler.

    Args:
        room_url: The Daily room URL
        token: The Daily room token
        body: The configuration object from the request body can contain dialin_settings, dialout_settings, voicemail_detection, and call_transfer
        session_id: The session ID for logging
    """
    logger.info(f"Bot process initialized {args.room_url} {args.token}")

    try:
        await main(args.room_url, args.token, args.body)
        logger.info("Bot process completed")
    except Exception as e:
        logger.exception(f"Error in bot process: {str(e)}")
        raise
