import logging
import os
from datetime import datetime, timezone
from typing import List, Optional

logger = logging.getLogger("voiceguard")


ALERT_NUMBERS: List[str] = [
    "+918861480372",
    "+917760568702",
]


def _get_client() -> Optional[object]:
    """Lazily import and return a Twilio Client instance or None if unavailable.

    This avoids ImportError at module import time and allows the system to
    continue operating without SMS if Twilio isn't configured.
    """
    try:
        from twilio.rest import Client
    except Exception:
        logger.warning("[SMS] twilio library not installed; SMS disabled")
        return None

    sid = os.getenv("TWILIO_SID")
    token = os.getenv("TWILIO_AUTH_TOKEN")
    if not sid or not token:
        logger.warning("[SMS] Twilio credentials are not set; SMS disabled")
        return None

    try:
        return Client(sid, token)
    except Exception:
        logger.exception("[SMS] Failed to create Twilio client")
        return None


def send_sms_alert(
    risk_level: str,
    location: str,
    advice: str,
    posts_analyzed: int = 0,
    disaster_type: str = "Unknown",
) -> bool:
    """Send SMS alerts for MEDIUM/HIGH risk levels.

    Returns True if at least one message was successfully queued, False otherwise.
    """
    try:
        if (risk_level or "").upper() not in {"MEDIUM", "HIGH"}:
            logger.info("[SMS] Not sending SMS for risk_level=%s", risk_level)
            return False

        from_number = os.getenv("TWILIO_FROM")
        if not from_number:
            logger.error("[SMS] TWILIO_FROM not set; cannot send SMS")
            return False

        alert_numbers = os.getenv("ALERT_NUMBERS", "")
        if alert_numbers:
            numbers = [n.strip() for n in alert_numbers.split(",") if n.strip()]
        else:
            numbers = ALERT_NUMBERS

        ts = datetime.now(timezone.utc).isoformat()
        body = (
            f"VOICEGUARD ALERT — {location}\n"
            f"Risk: {risk_level}\n"
            f"Disaster: {disaster_type}\n"
            f"Action: {advice}\n"
            f"Time: {ts}\n"
            f"Posts detected: {posts_analyzed}"
        )

        client = _get_client()
        if client is None:
            logger.warning("[SMS] Twilio client unavailable; skipping SMS send")
            return False

        sent = 0
        for number in numbers:
            try:
                client.messages.create(to=number, from_=from_number, body=body)
                sent += 1
            except Exception:
                logger.exception("[SMS] Failed to send to %s", number)

        logger.info("[SMS] Sent to %d numbers (attempted %d)", sent, len(numbers))
        return sent > 0
    except Exception:
        logger.exception("[SMS] Unexpected error sending SMS")
        return False
