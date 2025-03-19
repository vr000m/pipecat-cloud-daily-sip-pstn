import { logger } from '../../lib/utils';

export default function handler(req, res) {
  logger.info('Incoming request to /api/');
  
  return res.status(200).json({ message: 'Hello, World!' });
}
