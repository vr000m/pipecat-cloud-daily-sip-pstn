# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Bot Development
```bash
# Install Python dependencies for the bot
cd bot && pip install -r requirements.txt

# Deploy bot to Pipecat Cloud
cd bot && ./deploy.sh

# Check agent status
pcc agent status [AGENT_NAME]

# View agent deployments  
pcc agent deployments [AGENT_NAME]
```

### Webhook Server (FastAPI)
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

This repository implements a PSTN/SIP telephony system using Pipecat Cloud with three main components:

### 1. Voice Bot (`/bot`)
The core conversational AI that handles phone calls. Key files:
- `bot_voice_v2.py`: Current production bot with dial-in/dial-out handlers
- Uses Pipecat framework with Daily for WebRTC transport
- Integrates Deepgram (STT), OpenAI (LLM), and Cartesia (TTS)
- Deployed as Docker container to Pipecat Cloud via `pcc-deploy.toml`
- Supports both inbound (dial-in) and outbound (dial-out) calls

### 2. Webhook Servers
Two implementations that handle Daily's pinless dial-in webhooks:

**FastAPI Server (`/fastapi-webhook-server`)**
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

### 3. Call Flow

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

Bot-specific:
- `DAILY_API_KEY`: Daily API access
- `OPENAI_API_KEY`: OpenAI LLM service
- `DEEPGRAM_API_KEY`: Speech-to-text service  
- `CARTESIA_API_KEY`: Text-to-speech service

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