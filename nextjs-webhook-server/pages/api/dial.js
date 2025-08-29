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

// Helper function to normalize phone numbers (remove spaces, dashes, convert letters to numbers)
const normalizePhoneNumber = (phoneNumber) => {
  if (!phoneNumber) return null;
  
  // Phone keypad letter to number mapping
  const letterToNumber = {
    'a': '2', 'b': '2', 'c': '2',
    'd': '3', 'e': '3', 'f': '3',
    'g': '4', 'h': '4', 'i': '4',
    'j': '5', 'k': '5', 'l': '5',
    'm': '6', 'n': '6', 'o': '6',
    'p': '7', 'q': '7', 'r': '7', 's': '7',
    't': '8', 'u': '8', 'v': '8',
    'w': '9', 'x': '9', 'y': '9', 'z': '9'
  };
  
  // Check if starts with +
  const hasPlus = phoneNumber.charAt(0) === '+';
  
  // Convert letters to numbers and keep only digits
  let normalized = '';
  const lowercased = phoneNumber.toLowerCase();
  
  for (let i = 0; i < lowercased.length; i++) {
    const char = lowercased[i];
    if (letterToNumber[char]) {
      // Convert letter to corresponding number
      normalized += letterToNumber[char];
    } else if (/\d/.test(char)) {
      // Keep digits
      normalized += char;
    }
    // Skip all other characters (spaces, dashes, parentheses, etc.)
  }
  
  // Add back the + if it was there originally
  return hasPlus ? '+' + normalized : normalized;
};

// Helper function to normalize SIP URIs for comparison
const normalizeSipUri = (sipUri) => {
  if (!sipUri) return null;
  
  let normalized = sipUri;
  
  // Remove sip: prefix if present (case-insensitive)
  if (normalized.toLowerCase().startsWith('sip:')) {
    normalized = normalized.substring(4);
  }
  
  // Remove port number (e.g., :5060)
  normalized = normalized.replace(/:\d+/, '');
  
  // Remove query parameters (everything after ?)
  const queryIndex = normalized.indexOf('?');
  if (queryIndex !== -1) {
    normalized = normalized.substring(0, queryIndex);
  }
  
  // Remove URI parameters (everything after ;)
  const paramIndex = normalized.indexOf(';');
  if (paramIndex !== -1) {
    normalized = normalized.substring(0, paramIndex);
  }
  
  // Convert to lowercase for case-insensitive comparison
  normalized = normalized.toLowerCase().trim();
  
  logger.debug(`Normalized SIP URI: ${sipUri} -> ${normalized}`);
  return normalized;
};

// Helper function to look up phone configuration by purchased phone ID (UUID)
const getPhoneConfigById = (purchasedPhoneId) => {
  if (!phoneConfig || !purchasedPhoneId) return null;
  
  for (const [env, config] of Object.entries(phoneConfig)) {
    if (config.phone_numbers) {
      for (const phone of config.phone_numbers) {
        // Check purchased_phone_id first (new field), fallback to id for backward compatibility
        if (phone.purchased_phone_id === purchasedPhoneId || phone.id === purchasedPhoneId) {
          return { ...phone, environment: env };
        }
      }
    }
  }
  return null;
};

// Determine environment based on phone number or SIP URI
const getEnvironmentForDialIdentifier = (identifier) => {
  if (!phoneConfig || !identifier) {
    logger.warn('Phone config not loaded or identifier not provided, defaulting to production');
    return 'prod';
  }

  // Check if identifier is a SIP URI (contains @ or starts with sip:)
  const isSipUri = identifier.includes('@') || identifier.startsWith('sip:');
  
  if (isSipUri) {
    logger.debug(`Checking environment for SIP URI: ${identifier}`);
    const normalizedInputSip = normalizeSipUri(identifier);
    
    // Check each environment for matching SIP URI
    for (const [env, config] of Object.entries(phoneConfig)) {
      if (config.phone_numbers) {
        for (const phone of config.phone_numbers) {
          if (phone.sip_uri) {
            const normalizedStoredSip = normalizeSipUri(phone.sip_uri);
            if (normalizedStoredSip === normalizedInputSip) {
              logger.info(`SIP URI ${identifier} matched to ${phone.sip_uri} -> Environment: ${env}`);
              return env;
            }
          }
        }
      }
    }
    logger.warn(`SIP URI ${identifier} not found in config, defaulting to production`);
  } else {
    // Handle as phone number
    const normalizedNumber = normalizePhoneNumber(identifier);
    logger.debug(`Checking environment for normalized number: ${normalizedNumber}`);

    // Check each environment for matching phone number
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
  }

  return 'prod';
};

// Get HMAC secret for a specific phone number or SIP URI
const getHmacSecretForIdentifier = (identifier) => {
  if (!phoneConfig || !identifier) {
    logger.debug('Using default HMAC secret from environment');
    return process.env.PINLESS_HMAC_SECRET;
  }

  // Check if identifier is a SIP URI
  const isSipUri = identifier.includes('@') || identifier.startsWith('sip:');
  
  if (isSipUri) {
    logger.debug(`Looking for HMAC secret for SIP URI: ${identifier}`);
    const normalizedInputSip = normalizeSipUri(identifier);
    
    // Search through all environments for the SIP URI
    for (const [env, config] of Object.entries(phoneConfig)) {
      if (config.phone_numbers) {
        for (const phone of config.phone_numbers) {
          if (phone.sip_uri) {
            const normalizedStoredSip = normalizeSipUri(phone.sip_uri);
            if (normalizedStoredSip === normalizedInputSip) {
              if (phone.hmac_secret) {
                logger.debug(`Using HMAC secret for SIP URI ${identifier} (matched to ${phone.sip_uri})`);
                return phone.hmac_secret;
              }
              break;
            }
          }
        }
      }
    }
    logger.debug('SIP URI-specific HMAC not found, using default from environment');
  } else {
    // Handle as phone number
    const normalizedNumber = normalizePhoneNumber(identifier);
    
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
    logger.debug('Phone-specific HMAC not found, using default from environment');
  }

  // Fall back to environment variable
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
      // This could be either a phone number or a SIP URI
      const targetIdentifier = req.body.To || req.body.to;
      const hmacSecret = getHmacSecretForIdentifier(targetIdentifier);
      
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
          identifier: targetIdentifier 
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

    // Determine environment based on phone number or SIP URI
    let targetIdentifier = null;
    let detectedEnvironment = 'prod';

    // For dial-in, use the 'To' field (could be phone number or SIP URI)
    if (dialin_settings && dialin_settings.To) {
      targetIdentifier = dialin_settings.To;
      detectedEnvironment = getEnvironmentForDialIdentifier(targetIdentifier);
      const identifierType = targetIdentifier.includes('@') || targetIdentifier.startsWith('sip:') ? 'SIP URI' : 'phone number';
      logger.info(`Dial-in detected. Using 'To' ${identifierType}: ${targetIdentifier} -> Environment: ${detectedEnvironment}`);
    }
    // For dial-out, use the callerId to determine environment
    else if (dialout_settings && dialout_settings.length > 0) {
      const firstDialout = dialout_settings[0];
      
      // Validate that dialout_settings has a valid target (phoneNumber or sipUri)
      if (!firstDialout.phoneNumber && !firstDialout.sipUri) {
        logger.error('Dial-out settings provided but no phoneNumber or sipUri specified');
        return res.status(400).json({
          error: 'Invalid dialout_settings',
          message: 'dialout_settings must contain either phoneNumber or sipUri'
        });
      }
      
      if (firstDialout.callerId) {
        // Reject if callerId is a phone number instead of UUID
        if (firstDialout.callerId.match(/^\+?\d+$/)) {
          logger.error(`Dial-out rejected. callerId ${firstDialout.callerId} appears to be a phone number, but should be a UUID`);
          return res.status(400).json({ 
            error: 'Invalid callerId',
            message: 'callerId should be a UUID, not a phone number'
          });
        }
        
        // Look up callerId UUID in our phone config
        const phoneConfigResult = getPhoneConfigById(firstDialout.callerId);
        
        if (phoneConfigResult) {
          // Found phone config by UUID - use that environment
          detectedEnvironment = phoneConfigResult.environment;
          targetIdentifier = phoneConfigResult.number;
          logger.info(`Dial-out detected. Found callerId UUID ${firstDialout.callerId} -> ${phoneConfigResult.number} in ${detectedEnvironment}`);
        } else {
          // callerId UUID not found in config - default to prod
          detectedEnvironment = 'prod';
          logger.info(`Dial-out detected. callerId UUID ${firstDialout.callerId} not found in config, defaulting to prod environment`);
        }
      } else {
        // No callerId provided - default to prod
        detectedEnvironment = 'prod';
        logger.info('Dial-out detected. No callerId provided, defaulting to prod environment');
      }
      logger.info(`Dial-out detected. Final environment: ${detectedEnvironment}`);
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