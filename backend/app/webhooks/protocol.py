import hashlib
import hmac
import json
import re
import time
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

MAX_BODY = 65536


class CatalogEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    event_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    external_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    version: int = Field(ge=1, le=2147483647)
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=255)


def canonical(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()


def digest(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def signature(secret: str, timestamp: str, body: bytes, delivery_id: str = "") -> str:
    signed = timestamp.encode() + b"."
    if delivery_id:
        signed += delivery_id.encode() + b"."
    return hmac.new(secret.encode(), signed + body, hashlib.sha256).hexdigest()


def headers(secret: str, body: bytes, delivery_id: str = "") -> dict[str, str]:
    stamp = str(int(time.time()))
    return {
        "Content-Type": "application/json",
        "X-Webhook-Timestamp": stamp,
        "X-Webhook-Signature": signature(secret, stamp, body, delivery_id),
    }


def verify(
    secret: str, stamp: str, supplied: str, body: bytes, delivery_id: str = ""
) -> None:
    if not re.fullmatch(r"[0-9]{1,12}", stamp) or abs(time.time() - int(stamp)) > 300:
        raise ValueError("Expired or invalid signature")
    if not re.fullmatch(r"[0-9a-f]{64}", supplied) or not hmac.compare_digest(
        signature(secret, stamp, body, delivery_id), supplied
    ):
        raise ValueError("Expired or invalid signature")


def parse(body: bytes) -> CatalogEvent:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        obj: dict[str, Any] = {}
        for key, value in pairs:
            if key in obj:
                raise ValueError("Duplicate JSON key")
            obj[key] = value
        return obj

    return CatalogEvent.model_validate(json.loads(body, object_pairs_hook=unique))
