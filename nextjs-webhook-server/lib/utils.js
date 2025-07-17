// File: vercel/lib/utils.js
import pino from 'pino';

export const logger = pino({
  level: process.env.LOG_LEVEL || 'debug',
  browser: {
    write: {
      info: (...args) => console.log(...args),
      error: (...args) => console.error(...args),
      debug: (...args) => console.debug(...args),
    }
  }
});