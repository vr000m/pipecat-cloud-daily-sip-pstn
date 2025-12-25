# Unified Webhook Server

A single FastAPI server that handles both Daily-native PSTN and Twilio+Daily SIP webhook flows.

## Endpoints

| Endpoint | Source | Response | Purpose |
|----------|--------|----------|---------|
| `/api/dial` | Daily pinless dialin | JSON | Daily-native PSTN |
| `/api/twilio/call` | Twilio webhook | TwiML | Twilio → Daily SIP |
| `/health` | Any | JSON | Health check |

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env with your API keys
```

### 3. Run the server

```bash
uvicorn server:app --reload --port 8080
```

## Local Development with bot-eu

For testing with Twilio, run the bot locally alongside the webhook server:

**Terminal 1** - Webhook server:
```bash
cd unified-webhook-server
uvicorn server:app --reload --port 8080
```

**Terminal 2** - Bot:
```bash
cd bot-eu
uv run bot.py -t daily
```

**Terminal 3** - Expose via ngrok:
```bash
ngrok http 8080
```

Then configure Twilio to send webhooks to `https://<ngrok-url>/api/twilio/call`.

## Call Flows

### Daily-native PSTN (`/api/dial`)

1. User calls a Daily phone number
2. Daily sends webhook to `/api/dial`
3. Server validates HMAC signature
4. Server calls Pipecat Cloud `/start` API
5. Bot joins Daily room, call is connected

### Twilio + Daily SIP (`/api/twilio/call`)

1. User calls a Twilio phone number
2. Twilio sends webhook to `/api/twilio/call`
3. Server creates Daily room with SIP via `pipecat.runner.daily.configure()`
4. Server starts bot (local or Pipecat Cloud)
5. Server returns TwiML with hold music
6. Bot forwards Twilio call to Daily SIP endpoint
7. Caller connected to bot

## Environment Variables

See `.env.example` for all available configuration options.

### Key Variables

| Variable | Handler | Description |
|----------|---------|-------------|
| `PIPECAT_CLOUD_API_KEY` | Daily | Pipecat Cloud API key |
| `AGENT_NAME` | Daily | Agent name in Pipecat Cloud |
| `PINLESS_HMAC_SECRET` | Daily | HMAC secret (base64-encoded) |
| `PIPECAT_API_KEY` | Twilio | Pipecat Cloud API key |
| `PIPECAT_AGENT_NAME` | Twilio | Agent name in Pipecat Cloud |
| `DAILY_API_KEY` | Twilio | Daily API key for room creation |
| `ENV` | Both | `production` or `local` |
| `LOCAL_SERVER_URL` | Both | Local bot URL (when ENV=local) |

## Deployment

This server is deployment-agnostic. Deploy to your platform of choice:

- **Cloudflare Workers** - Use ASGI adapter
- **AWS Lambda** - Use Mangum
- **Google Cloud Run** - Deploy container
- **Fly.io** - Deploy with `fly.toml`
- **Railway** - Deploy from GitHub

## Project Structure

```
unified-webhook-server/
├── server.py              # Main FastAPI app
├── handlers/
│   ├── __init__.py
│   ├── daily.py           # /api/dial handler
│   └── twilio.py          # /api/twilio/call handler
├── utils/
│   ├── __init__.py
│   └── hmac_validation.py # HMAC signature verification
├── models.py              # Pydantic request models
├── requirements.txt       # Dependencies
├── .env.example           # Environment template
└── README.md              # This file
```
