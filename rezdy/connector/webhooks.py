from __future__ import annotations

import hashlib
import hmac
import json
import logging
from typing import Any

from .schemas import RezdyBooking, RezdyWebhookPayload

logger = logging.getLogger(__name__)

KNOWN_EVENTS = {
    "order.created",
    "order.updated",
    "order.cancelled",
    "booking.created",
    "booking.updated",
    "booking.cancelled",
}


def compute_payload_hash(source: str, event_type: str, payload: dict[str, Any]) -> str:
    canonical = json.dumps({"source": source, "event_type": event_type, "payload": payload}, sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


def verify_signature(body: bytes, signature: str, secret: str) -> bool:
    """Verifica assinatura HMAC-SHA256 no header X-Rezdy-Signature ou similar."""
    if not secret:
        return True
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.lower().removeprefix("sha256="))


def parse_webhook(raw_body: bytes, secret: str | None = None, signature: str | None = None) -> RezdyWebhookPayload:
    if secret and signature:
        if not verify_signature(raw_body, signature, secret):
            raise ValueError("Invalid webhook signature")

    data = json.loads(raw_body)
    return RezdyWebhookPayload.model_validate(data)


def extract_booking(payload: RezdyWebhookPayload) -> RezdyBooking | None:
    return payload.booking
