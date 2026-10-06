import logging
import uuid

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlmodel import Session

from app.models import Item, User
from app.webhooks.protocol import CatalogEvent, canonical, digest

log = logging.getLogger("webhooks")


def accept(engine: Engine, owner_id: uuid.UUID, event: CatalogEvent) -> dict[str, str]:
    """Inbox + upstream Item + outbox commit together. No remote I/O in this transaction."""
    full_hash = digest(canonical(event.model_dump()))
    content_hash = digest(canonical(event.model_dump(exclude={"event_id"})))
    with Session(engine) as session, session.begin():
        # Raw SQL and ORM writes share this session's transaction/connection.
        conn = session.connection()
        conn.execute(text("SET LOCAL lock_timeout='3s'"))
        conn.execute(text("SET LOCAL statement_timeout='5s'"))
        # Serialize event identity first, then entity identity. Hash collisions only serialize.
        for key in ("event:" + event.event_id, "entity:" + event.external_id):
            conn.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": key},
            )
        previous = (
            conn.execute(
                text("SELECT * FROM webhook_inbox WHERE event_id=:id"),
                {"id": event.event_id},
            )
            .mappings()
            .first()
        )
        if previous:
            if previous["body_hash"] != full_hash:
                raise HTTPException(409, "Event ID reused with different content")
            return {
                "event_id": event.event_id,
                "outcome": previous["outcome"],
                "receipt": "duplicate",
            }
        owner = session.get(User, owner_id)
        if not owner or not owner.is_active:
            raise HTTPException(503, "Integration owner unavailable")
        current = (
            conn.execute(
                text("SELECT * FROM webhook_entity WHERE external_id=:id FOR UPDATE"),
                {"id": event.external_id},
            )
            .mappings()
            .first()
        )
        outcome = "applied"
        if current and event.version < current["version"]:
            outcome = "stale"
        elif current and event.version == current["version"]:
            if current["content_hash"] != content_hash:
                raise HTTPException(409, "Entity version reused with different content")
            outcome = "unchanged"
        if outcome == "applied":
            item = session.get(Item, current["item_id"]) if current else None
            if item is not None and item.owner_id != owner_id:
                raise HTTPException(
                    409, "Managed item owner changed; operator review required"
                )
            if item is None:
                item = Item(
                    title=event.title, description=event.description, owner_id=owner_id
                )
            item.title, item.description = event.title, event.description
            session.add(item)
            session.flush()
            conn.execute(
                text("""
                INSERT INTO webhook_entity(external_id,item_id,version,content_hash)
                VALUES (:id,:item,:version,:hash) ON CONFLICT (external_id) DO UPDATE
                SET version=EXCLUDED.version, content_hash=EXCLUDED.content_hash
            """),
                {
                    "id": event.external_id,
                    "item": item.id,
                    "version": event.version,
                    "hash": content_hash,
                },
            )
        conn.execute(
            text("""
            INSERT INTO webhook_inbox(event_id,external_id,version,body_hash,outcome)
            VALUES (:event,:entity,:version,:hash,:outcome)
        """),
            {
                "event": event.event_id,
                "entity": event.external_id,
                "version": event.version,
                "hash": full_hash,
                "outcome": outcome,
            },
        )
        if outcome == "applied":
            conn.execute(
                text("""
                INSERT INTO webhook_outbox(id,event_id,payload) VALUES (:id,:event,CAST(:payload AS jsonb))
            """),
                {
                    "id": uuid.uuid4(),
                    "event": event.event_id,
                    "payload": canonical(event.model_dump()).decode(),
                },
            )
    log.info("catalog_accept event_id=%s outcome=%s", event.event_id, outcome)
    return {"event_id": event.event_id, "outcome": outcome, "receipt": "new"}
