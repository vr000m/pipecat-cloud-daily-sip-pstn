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
- Same functionality as FastAPI but JavaScript-based
- Handles `/api/dial` endpoint for both dial-in and dial-out

### 3. Call Flow

**Dial-in (incoming calls):**
1. User calls purchased phone number
2. Daily receives call, triggers webhook to server
3. Server validates request and calls Pipecat Cloud `/start` endpoint
4. Bot joins Daily room with `dialin_settings`
5. Call is forwarded to bot, conversation begins

**Dial-out (outgoing calls):**
1. External system calls `/api/dial` with target phone number
2. Server creates room with `dialout_settings`
3. Bot initiates outbound call via Daily
4. Bot waits for remote party to answer before speaking

## Key Environment Variables

Required across all components:
- `PIPECAT_CLOUD_API_KEY`: Pipecat Cloud API key (pk_*)
- `AGENT_NAME`: Deployed agent name
- `PINLESS_HMAC_SECRET`: Webhook signature validation

Bot-specific:
- `DAILY_API_KEY`: Daily API access
- `OPENAI_API_KEY`: OpenAI LLM service
- `DEEPGRAM_API_KEY`: Speech-to-text service  
- `CARTESIA_API_KEY`: Text-to-speech service

## Testing

Currently no automated tests. Manual testing workflow:
1. Deploy bot using `deploy.sh`
2. Run webhook server locally
3. Use ngrok to expose local server
4. Configure Daily phone number webhook to ngrok URL
5. Test with curl commands or actual phone calls

## Important Patterns

- Bot selection: `deploy.sh` uses `deploy_map.txt` to map bot files to deployment configs
- Event handling: Bot uses Daily transport event handlers for call lifecycle
- Error handling: Both webhook servers validate signatures and handle Daily API errors
- Logging: Structured logging with loguru (Python) and pino (JavaScript)