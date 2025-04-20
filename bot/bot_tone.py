#
# Copyright (c) 2025, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

import asyncio
import os
import sys
import time

import numpy as np
from dotenv import load_dotenv
from loguru import logger
from openai._types import NotGiven
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import (
    Frame,
    OutputAudioRawFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

# from pipecat.services.cartesia.tts import CartesiaTTSService
# from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.transports.services.daily import DailyParams, DailyTransport
from pipecatcloud.agent import DailySessionArguments

load_dotenv(override=True)
logger.remove()
logger.add(sys.stderr, level="DEBUG")

AUDIO_SAMPLE_RATE = 8000


# Add environment variable validation
def validate_env_vars():
    required_vars = ["DAILY_API_KEY", "DEEPGRAM_API_KEY", "OPENAI_API_KEY", "CARTESIA_API_KEY"]
    missing = [var for var in required_vars if not os.getenv(var)]
    if missing:
        raise ValueError(f"Missing required environment variables: {', '.join(missing)}")


def generate_tone_data(freq=400, duration=5.0, sample_rate=8000):
    """Generate a sine wave tone with the specified parameters.

    Args:
        freq: Frequency of the tone in Hz
        duration: Duration of the tone in seconds
        sample_rate: Sample rate in Hz

    Returns:
        A NumPy array containing the audio data as int16
    """
    # Generate time array
    t = np.linspace(0, duration, int(sample_rate * duration), False)

    # Generate sine wave
    tone = 0.5 * np.sin(2 * np.pi * freq * t)

    # Convert to 16-bit PCM
    tone_data = (tone * 32767).astype(np.int16)

    logger.info(f"Generated tone data: {len(tone_data) / sample_rate:.1f}s at {freq}Hz")

    return tone_data


class SimpleAudioFrameInserter(FrameProcessor):
    """A frame processor that inserts audio frames into the pipeline.

    This processor can use either a pre-generated tone file or directly passed audio data.
    """

    def __init__(self, audio_data=None, tone_file_path=None, sample_rate=8000):
        """Initialize the SimpleAudioFrameInserter.

        Args:
            audio_data: NumPy array containing the audio data (priority over tone_file_path)
            tone_file_path: Path to the audio file containing tone data (used if audio_data is None)
            sample_rate: Sample rate of the audio frames to be sent
        """
        super().__init__()
        self.sample_rate = sample_rate
        self.tone_file_path = tone_file_path
        self.audio_data = audio_data
        self.frame_size = int(sample_rate * 0.02)  # 20ms frames
        self.num_frames = 0
        self.running = False
        self._send_task = None

    async def setup(self):
        """Load the tone file data during setup if needed."""
        await super().setup()

        try:
            # If audio data was passed directly, use it
            if self.audio_data is not None:
                logger.info(f"Using provided audio data with {len(self.audio_data)} samples")
            # Otherwise, load from file or generate
            elif self.tone_file_path:
                import soundfile as sf

                self.audio_data, _ = sf.read(self.tone_file_path, dtype="int16")
                logger.info(f"Loaded tone file with {len(self.audio_data)} samples")
            else:
                # Generate tone data if neither was provided
                self.audio_data = generate_tone_data(
                    freq=400, duration=5.0, sample_rate=self.sample_rate
                )
                logger.info(f"Generated tone data with {len(self.audio_data)} samples")

            # Calculate the number of frames and validate
            if self.frame_size <= 0:
                raise ValueError(f"Invalid frame size: {self.frame_size}")

            self.num_frames = len(self.audio_data) // self.frame_size

            if self.num_frames <= 0:
                raise ValueError(
                    f"Audio data too short for frame size. Audio length: {len(self.audio_data)}, Frame size: {self.frame_size}"
                )

            logger.info(
                f"Audio data prepared with {self.num_frames} frames of {self.frame_size} samples each"
            )
        except Exception as e:
            logger.error(f"Error setting up SimpleAudioFrameInserter: {e}")
            raise

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        """Pass all frames through this processor."""
        await super().process_frame(frame, direction)
        await self.push_frame(frame, direction)

    def start_sending(self):
        """Start a loop that sends audio frames."""
        if self.running:
            logger.warning("Audio sender is already running")
            return

        self.running = True
        self._send_task = self.get_event_loop().create_task(self._send_loop())

    def stop_sending(self):
        """Stop sending audio frames."""
        if not self.running:
            return

        self.running = False
        if self._send_task and not self._send_task.done():
            self._send_task.cancel()

    async def _send_loop(self):
        """Send audio frames at a consistent rate."""
        try:
            logger.debug("Starting SimpleAudioFrameInserter send loop")

            # Verify that we have valid audio data and frame configuration
            if self.audio_data is None or len(self.audio_data) == 0:
                raise ValueError("No audio data available")

            if self.num_frames <= 0:
                raise ValueError(f"Invalid number of frames: {self.num_frames}")

            frame_index = 0

            # Use a sliding window approach rather than fixed start time
            # to prevent drift over long periods
            next_frame_time = time.time()

            while self.running:
                # Calculate frame start position in the audio data
                frame_start = (frame_index % self.num_frames) * self.frame_size

                # Get the audio data for this frame
                frame_end = min(frame_start + self.frame_size, len(self.audio_data))
                frame_data = self.audio_data[frame_start:frame_end]

                # Create and send the audio frame
                audio_frame = OutputAudioRawFrame(
                    audio=frame_data.tobytes(),
                    sample_rate=self.sample_rate,
                    num_channels=1,
                )
                await self.push_frame(audio_frame)

                # Increment frame index and wrap around if needed
                frame_index += 1

                # Update next frame time (20ms per frame = 50fps)
                next_frame_time += 0.02

                # Sleep until next frame time
                sleep_time = max(0, next_frame_time - time.time())

                # If we're significantly behind, reset the timing
                if sleep_time <= 0:
                    logger.warning(f"Audio frame sending is falling behind by {-sleep_time:.3f}s")
                    next_frame_time = time.time() + 0.02
                    sleep_time = 0.02

                await asyncio.sleep(sleep_time)

        except asyncio.CancelledError:
            logger.info("Audio sending task cancelled")
        except Exception as e:
            logger.error(f"Error in audio sending loop: {e}")
            self.running = False

    async def teardown(self):
        """Clean up resources when the processor is shutting down."""
        self.stop_sending()
        await super().teardown()


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
            audio_out_sample_rate=AUDIO_SAMPLE_RATE,
            vad_enabled=True,
            vad_analyzer=SileroVADAnalyzer(),
            vad_audio_passthrough=True,
        ),
    )

    # Generate the tone data directly in memory
    tone_data = generate_tone_data(freq=400, duration=50.0, sample_rate=AUDIO_SAMPLE_RATE)

    # Create the audio frame inserter with the generated tone data
    audio_sender = SimpleAudioFrameInserter(audio_data=tone_data, sample_rate=AUDIO_SAMPLE_RATE)

    # Configure your STT, LLM, and TTS services here
    # Swap out different processors or properties to customize your bot
    # stt = DeepgramSTTService(api_key=os.getenv("DEEPGRAM_API_KEY"))
    llm = OpenAILLMService(api_key=os.getenv("OPENAI_API_KEY"), model="gpt-4o")
    # tts = CartesiaTTSService(
    #     api_key=os.getenv("CARTESIA_API_KEY"),
    #     voice_id="71a7ad14-091c-4e8e-a314-022ece01c121",
    # )

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

    tools = NotGiven()

    # This sets up the LLM context by providing messages and tools
    messages = [
        {
            "role": "system",
            "content": """You are a helpfil voice AI bot that can answer questions.
                """,
        },
    ]
    context = OpenAILLMContext(messages, tools)
    context_aggregator = llm.create_context_aggregator(context)

    # A core voice AI pipeline
    # Add additional processors to customize the bot's behavior
    pipeline = Pipeline(
        [
            transport.input(),
            audio_sender,
            transport.output(),
        ]
    )

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            allow_interruptions=False,
            audio_in_sample_rate=8000,
            audio_out_sample_rate=8000,
            enable_metrics=True,
            enable_usage_metrics=True,
        ),
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
        if state == "joined":
            await asyncio.sleep(1)
            audio_sender.start_sending()
            # Start all dial-out calls if configured
            if dialout_settings and "dialout" in handlers:
                for handler in handlers["dialout"]:
                    await handler.start()
        elif state == "left":
            audio_sender.stop_sending()
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
