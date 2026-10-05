from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from starlette.concurrency import run_in_threadpool

from app.api.deps import get_current_active_superuser
from app.core.db import engine
from app.models import User
from app.webhooks.config import config
from app.webhooks.protocol import MAX_BODY, parse, verify
from app.webhooks.service import accept

router = APIRouter(prefix="/catalog-sync", tags=["catalog-sync"])
Operator = Annotated[User, Depends(get_current_active_superuser)]


async def authenticated_body(
    request: Request, secret: str, delivery_id: str = ""
) -> bytes:
    if (
        request.headers.get("content-type", "").split(";")[0].strip()
        != "application/json"
    ):
        raise HTTPException(415, "application/json required")
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > MAX_BODY:
            raise HTTPException(413, "Payload too large")
    try:
        verify(
            secret,
            request.headers.get("x-webhook-timestamp", ""),
            request.headers.get("x-webhook-signature", ""),
            bytes(data),
            delivery_id,
        )
    except ValueError:
        raise HTTPException(401, "Expired or invalid signature")
    return bytes(data)


@router.post("/events", status_code=202)
async def receive(request: Request) -> dict[str, str]:
    cfg = config()
    body = await authenticated_body(request, cfg.inbound_secret.get_secret_value())
    try:
        event = parse(body)
    except ValueError, UnicodeError:
        raise HTTPException(422, "Invalid catalog event")
    try:
        return await run_in_threadpool(accept, engine, cfg.owner_id, event)
    except OperationalError:
        raise HTTPException(
            503,
            "Storage unavailable; retry with same event ID",
            headers={"Retry-After": "5"},
        )


@router.get("/status")
def status(operator: Operator) -> dict:
    with engine.connect() as conn:
        counts = (
            conn.execute(
                text(
                    "SELECT state,count(*) AS count FROM webhook_outbox GROUP BY state"
                )
            )
            .mappings()
            .all()
        )
        events = (
            conn.execute(
                text("""SELECT o.id,o.event_id,i.external_id,i.version,i.outcome,
            o.state,o.attempts,o.last_error,o.available_at,o.lease_until,o.delivered_at
            FROM webhook_outbox o JOIN webhook_inbox i USING(event_id)
            ORDER BY o.created_at DESC LIMIT 100""")
            )
            .mappings()
            .all()
        )
        return {
            "counts": [dict(x) for x in counts],
            "deliveries": [dict(x) for x in events],
            "operator": str(operator.id),
        }


class Replay(BaseModel):
    reason: str = Field(min_length=10, max_length=500)


@router.post("/deliveries/{delivery_id}/replay")
def replay(delivery_id: UUID, request: Replay, operator: Operator) -> dict[str, str]:
    with engine.begin() as conn:
        row = conn.execute(
            text("SELECT state FROM webhook_outbox WHERE id=:id FOR UPDATE"),
            {"id": delivery_id},
        ).first()
        if not row:
            raise HTTPException(404, "Delivery not found")
        if row.state != "dead":
            raise HTTPException(409, "Only dead deliveries may be replayed")
        conn.execute(
            text("""UPDATE webhook_outbox SET state='pending',attempts=0,
            available_at=clock_timestamp(),lease_until=NULL,lease_token=NULL,last_error=NULL WHERE id=:id"""),
            {"id": delivery_id},
        )
        conn.execute(
            text("""INSERT INTO webhook_audit(outbox_id,action,actor,reason)
            VALUES (:id,'manual_replay',:actor,:reason)"""),
            {"id": delivery_id, "actor": str(operator.id), "reason": request.reason},
        )
    return {"id": str(delivery_id), "state": "pending"}
