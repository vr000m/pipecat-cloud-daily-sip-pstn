import { logger } from '../../lib/utils'; 
import axios from 'axios';
import crypto from 'crypto';
import fs from 'fs';
import path from 'path';
import yaml from 'js-yaml';

// Load phone configuration
const loadPhoneConfig = () => {
  try {
    const configPath = path.join(process.cwd(), 'phone.yml');
    const fileContents = fs.readFileSync(configPath, 'utf8');
    return yaml.load(fileContents);
  } catch (error) {
    logger.error('Error loading phone.yml:', error);
    return null;
  }
};

// Cache the phone config at startup
const phoneConfig = loadPhoneConfig();

// Helper function to normalize phone numbers (remove spaces, dashes, etc.)
const normalizePhoneNumber = (phoneNumber) => {
  if (!phoneNumber) return null;
  // Remove all non-digit characters except the leading +
  return phoneNumber.replace(/[^\d+]/g, '');
};

// Determine environment based on phone number
const getEnvironmentForPhoneNumber = (phoneNumber) => {
  if (!phoneConfig || !phoneNumber) {
    logger.warn('Phone config not loaded or phone number not provided, defaulting to production');
    return 'prod';
  }

  const normalizedNumber = normalizePhoneNumber(phoneNumber);
  logger.debug(`Checking environment for normalized number: ${normalizedNumber}`);

  // Check each environment
  for (const [env, config] of Object.entries(phoneConfig)) {
    if (config.phone_numbers) {
      for (const phone of config.phone_numbers) {
        if (normalizePhoneNumber(phone.number) === normalizedNumber) {
          logger.info(`Phone number ${normalizedNumber} mapped to environment: ${env}`);
          return env;
        }
      }
    }
  }

  logger.warn(`Phone number ${normalizedNumber} not found in config, defaulting to production`);
  return 'prod';
};

// Get HMAC secret for a specific phone number
const getHmacSecretForPhoneNumber = (phoneNumber) => {
  if (!phoneConfig || !phoneNumber) {
    logger.debug('Using default HMAC secret from environment');
    return process.env.PINLESS_HMAC_SECRET;
  }

  const normalizedNumber = normalizePhoneNumber(phoneNumber);
  
  // Search through all environments for the phone number
  for (const [env, config] of Object.entries(phoneConfig)) {
    if (config.phone_numbers) {
      for (const phone of config.phone_numbers) {
        if (normalizePhoneNumber(phone.number) === normalizedNumber) {
          if (phone.hmac_secret) {
            logger.debug(`Using HMAC secret for phone number ${normalizedNumber}`);
            return phone.hmac_secret;
          }
          break;
        }
      }
    }
  }

  // Fall back to environment variable
  logger.debug('Phone-specific HMAC not found, using default from environment');
  return process.env.PINLESS_HMAC_SECRET;
};

const validateSignature = (body, signature, timestamp, secret) => {
  // Skip if any required fields are missing
  if (!signature || !timestamp || !secret) {
    logger.warn('Missing required fields for HMAC validation');
    return true;
  }

  try {
    const decodedSecret = Buffer.from(secret, 'base64');
    const hmac = crypto.createHmac('sha256', decodedSecret);
    const signatureData = `${timestamp}.${body}`;
    const computedSignature = hmac.update(signatureData).digest('base64');
    
    logger.debug('Signature validation:', {
      timestamp,
      signatureData: signatureData.substring(0, 50) + '...',
      computedSignature,
      receivedSignature: signature
    });
    
    return computedSignature === signature;
  } catch (error) {
    logger.error('Error validating signature:', error);
    return true; // Allow request to proceed on error
  }
};

export default async function handler(req, res) {
  // Only allow POST requests
  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  try {
    logger.info('Incoming request to /api/dial:');
    logger.info(`Headers: ${JSON.stringify(req.headers)}`);
    
    const rawBody = JSON.stringify(req.body);
    logger.info(`Raw body: ${rawBody}`);

    const signature = req.headers['x-pinless-signature'];
    const timestamp = req.headers['x-pinless-timestamp'];
    
    if (signature && timestamp) {
      logger.info('Validating HMAC signature');
      
      // Extract the 'To' field from the request body to determine which phone's HMAC to use
      const targetPhoneNumber = req.body.To || req.body.to;
      const hmacSecret = getHmacSecretForPhoneNumber(targetPhoneNumber);
      
      if (!hmacSecret) {
        logger.error('No HMAC secret found for validation');
        return res.status(401).json({ 
          error: 'Invalid configuration',
          message: 'No HMAC secret configured'
        });
      }
      
      if (!validateSignature(rawBody, signature, timestamp, hmacSecret)) {
        logger.error('Invalid HMAC signature', { 
          signature, 
          timestamp,
          phoneNumber: targetPhoneNumber 
        });
        return res.status(401).json({ 
          error: 'Invalid signature',
          message: 'Invalid HMAC signature'
        });
      }
      
      logger.info('HMAC signature validated successfully');
    } else {
      logger.info('Skipping HMAC validation - no signature headers present');
    }

    // Extract request data
    const {
      Test: test,
      To,
      From,
      callId,
      callDomain,
      dialout_settings,
      voicemail_detection,
      call_transfer,
      sipHeaders
    } = req.body;

    // Handle test requests when a webhook is configured
    if (test === 'test') {
      logger.debug('Test request received');
      return res.status(200).json({ status: 'success', message: 'Test request received' });
    }

    // Process dialin settings
    let dialin_settings = null;
    const requiredFields = ['To', 'From', 'callId', 'callDomain'];
    
    if (requiredFields.every(field => req.body[field] !== undefined && req.body[field] !== null)) {
      dialin_settings = {
        // snake_case because pipecat expects this format
        From,
        To,
        call_id: callId, 
        call_domain: callDomain,
      };
      logger.debug(`Populated dialin_settings from request: ${JSON.stringify(dialin_settings)}`);
    }

    // Set up Daily room properties
    const daily_room_properties = {
      enable_dialout: dialout_settings !== undefined && dialout_settings !== null,
      exp: Math.floor(Date.now() / 1000) + (5 * 60), // 5 minutes from now
    };

    // Configure SIP if dialin settings are provided
    if (dialin_settings !== null) {
      const sip_config = {
        display_name: From,
        sip_mode: 'dial-in',
        // num_endpoints: 1, // 1 for dial-in, 2 for transfer
        num_endpoints: (call_transfer !== undefined && call_transfer !== null) ? 2 : 1,
        // codecs: {"audio": [To === "+16502315623" ? "PCMU" : "OPUS"]},
      };
      daily_room_properties.sip = sip_config;
    }

    // Prepare payload for {service}/start API call
    const payload = {
      createDailyRoom: true,
      dailyRoomProperties: daily_room_properties,
      body: {
        dialin_settings,
        dialout_settings,
        voicemail_detection,
        call_transfer,
        sip_headers: sipHeaders,
      },
    };

    logger.debug(`Daily room properties: ${JSON.stringify(daily_room_properties)}`);

    // Determine environment based on phone number
    let targetPhoneNumber = null;
    let detectedEnvironment = 'prod';

    // For dial-in, use the 'To' field (the number being called)
    if (dialin_settings && dialin_settings.To) {
      targetPhoneNumber = dialin_settings.To;
      detectedEnvironment = getEnvironmentForPhoneNumber(targetPhoneNumber);
      logger.info(`Dial-in detected. Using 'To' number ${targetPhoneNumber} -> Environment: ${detectedEnvironment}`);
    }
    // For dial-out, use the 'From' field in dialout_settings (the caller ID)
    else if (dialout_settings && dialout_settings.length > 0) {
      // Look for a callerId in the first dialout setting
      const firstDialout = dialout_settings[0];
      if (firstDialout.callerId) {
        // The callerId might be a UUID, so we need to look it up in our config
        // For now, we'll check if any dialout_settings has a phoneNumber that matches our config
        for (const setting of dialout_settings) {
          if (setting.phoneNumber) {
            const env = getEnvironmentForPhoneNumber(setting.phoneNumber);
            if (env !== 'prod') {
              detectedEnvironment = env;
              targetPhoneNumber = setting.phoneNumber;
              break;
            }
          }
        }
      }
      logger.info(`Dial-out detected. Environment: ${detectedEnvironment}`);
    }

    // Get agent name and API configuration based on environment
    const agentName = process.env.AGENT_NAME || 'my-first-agent';
    let pccApiKey;
    let url;

    if (detectedEnvironment === 'staging') {
      pccApiKey = process.env.PIPECAT_CLOUD_API_KEY_STAGING;
      url = `https://staging.qa.pipecat.cloud/v1/public/${agentName}/start`;
      logger.info('Using STAGING environment configuration');
    } else {
      pccApiKey = process.env.PIPECAT_CLOUD_API_KEY_PROD;
      url = `https://api.pipecat.daily.co/v1/public/${agentName}/start`;
      logger.info('Using PRODUCTION environment configuration');
    }

    if (!pccApiKey) {
      throw new Error(`PIPECAT_CLOUD_API_KEY_${detectedEnvironment.toUpperCase()} env variable is not set`);
    }

    // Set up headers for Daily API call
    const headers = {
      'Authorization': `Bearer ${pccApiKey}`,
      'Content-Type': 'application/json',
    };

    logger.debug(`API URL: ${url}`);  
    logger.debug(`Headers: ${JSON.stringify(headers)}`);
    logger.debug(`Payload: ${JSON.stringify(payload)}`);
    
    try {
      const response = await axios.post(url, payload, { headers });
      logger.debug(`Response: ${JSON.stringify(response.data)}`);
      
      return res.status(200).json({
        status: 'success',
        data: response.data,
        room_properties: daily_room_properties,
      });
    } catch (error) {
      if (error.response) {
        // Pass through status code and error details from the Daily API
        const statusCode = error.response.status;
        const errorDetail = error.response.data || error.message;
        logger.error(`HTTP error: ${JSON.stringify(errorDetail)}`);
        return res.status(statusCode).json(errorDetail);
      } else {
        logger.error(`Request error: ${error.message}`);
        return res.status(500).json({ error: error.message });
      }
    }    
  } catch (error) {
    logger.error(`Unexpected error: ${error.message}`);
    return res.status(500).json({ error: 'Internal server error', message: error.message });
  }
}

// Configure body parser to preserve raw body text
export const config = {
  api: {
    bodyParser: {
      sizeLimit: '1mb',
    },
  },
};