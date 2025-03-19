import crypto from 'crypto';

/**
 * Validate the HMAC signature from request headers
 * @param {string} signature - The signature from x-pinless-signature header
 * @param {string} timestamp - The timestamp from x-pinless-timestamp header
 * @param {string} body - The raw request body
 * @returns {boolean} - Whether the signature is valid
 */
export function validateSignature(signature, timestamp, body) {
  if (!process.env.PINLESS_HMAC_SECRET || !signature || !timestamp) {
    return false;
  }

  const signatureData = `${timestamp}.${body}`;
  const decodedSecret = Buffer.from(process.env.PINLESS_HMAC_SECRET, 'base64');
  
  const computedSignature = crypto
    .createHmac('sha256', decodedSecret)
    .update(signatureData)
    .digest('base64');

  return computedSignature === signature;
}

/**
 * Logger utility (simplified version of loguru)
 */
export const logger = {
  debug: (message) => console.debug(message),
  info: (message) => console.info(message),
  error: (message) => console.error(message),
};
