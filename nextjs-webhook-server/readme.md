# Daily API Backend

Next.js API routes for handling Daily Pipecat requests.

## Features

- API endpoint for handling Daily Pipecat requests
- Dynamic environment routing based on phone numbers or SIP URIs
- Automatic phone configuration sync from Daily API
- Per-phone-number/SIP-URI HMAC signature validation for enhanced security
- Structured logging with Pino
- Support for dialin and dialout settings
- Voicemail detection and call transfer functionality
- Test request handling

## Setup

1. Clone the repository
2. Install dependencies:
   ```bash
   npm install
   ```
3. Create `.env.local` file with your credentials:
   ```
   PIPECAT_CLOUD_API_KEY_PROD=pk_prod_*
   PIPECAT_CLOUD_API_KEY_STAGING=pk_staging_*
   AGENT_NAME=my-first-agent
   PINLESS_HMAC_SECRET=your_hmac_secret
   LOG_LEVEL=info
   ```
4. Configure phone numbers:
   - Option A: Manually edit `phone.yml` to map phone numbers to environments
   - Option B: Auto-fetch from Daily API using `npm run update-phones` (requires DAILY_API_KEY_* env vars)
5. Run the development server:
   ```bash
   npm run dev
   ```

## API Endpoints

### GET /api
Returns a simple "Hello, World!" message with a cute cat emoji to verify the server is running.

### POST /api/dial
Handles dialin and dialout requests for Daily Pipecat.

#### Test Requests
The endpoint handles test requests when a webhook is configured. Send a request with `"Test": "test"` to verify your setup:
```json
{
  "Test": "test"
}
```

#### Production Request Format
```json
{
  // for dial-in from webhook
  "To": "+14152251493",
  "From": "+14158483432",
  "callId": "string-contains-uuid",
  "callDomain": "string-contains-uuid",
  "sipHeaders": {
      "X-My-Custom-Header": "value",
      "x-caller": "+14158483432",
      "x-called": "+14152251493",
   },
  // for making a dial out to a phone or SIP
  "dialout_settings": [
    {"phoneNumber": "+14158483432", "callerId": "purchased_phone_uuid"}, 
    {"sipUri": "sip:username@sip.hostname.com"}
  ],
}
```

## Phone Number Management

### Automatic Phone Configuration

The application can automatically fetch and sync phone numbers from your Daily account:

```bash
# Fetch phone numbers from both prod and staging Daily APIs
npm run update-phones
```

This command will:
- Connect to both production and staging Daily APIs
- Fetch all configured phone numbers with their HMAC secrets
- Update `phone.yml` with the latest configuration
- Show a summary of discovered phone numbers

**Security Note**: Each phone number and SIP URI has its own HMAC secret that's automatically fetched from Daily. This provides better security than using a single shared secret.

**SIP URI Support**: The webhook can handle both phone numbers and SIP URIs in the `To` field. The system automatically detects whether it's a phone number or SIP URI and looks up the appropriate configuration.

### Manual Phone Configuration

You can also manually edit `phone.yml` to add or modify phone numbers:

```yaml
prod:
  phone_numbers:
    - id: "unique-id"
      number: "+1234567890"
      description: "Main production line"
      webhook_url: "https://your-webhook.com/api/dial"
      sip_uri: "sip:address@example.com"
      hmac_secret: "base64-encoded-secret"
      type: "pinless_dialin"

staging:
  phone_numbers:
    - id: "unique-id"
      number: "+1987654321"
      description: "Testing line"
      webhook_url: "https://your-webhook.com/api/dial"
      hmac_secret: "base64-encoded-secret"
      type: "pinless_dialin"
```

## Deployment

The application is configured for Vercel deployment:

1. Push your code to a Git repository
2. Import your project in Vercel dashboard
3. Configure environment variables:
   - `PIPECAT_CLOUD_API_KEY_PROD` - Production Pipecat Cloud API key
   - `PIPECAT_CLOUD_API_KEY_STAGING` - Staging Pipecat Cloud API key
   - `AGENT_NAME` - Your agent name
   - `PINLESS_HMAC_SECRET` - HMAC secret for webhook validation
   - `LOG_LEVEL` (optional, defaults to 'info')
4. Deploy!

```
❯ npx vercel

Vercel CLI 41.4.1
? Set up and deploy “~/Code/dailyai/pipecat-cloud/pipecat-cloud-daily-sip-pstn/vercel”? yes
? Which scope should contain your project? Daily
? Link to existing project? yes
? What’s the name of your existing project? pcc-dial-webhook-handler
🔗  Linked to daily-co/pcc-dial-webhook-handler (created .vercel)
🔍  Inspect: https://vercel.com/daily-co/pcc-dial-webhook-handler/xxx [2s]
✅  Preview: https://pcc-dial-webhook-handler-xxx-daily-co.vercel.app [2s]
📝  To deploy to production (pcc-dial-webhook-handler.vercel.app), run `vercel --prod`
```

## Security

- Per-phone-number HMAC signature validation for enhanced security
- Each phone number has its own HMAC secret (automatically synced from Daily)
- Environment variables for sensitive credentials
- Method validation (POST only for /dial)
- Automatic fallback to environment variable HMAC if phone-specific secret not found