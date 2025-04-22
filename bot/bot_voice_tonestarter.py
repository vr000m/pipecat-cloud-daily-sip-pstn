#
# Copyright (c) 2025, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

import os
import re
import sys
import tempfile
from pathlib import Path

import numpy as np
from dotenv import load_dotenv
from loguru import logger
from openai.types.chat import ChatCompletionToolParam
from pipecat.audio.mixers.soundfile_mixer import SoundfileMixer
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import (
    EndTaskFrame,
    Frame,
    MixerEnableFrame,
    UserStartedSpeakingFrame,
)
from pipecat.observers.base_observer import BaseObserver
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.processors.frameworks.rtvi import RTVIConfig, RTVIObserver, RTVIProcessor
from pipecat.services.cartesia.tts import CartesiaTTSService
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.llm_service import LLMService
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.transports.services.daily import DailyParams, DailyTransport
from pipecatcloud.agent import DailySessionArguments

load_dotenv(override=True)
logger.remove()
logger.add(sys.stderr, level="DEBUG")


# Function to generate a sine wave tone and save it to a temporary file
def generate_tone_file(freq=400, duration=5.0, sample_rate=8000):
    """Generate a sine wave tone file with the specified parameters."""
    # Generate time array
    t = np.linspace(0, duration, int(sample_rate * duration), False)

    # Generate sine wave
    tone = 0.5 * np.sin(2 * np.pi * freq * t)

    # Convert to 16-bit PCM
    tone = (tone * 32767).astype(np.int16)

    # Create a temporary file to store the tone
    temp_dir = tempfile.gettempdir()
    tone_file = os.path.join(temp_dir, f"tone_{freq}hz.wav")

    # Use soundfile to write the tone to the file
    import soundfile as sf

    sf.write(tone_file, tone, sample_rate, format="WAV")
    logger.info(f"Generated tone file at: {tone_file}")

    return tone_file


# Add environment variable validation
def validate_env_vars():
    required_vars = ["DAILY_API_KEY", "DEEPGRAM_API_KEY", "OPENAI_API_KEY", "CARTESIA_API_KEY"]
    missing = [var for var in required_vars if not os.getenv(var)]
    if missing:
        raise ValueError(f"Missing required environment variables: {', '.join(missing)}")


# Voice Observer to detect speech and stop tones
class VoiceActivityObserver(BaseObserver):
    """Observer that detects user speech and manages the tone playback."""

    def __init__(self):
        # Call the parent class constructor correctly without arguments
        super().__init__()
        self.task = None
        self.context_aggregator = None
        self.tone_enabled = False
        self.conversation_started = False

    async def on_push_frame(
        self,
        src: FrameProcessor,
        dst: FrameProcessor,
        frame: Frame,
        direction: FrameDirection,
        timestamp: int,
    ):
        if not self.task or not self.context_aggregator:
            return

        # Handle user started speaking
        if isinstance(frame, UserStartedSpeakingFrame) and not frame.emulated:
            if self.tone_enabled and not self.conversation_started:
                logger.info("User started speaking, disabling tone and starting conversation")
                # Disable the tone
                await self.task.queue_frame(MixerEnableFrame(False))
                self.tone_enabled = False

                # Start the conversation if it hasn't started yet
                if not self.conversation_started:
                    await self.task.queue_frames(
                        [self.context_aggregator.user().get_context_frame()]
                    )
                    self.conversation_started = True


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


caller_name = "Tess from Daily"
system_prompt = """
You are {caller_name}, a friendly, helpful robot. Your goal is to demonstrate your capabilities in a succinct way. Your output will be converted to audio so don't include special characters in your answers. Respond to what the user said in a creative and helpful way, but keep your responses brief. Start by introducing yourself.

- If the user no longer needs assistance, then call `terminate_call` immediately.
"""

dialled_name = ""
caller_phonenum = "+16504771871"


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

    def __init__(self, transport, task, context_aggregator, voice_observer):
        """Initialize the DialInHandler.

        Args:
            transport: The Daily transport instance
            task: The PipelineTask instance
            context_aggregator: The context aggregator for the LLM
            voice_observer: The voice activity observer
        """
        self.transport = transport
        self.task = task
        self.context_aggregator = context_aggregator
        self.voice_observer = voice_observer
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
            logger.debug(f"Dial-in connected: {data}")
            logger.info(f"Dial-in session ID: {session_id}")

            # Enable the tone when the call connects
            await self.task.queue_frame(MixerEnableFrame(True))
            self.voice_observer.tone_enabled = True

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


class DialOutHandler:
    """Handles a single dial-out call and it is also managing retry attempts.
    In addition handling all dial-out related events from the Daily platform."""

    def __init__(self, transport, task, dialout_setting, voice_observer, max_attempts=5):
        """Initialize the DialOutHandler for a single call.

        Args:
            transport: The Daily transport instance
            task: The PipelineTask instance
            dialout_setting: Configuration for this specific outbound call
            voice_observer: The voice activity observer
            max_attempts: Maximum number of dial-out attempts on a specific number
        """
        self.transport = transport
        self.task = task
        self.dialout_setting = dialout_setting
        self.voice_observer = voice_observer
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

            # Enable the tone when the call is answered
            await self.task.queue_frame(MixerEnableFrame(True))
            self.voice_observer.tone_enabled = True

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


class DebugObserver(BaseObserver):
    """Observer to log interruptions and bot speaking events to the console."""

    # Fixed initialization
    def __init__(self):
        super().__init__()

    async def on_push_frame(
        self,
        src: FrameProcessor,
        dst: FrameProcessor,
        frame: Frame,
        direction: FrameDirection,
        timestamp: int,
    ):
        # Convert timestamp to seconds for readability
        time_sec = timestamp / 1_000_000_000

        # Create direction arrow
        arrow = "→" if direction == FrameDirection.DOWNSTREAM else "←"

        if isinstance(frame, UserStartedSpeakingFrame):
            logger.info(f"👤 USER START SPEAKING: {src} {arrow} {dst} at {time_sec:.2f}s")


async def main(room_url: str, token: str, body: dict):
    logger.debug("Starting bot in room: {}", room_url)

    # Validate environment variables
    validate_env_vars()

    # Configure tone parameters
    tone_freq = 400  # Hz
    tone_duration = 5.0  # seconds
    sample_rate = 8000  # match with pipeline params

    # Generate tone file
    tone_file = generate_tone_file(tone_freq, tone_duration, sample_rate)

    # Create sound mixer with the generated tone
    soundfile_mixer = SoundfileMixer(
        sound_files={"tone": tone_file},
        default_sound="tone",
        volume=0.8,
        mixing=False,  # Start with mixing disabled
        loop=True,  # Loop the tone
    )

    # Dial-in configuration:
    # dialin_settings are received when a call is triggered to
    # Daily via pinless_dialin. This can be a phone number on Daily or a
    # sip interconnect from Twilio or Telnyx.
    dialin_settings = None
    dialled_phonenum = None
    caller_phonenum = None
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
    daily_api_key = os.getenv("DAILY_API_KEY")
    logger.info(f"DAILY API Key: {daily_api_key}")
    daily_api_url = os.getenv("DAILY_URL") or "https://api.daily.co/v1"
    logger.info(f"Daily backend url: {daily_api_url}")

    transport = DailyTransport(
        room_url,
        token,
        "Voice AI Bot",
        DailyParams(
            api_url=daily_api_url,
            api_key=daily_api_key,  # needed for dial-in
            audio_out_mixer=soundfile_mixer,
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

    # This sets up the LLM context by providing messages and tools
    context = OpenAILLMContext(messages, tools)
    context_aggregator = llm.create_context_aggregator(context)

    # RTVI events for Pipecat client UI
    rtvi = RTVIProcessor(config=RTVIConfig(config=[]))

    # Create our voice activity observer - Fix initialization
    voice_observer = VoiceActivityObserver()

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
            audio_in_sample_rate=sample_rate,
            audio_out_sample_rate=sample_rate,
            enable_metrics=True,
            enable_usage_metrics=True,
        ),
        observers=[RTVIObserver(rtvi), voice_observer, DebugObserver()],
    )

    # Set the task and context aggregator in the voice observer
    voice_observer.task = task
    voice_observer.context_aggregator = context_aggregator

    # Initialize handlers dict to keep references
    handlers = {}

    # Initialize appropriate handlers based on the call type
    if dialin_settings:
        handlers["dialin"] = DialInHandler(transport, task, context_aggregator, voice_observer)

    if dialout_settings:
        # Create a handler for each dial-out setting
        # i.e., each phone number/sip address gets its own handler
        # allows more control on retries and state management
        handlers["dialout"] = [
            DialOutHandler(transport, task, setting, voice_observer) for setting in dialout_settings
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
