#
# Copyright (c) 2025, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

"""HMAC signature validation for Daily pinless dial-in webhooks."""

import base64
import hmac
from typing import Optional

from loguru import logger


def validate_hmac_signature(
    secret: Optional[str],
    timestamp: Optional[str],
    body: str,
    signature: Optional[str],
) -> bool:
    """Validate HMAC signature for Daily webhook requests.

    Args:
        secret: Base64-encoded HMAC secret (from PINLESS_HMAC_SECRET env var)
        timestamp: Request timestamp (from x-pinless-timestamp header)
        body: Raw request body as string
        signature: Request signature (from x-pinless-signature header)

    Returns:
        True if signature is valid or validation is skipped, False if invalid
    """
    if not secret:
        logger.debug("Skipping HMAC validation - secret not set")
        return True

    if not timestamp or not signature:
        logger.debug("Skipping HMAC validation - no signature headers present")
        return True

    message = f"{timestamp}.{body}"

    try:
        base64_decoded_secret = base64.b64decode(secret)
        computed_signature = base64.b64encode(
            hmac.new(base64_decoded_secret, message.encode(), "sha256").digest()
        ).decode()

        if computed_signature != signature:
            logger.error(f"Invalid signature. Expected {signature}, got {computed_signature}")
            return False

        return True
    except Exception as e:
        logger.error(f"HMAC validation error: {e}")
        return False
