# Daily API Backend

This is a Next.js backend application that integrates with Daily's API for handling voice calls.

## Features

- API endpoint for handling Daily Pipecat requests
- HMAC signature validation
- Support for dialin and dialout settings
- Voicemail detection and call transfer functionality

## Setup

1. Clone the repository
2. Install dependencies:
   ```bash
   npm install
   ```
3. Create `.env.local` file with your credentials:
   ```
   PINLESS_HMAC_SECRET=your_hmac_secret
   DAILY_API_KEY=your_daily_api_key
   AGENT_NAME=my-first-agent
   ```
4. Run the development server:
   ```bash
   npm run dev
   ```

## API Endpoints

### GET /api
Returns a simple "Hello, World!" message to verify the server is running.

### POST /api/dial
Handles dialin and dialout requests for Daily Pipecat.

#### Request Body Format

The request body should contain the following fields:

```json
{
  "To": "+14152251493",
  "From": "+14158483432",
  "callId": "string-contains-uuid",
  "callDomain": "string-contains-uuid",
  "dialout_settings": [
    {"phoneNumber": "+14158483432", "callerId": "+14152251493"}, 
    {"sipUri": "sip:username@sip.hostname"}
  ],
  "voicemail_detection": {
    "testInPrebuilt": true
  },
  "call_transfer": {
    "mode": "dialout",
    "speakSummary": true,
    "storeSummary": true,
    "operatorNumber": "+14152250006",
    "testInPrebuilt": true
  }
}
```

## Deployment to Vercel

This application is designed to be deployed to Vercel:

1. Push your code to a Git repository
2. Connect the repository to Vercel
3. Add your environment variables in the Vercel dashboard
4. Deploy!

## Security

- HMAC signature validation for request authentication
- Environment variables for sensitive credentials
