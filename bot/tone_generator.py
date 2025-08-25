import argparse
import signal
import sys
import time

import numpy as np
import sounddevice as sd
from scipy import signal as scipy_signal

# Global flag to indicate if we should stop playback
stop_playback = False


def signal_handler(sig, frame):
    """Handle signal interrupts like CTRL+C"""
    global stop_playback
    print("\nStopping playback...")
    stop_playback = True
    sd.stop()
    sys.exit(0)


def generate_tone(frequency, duration=10, amplitude=0.5, sample_rate=44100, waveform="sine"):
    """
    Generate an audible tone of specified frequency.

    Args:
        frequency (float): Frequency of the tone in Hz
        duration (float): Duration of the tone in seconds (default: 10)
        amplitude (float): Amplitude of the tone between 0 and 1 (default: 0.5)
        sample_rate (int): Sample rate in Hz (default: 44100)
        waveform (str): Type of waveform - 'sine', 'square', 'sawtooth', 'triangle' (default: 'sine')
    """
    # Generate time array
    t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)

    # Generate waveform based on selection
    if waveform == "sine":
        # Generate sine wave
        tone = amplitude * np.sin(2 * np.pi * frequency * t)
    elif waveform == "square":
        # Generate square wave
        tone = amplitude * scipy_signal.square(2 * np.pi * frequency * t)
    elif waveform == "sawtooth":
        # Generate sawtooth wave
        tone = amplitude * scipy_signal.sawtooth(2 * np.pi * frequency * t)
    elif waveform == "triangle":
        # Generate triangle wave
        tone = amplitude * scipy_signal.sawtooth(2 * np.pi * frequency * t, width=0.5)
    else:
        raise ValueError(f"Waveform type '{waveform}' not recognized")

    # Apply fade in/out to avoid clicks
    fade_duration = min(0.1, duration / 10)  # 100ms or 10% of duration, whichever is smaller
    fade_samples = int(fade_duration * sample_rate)

    if fade_samples > 0:
        fade_in = np.linspace(0, 1, fade_samples)
        fade_out = np.linspace(1, 0, fade_samples)
        tone[:fade_samples] *= fade_in
        tone[-fade_samples:] *= fade_out

    return tone, sample_rate


def play_tone(frequency, duration=10, amplitude=0.5, sample_rate=44100, waveform="sine"):
    """
    Generate and play a tone with the given parameters.

    Args:
        frequency (float): Frequency of the tone in Hz
        duration (float): Duration of the tone in seconds (default: 10)
        amplitude (float): Amplitude of the tone between 0 and 1 (default: 0.5)
        sample_rate (int): Sample rate in Hz (default: 44100)
        waveform (str): Type of waveform - 'sine', 'square', 'sawtooth', 'triangle' (default: 'sine')
    """
    global stop_playback
    stop_playback = False

    tone, sample_rate = generate_tone(frequency, duration, amplitude, sample_rate, waveform)

    # Play the tone
    sd.play(tone, sample_rate)

    # Wait for the tone to finish or until interrupted
    start_time = time.time()
    try:
        while sd.get_stream().active and time.time() - start_time < duration:
            if stop_playback:
                break
            time.sleep(0.1)  # Check every 100ms
    finally:
        sd.stop()


if __name__ == "__main__":
    # Register the signal handler for Ctrl+C
    signal.signal(signal.SIGINT, signal_handler)

    parser = argparse.ArgumentParser(description="Generate and play an audible tone.")
    parser.add_argument("frequency", type=float, help="Frequency of the tone in Hz")
    parser.add_argument(
        "--duration",
        "-d",
        type=float,
        default=10.0,
        help="Duration of the tone in seconds (default: 10)",
    )
    parser.add_argument(
        "--amplitude",
        "-a",
        type=float,
        default=0.5,
        help="Amplitude of the tone between 0 and 1 (default: 0.5)",
    )
    parser.add_argument(
        "--sample-rate", "-sr", type=int, default=44100, help="Sample rate in Hz (default: 44100)"
    )
    parser.add_argument(
        "--waveform",
        "-w",
        type=str,
        default="sine",
        choices=["sine", "square", "sawtooth", "triangle"],
        help="Type of waveform (default: sine)",
    )

    args = parser.parse_args()

    try:
        print(f"Playing {args.waveform} wave at {args.frequency} Hz for {args.duration} seconds...")
        print("Press Ctrl+C to stop playback")
        play_tone(args.frequency, args.duration, args.amplitude, args.sample_rate, args.waveform)
        print("Done!")
    except Exception as e:
        print(f"Error: {e}")
