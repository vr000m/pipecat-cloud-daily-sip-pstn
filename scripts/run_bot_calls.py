import argparse
import asyncio
import json
import os
import subprocess
import sys
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

# Configuration
WAIT_MINUTES = 5
API_URL = os.getenv("API_URL", "http://pcc-dial-webhook-handler.vercel.app/")

DIALOUT_SETTINGS = [
    {"phoneNumber": "+17868748498", "callerId": "15aad0ec-4d50-4c7f-aa0d-2158316deb03"},
    {"sipUri": "sip:+17868748498@daily-twilio-integration.sip.twilio.com"},
    {"phoneNumber": "+17868748498"},
]


async def make_bot_call(dialout_setting):
    """Make a single bot call using curl"""
    payload = {"dialout_settings": [dialout_setting]}

    curl_command = [
        "curl",
        "-X",
        "POST",
        f"{API_URL}/bot/call",
        "-H",
        "Content-Type: application/json",
        "-d",
        json.dumps(payload),
    ]

    try:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        target = dialout_setting.get("phoneNumber") or dialout_setting.get("sipUri")
        print(f"\n[{timestamp}] Calling {target}...")

        result = subprocess.run(curl_command, capture_output=True, text=True)
        if result.returncode == 0:
            print(f"Success: {result.stdout}")
        else:
            print(f"Error: {result.stderr}")
    except Exception as e:
        print(f"Failed to make call: {str(e)}")


def parse_args():
    parser = argparse.ArgumentParser(description="Run bot calls with intervals")
    parser.add_argument(
        "--wait", type=int, default=5, help="Wait time in minutes between calls (default: 5)"
    )
    parser.add_argument("--config", type=str, help="Path to JSON config file with dialout settings")
    return parser.parse_args()


async def main():
    args = parse_args()
    global WAIT_MINUTES
    WAIT_MINUTES = args.wait

    if args.config:
        global DIALOUT_SETTINGS
        with open(args.config) as f:
            DIALOUT_SETTINGS = json.load(f)

    print(f"Starting bot calls with {WAIT_MINUTES} minute intervals")

    for i, dialout_setting in enumerate(DIALOUT_SETTINGS, 1):
        await make_bot_call(dialout_setting)

        if i < len(DIALOUT_SETTINGS):
            print(f"\nWaiting {WAIT_MINUTES} minutes before next call...")
            await asyncio.sleep(WAIT_MINUTES * 60)

    print("\nAll calls completed!")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nScript interrupted by user")
        sys.exit(1)
