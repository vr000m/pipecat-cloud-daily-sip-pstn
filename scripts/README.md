# Bot Call Scripts

Utilities for running automated bot calls with configurable delays.

## Setup

1. Create and activate a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows use: venv\Scripts\activate
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Configure environment variables:
```bash
cp .env.example .env
# Edit .env with your settings
```

## Usage

### Basic Run
Run with default settings (5 minute intervals):
```bash
python run_bot_calls.py
```

### Custom Wait Time
Run with custom interval between calls:
```bash
python run_bot_calls.py --wait 10  # 10 minute intervals
```

### Custom Configuration File
Run with custom dialout settings from a JSON file:
```bash
# Copy and modify the example config
cp config.example.json my_config.json
python run_bot_calls.py --config my_config.json
```

## Configuration Examples

### Example config.json
```json
[
    {
        "phoneNumber": "+1234567890",
        "callerId": "your-caller-id"
    },
    {
        "sipUri": "sip:+1234567890@sip.example.com"
    },
    {
        "phoneNumber": "+1987654321"
    }
]
```

### Example Curl Commands
Test individual calls using curl:
```bash
# Direct phone call with caller ID
curl -X POST http://localhost:3000/api/dial \
    -H "Content-Type: application/json" \
    -d '{"dialout_settings": [{"phoneNumber": "+1234567890", "callerId":"your-caller-id"}]}'

# SIP URI call
curl -X POST http://localhost:3000/api/dial \
    -H "Content-Type: application/json" \
    -d '{"dialout_settings": [{"sipUri": "sip:+1234567890@daily-twilio-integration.sip.twilio.com"}]}'
```

## Error Handling

- The script will log all successful and failed attempts
- Use Ctrl+C to safely interrupt the script
- Failed calls will be logged but won't stop the script
