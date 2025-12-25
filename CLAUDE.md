# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Pipecat CLI Installation
```bash
# Install pipecat CLI (required for deployment)
uv tool install pipecat-ai-cli
# Or with pipx:
pipx install pipecat-ai-cli

# Optional: Install with tail dashboard for real-time monitoring
uv tool install "pipecat-ai-cli[tail]"

# Authenticate with Pipecat Cloud
pipecat cloud auth login

# List and select organization
pipecat cloud organizations list
pipecat cloud organizations select
```

### Pipecat Cloud Organization & Agents
**Organization**: Default Workspace1 (`disastrous-mockingbird-amethyst-180`)

| Agent Name | Region | Description |
|------------|--------|-------------|
| `my-pstn-agent` | us-west | Main /bot Daily-native PSTN agent |
| `vr000m-pcc-twilio-sip-eu` | eu-central | /bot-eu Twilio+Daily SIP (EU) |
| `vr000m-pcc-twilio-sip-us` | us-west | /bot-eu Twilio+Daily SIP (US) |

```bash
# View agent logs
pipecat cloud agent logs my-pstn-agent
pipecat cloud agent logs vr000m-pcc-twilio-sip-eu
pipecat cloud agent logs vr000m-pcc-twilio-sip-us
```

### Docker & Image Pull Secrets Setup
```bash
# Login to Docker Hub (one-time setup)
docker login -u pluot

# Create image pull secrets (one-time setup per region)
pipecat cloud secrets image-pull-secret pluot-image-pull-secret-eu https://index.docker.io/v1/ --region eu-central
pipecat cloud secrets image-pull-secret pluot-image-pull-secret-us https://index.docker.io/v1/
```

### Staging Environment
```bash
# To use staging infrastructure, pass PIPECAT_API_HOST inline with each command
PIPECAT_API_HOST="https://staging.qa.pipecat.cloud" pipecat cloud auth login
PIPECAT_API_HOST="https://staging.qa.pipecat.cloud" pipecat cloud secrets image-pull-secret pluot-image-pull-secret-eu https://index.docker.io/v1/ --region eu-central
PIPECAT_API_HOST="https://staging.qa.pipecat.cloud" pipecat cloud docker build-push
PIPECAT_API_HOST="https://staging.qa.pipecat.cloud" pipecat cloud deploy
```

### Bot Development (`/bot` - Daily-native PSTN)
```bash
# Install Python dependencies for the bot
cd bot && uv sync
# Or with pip:
cd bot && pip install -r requirements.txt

# Run locally (for development with unified-webhook-server)
cd bot && uv run python -m pipecat.runner.run  # Starts on port 7860

# Deploy bot to Pipecat Cloud
cd bot && ./deploy.sh

# Or deploy manually:
pipecat cloud docker build-push
pipecat cloud deploy

# List all deployed agents
pipecat cloud agent list

# View agent logs
pipecat cloud agent logs [AGENT_NAME]

# Real-time monitoring (local bot)
pipecat tail

# Real-time monitoring (remote)
pipecat tail --url wss://your-bot.example.com
```

### Bot-EU Development (`/bot-eu` - Twilio + Daily SIP)
```bash
# Install Python dependencies
cd bot-eu && pip install -r requirements.txt
# Or with uv:
cd bot-eu && uv sync

# Run locally (two terminals needed)
cd bot-eu && uv run server.py       # Terminal 1: Webhook server on port 8080
cd bot-eu && uv run bot.py -t daily # Terminal 2: Bot with Daily transport

# Deploy to Pipecat Cloud (EU region)
cd bot-eu
cp pcc-deploy-eu.toml pcc-deploy.toml
pipecat cloud docker build-push
pipecat cloud deploy

# Deploy to Pipecat Cloud (US region)
cd bot-eu
cp pcc-deploy-us.toml pcc-deploy.toml
pipecat cloud docker build-push
pipecat cloud deploy

# View agent logs
pipecat cloud agent logs vr000m-pcc-twilio-sip-eu
pipecat cloud agent logs vr000m-pcc-twilio-sip-us
```

**Note**: When merging `bot-eu/server.py` into `fastapi-webhook-server`, consider keeping a local `server.py` in bot-eu for simplicity of local development.

**Future improvements**:

1. **Dynamic region deployment**: Refactor deploy.sh to use a single base `pcc-deploy-base.toml` with dynamic region selection. Available regions: `ap-south`, `eu-central`, `us-east`, `us-west` (default). The script would:
   - Append region suffix (e.g., `-eu`, `-us`) to: `agent_name`, `image`, `image_credentials`, `secret_set`
   - Add `region` field only if not us-west (the default)
   - Copy modified config to `pcc-deploy.toml` for deployment

2. **Setup utility**: Create a `create-pipecat-toml` utility that:
   - Prompts for agent details (name, image registry, regions to deploy)
   - Creates required `secret_set` and `image_credentials` in Pipecat Cloud per region
   - Generates `pcc-deploy-base.toml` with the provided configuration
   - Relevant commands for setup:
     ```bash
     pipecat cloud secrets image-pull-secret <name> <registry-url> [--region <region>]
     pipecat cloud secrets --help  # for secret_set management
     ```

### Unified Webhook Server (`/unified-webhook-server`)
Handles both Daily-native PSTN and Twilio+Daily SIP webhooks in a single FastAPI server.

```bash
# Install dependencies
cd unified-webhook-server && pip install -r requirements.txt

# Run locally (three terminals needed)
cd unified-webhook-server && uvicorn server:app --reload --port 8080  # Terminal 1: Webhook server
cd bot-eu && uv run bot.py -t daily                                    # Terminal 2: Bot
ngrok http 8080                                                        # Terminal 3: Expose to internet

# Endpoints:
# /api/dial         - Daily pinless dial-in webhook (JSON response)
# /api/twilio/call  - Twilio call webhook (TwiML response)
# /health           - Health check
```

**Deployment**: The server is deployment-agnostic. Deploy to Cloudflare Workers, AWS Lambda, Google Cloud Run, etc.

### Legacy: Webhook Server (FastAPI)
```bash
# Install dependencies
cd fastapi-webhook-server && pip install -r requirements.txt

# Run locally
python server.py

# Expose via ngrok for testing
ngrok http 3000
```

### Webhook Server (Next.js/Vercel)
```bash
# Install dependencies
cd nextjs-webhook-server && npm install

# Run development server
npm run dev

# Build for production
npm run build

# Run production server
npm start

# Lint code
npm run lint

# Deploy to Vercel
npx vercel

# Update phone configuration from Daily APIs
npm run update-phones

# Test phone number normalization (including vanity numbers)
npm run test-phone

# Test SIP URI normalization  
npm run test-sip

# Run both normalization tests
npm run test-normalization
```

## Architecture

This repository implements a PSTN/SIP telephony system using Pipecat Cloud with the following components:

### 1. Voice Bot (`/bot`) - Daily-native PSTN
The core conversational AI that handles phone calls via Daily's native PSTN. Key files:
- `bot_voice_v2.py`: Current production bot with dial-in/dial-out handlers
- Uses Pipecat framework with Daily for WebRTC transport
- Integrates Deepgram (STT), OpenAI (LLM), and Cartesia (TTS)
- Deployed as Docker container to Pipecat Cloud via `pcc-deploy.toml`
- Supports both inbound (dial-in) and outbound (dial-out) calls

### 2. Voice Bot EU (`/bot-eu`) - Twilio + Daily SIP
Alternative implementation using Twilio as PSTN provider with Daily SIP. Key files:
- `bot.py`: Voice bot with region-based Twilio credential selection
- `server.py`: FastAPI webhook handler for Twilio `/call` endpoint
- `server_utils.py`: Utilities for Daily room creation and bot starting
- `pcc-deploy-eu.toml`: EU deployment (eu-central region)
- `pcc-deploy-us.toml`: US deployment

**Region-based routing**: The bot selects Twilio credentials based on dialed number:
- `+1` numbers (US/Canada) → `TWILIO_AUTH_TOKEN_US` with `us1` region
- All other numbers → `TWILIO_AUTH_TOKEN_EU` with `ie1` (Ireland) region

**Call flow**:
1. User calls Twilio phone number
2. Twilio sends webhook to `server.py` `/call` endpoint
3. Server creates Daily room with SIP capabilities via `pipecat.runner.daily.configure`
4. Server starts bot (locally or via Pipecat Cloud based on `ENV`)
5. Bot receives `on_dialin_ready` event
6. Bot uses Twilio API to forward call to Daily SIP endpoint
7. Caller connected to bot

**Note**: The `bot-eu/server.py` can be used standalone for simple local development, or replaced by the unified webhook server (see below).

### 3. Unified Webhook Server (`/unified-webhook-server`)
A single FastAPI server that handles both Daily-native PSTN and Twilio+Daily SIP webhooks.

**Endpoints:**
- `/api/dial` - Daily pinless dial-in webhook (JSON response)
- `/api/twilio/call` - Twilio call webhook (TwiML response)
- `/health` - Health check

**Key features:**
- Async HTTP with aiohttp for concurrent webhook handling
- HMAC validation for Daily webhooks
- Uses `pipecat.runner.daily.configure()` for Twilio flow room creation
- Deployment-agnostic (Cloudflare Workers, Lambda, Cloud Run, etc.)

**Project structure:**
```
unified-webhook-server/
├── server.py              # Main FastAPI app
├── handlers/
│   ├── daily.py           # /api/dial handler
│   └── twilio.py          # /api/twilio/call handler
├── utils/
│   └── hmac_validation.py # HMAC signature verification
├── models.py              # Pydantic request models
└── requirements.txt       # Dependencies
```

### 4. Legacy Webhook Servers

**FastAPI Server (`/fastapi-webhook-server`)** - Legacy, use unified-webhook-server instead
- Receives webhook from Daily when call arrives
- Validates HMAC signature for security
- Creates Daily room and starts bot via Pipecat Cloud API
- Returns room properties for call routing

**Next.js Server (`/nextjs-webhook-server`)**
- Serverless alternative for Vercel deployment
- Dynamic environment routing based on phone numbers/SIP URIs
- Per-phone HMAC validation with individual secrets
- Handles vanity numbers (+1800FLOWERS) and SIP URI normalization
- Validates callerId as UUID for dial-out requests
- Handles `/api/dial` endpoint for both dial-in and dial-out

### 5. Call Flow

**Dial-in (incoming calls):**
1. User calls purchased phone number
2. Daily receives call, triggers webhook to server
3. Server validates request and calls Pipecat Cloud `/start` endpoint
4. Bot joins Daily room with `dialin_settings`
5. Call is forwarded to bot, conversation begins

**Dial-out (outgoing calls):**
1. External system calls `/api/dial` with `dialout_settings` and `callerId` (purchased phone UUID)
2. Server validates callerId is UUID, looks up environment from `phone.yml`
3. Server creates room with `dialout_settings` using correct environment
4. Bot initiates outbound call via Daily
5. Bot waits for remote party to answer before speaking

## Key Environment Variables

Required across all components:
- `PIPECAT_CLOUD_API_KEY_PROD`: Pipecat Cloud API key for production (pk_prod_*)
- `PIPECAT_CLOUD_API_KEY_STAGING`: Pipecat Cloud API key for staging (pk_staging_*)
- `AGENT_NAME`: Deployed agent name
- `PINLESS_HMAC_SECRET`: Default HMAC secret (individual phones can override)
- `DAILY_API_KEY_PROD`: Daily API key for production phone config fetching
- `DAILY_API_KEY_STAGING`: Daily API key for staging phone config fetching

Bot-specific (`/bot` and `/bot-eu` share these):
- `DAILY_API_KEY`: Daily API access
- `OPENAI_API_KEY`: OpenAI LLM service
- `DEEPGRAM_API_KEY`: Speech-to-text service
- `CARTESIA_API_KEY`: Text-to-speech service

Bot-EU additional (`/bot-eu` only):
- `TWILIO_ACCOUNT_SID`: Twilio account (shared across regions)
- `TWILIO_AUTH_TOKEN`: Fallback auth token
- `TWILIO_AUTH_TOKEN_US`: US region Twilio credentials
- `TWILIO_AUTH_TOKEN_EU`: EU region Twilio credentials
- `ENV`: Environment mode (`local` or `production`)
- `LOCAL_SERVER_URL`: Local bot server URL (default: `http://localhost:7860`)
- `PIPECAT_API_KEY`: Pipecat Cloud API key (for production)
- `PIPECAT_AGENT_NAME`: Agent name for Pipecat Cloud
- `PIPECAT_HOSTNAME`: Pipecat Cloud hostname (optional, for staging)

## Phone Configuration System

The Next.js webhook server uses `phone.yml` to manage phone number routing and HMAC validation:

### Key Concepts
- **Dialin Config ID** (`id`): UUID from Daily's domain-dialin-config endpoint
- **Purchased Phone ID** (`purchased_phone_id`): UUID from Daily's purchased-phone-numbers endpoint
- **CallerId Validation**: Dial-out requires purchased phone ID as callerId, not dialin config ID

### Configuration Structure
```yaml
prod:
  phone_numbers:
    - id: "dialin-config-uuid"                    # For webhook routing
      purchased_phone_id: "purchased-phone-uuid" # For callerId in dial-out
      number: "+16502315623"
      hmac_secret: "individual-phone-secret"     # Per-phone HMAC
      sip_uri: "sip:address@domain.com"
      webhook_url: "https://your-app.vercel.app/api/dial"
```

### Features
- **Dynamic Environment Routing**: Routes calls to staging/prod based on phone number
- **Phone Number Normalization**: Handles vanity numbers (+1800FLOWERS → +18003569377)  
- **SIP URI Support**: Normalizes SIP addresses with ports/parameters
- **Per-Phone HMAC**: Each phone can have its own HMAC secret for enhanced security
- **Auto-Configuration**: Script fetches latest config from both Daily API endpoints

## Testing

### Automated Tests
- Phone number normalization: `npm run test-phone` 
- SIP URI normalization: `npm run test-sip`
- Both tests: `npm run test-normalization`

### Manual Testing Workflow
1. Deploy bot using `deploy.sh`
2. Update phone configuration: `npm run update-phones`
3. Run webhook server locally or deploy to Vercel
4. Test with curl commands using correct purchased phone UUIDs as callerId

## Important Patterns

- Bot selection: `deploy.sh` uses `deploy_map.txt` to map bot files to deployment configs
- Event handling: Bot uses Daily transport event handlers for call lifecycle
- Error handling: Both webhook servers validate signatures and handle Daily API errors
- Logging: Structured logging with loguru (Python) and pino (JavaScript)