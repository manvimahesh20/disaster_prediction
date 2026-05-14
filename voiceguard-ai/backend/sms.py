import logging
import os
from typing import List

from twilio.rest import Client

logger = logging.getLogger("voiceguard")

ALERT_NUMBERS: List[str] = [
    "+918861480372",
    "+917760568702"
]


def _get_client() -> Client:
    sid = os.getenv("TWILIO_SID")
    token = os.getenv("TWILIO_AUTH_TOKEN")
    if not sid or not token:
        raise ValueError("Twilio credentials are not set")
    return Client(sid, token)


def send_sms_alert(risk_level: str, location: str, advice: str) -> bool:
    if risk_level not in {"MEDIUM", "HIGH"}:
        return False

    from_number = os.getenv("TWILIO_FROM")
    if not from_number:
        logger.error("TWILIO_FROM not set")
        return False

    alert_numbers = os.getenv("ALERT_NUMBERS", "")
    if alert_numbers:
        numbers = [n.strip() for n in alert_numbers.split(",") if n.strip()]
    else:
        numbers = ALERT_NUMBERS

    body = f"VoiceGuard AI Alert: {risk_level} risk in {location}. Advice: {advice}"
    try:
        client = _get_client()
        for number in numbers:
            client.messages.create(to=number, from_=from_number, body=body)
        return True
    except Exception:
        logger.exception("Failed to send SMS alert")
        return False
