"""Synthetic partner simulator, NOT a Shopify/CRM vendor integration.

Separate process + separate PostgreSQL schema. Persists receipts atomically with its
catalog projection. Failure controls only exist here, never in the upstream app.
"""

import asyncio
import os
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request, Response
from sqlalchemy import create_engine, text
from starlette.concurrency import run_in_threadpool

from app.webhooks.config import config
from app.webhooks.protocol import canonical, digest, parse
from app.webhooks.routes import authenticated_body

engine = create_engine(
    os.environ.get("RECEIVER_DATABASE_URL", os.environ["DATABASE_URL"]),
    pool_pre_ping=True,
)
app = FastAPI(title="Synthetic partner receipt contract")


def initialize() -> None:
    with engine.begin() as conn:
        conn.execute(
            text("""
        CREATE SCHEMA IF NOT EXISTS proof_receiver;
        CREATE TABLE IF NOT EXISTS proof_receiver.receipt (
            key uuid PRIMARY KEY, body_hash char(64) NOT NULL,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp()
        );
        CREATE TABLE IF NOT EXISTS proof_receiver.catalog (
            external_id varchar(80) PRIMARY KEY, version integer NOT NULL,
            payload jsonb NOT NULL, apply_count integer NOT NULL
        );
        CREATE TABLE IF NOT EXISTS proof_receiver.control (
            id integer PRIMARY KEY CHECK(id=1), mode text NOT NULL
        );
        INSERT INTO proof_receiver.control VALUES (1,'ok') ON CONFLICT DO NOTHING;
        """)
        )


def commit_receipt(key: UUID, body: bytes) -> bool:
    event = parse(body)
    body_hash = digest(canonical(event.model_dump()))
    with engine.begin() as conn:
        added = conn.execute(
            text("""INSERT INTO proof_receiver.receipt(key,body_hash)
            VALUES (:key,:hash) ON CONFLICT DO NOTHING RETURNING key"""),
            {"key": key, "hash": body_hash},
        ).first()
        if not added:
            old_hash = conn.execute(
                text("SELECT body_hash FROM proof_receiver.receipt WHERE key=:key"),
                {"key": key},
            ).scalar_one()
            if old_hash != body_hash:
                raise HTTPException(409, "Receipt key conflict")
            return False
        conn.execute(
            text("""INSERT INTO proof_receiver.catalog(external_id,version,payload,apply_count)
            VALUES (:id,:version,CAST(:payload AS jsonb),1)
            ON CONFLICT(external_id) DO UPDATE SET version=EXCLUDED.version,
            payload=EXCLUDED.payload,apply_count=proof_receiver.catalog.apply_count+1
            WHERE proof_receiver.catalog.version<EXCLUDED.version"""),
            {
                "id": event.external_id,
                "version": event.version,
                "payload": canonical(event.model_dump()).decode(),
            },
        )
    return True


@app.post("/catalog")
async def catalog(request: Request) -> Response:
    delivery_id = request.headers.get("idempotency-key", "")
    body = await authenticated_body(
        request, config().outbound_secret.get_secret_value(), delivery_id
    )
    try:
        key = UUID(request.headers.get("idempotency-key", ""))
        parse(body)
    except ValueError, UnicodeError:
        raise HTTPException(422, "Invalid delivery")
    with engine.connect() as conn:
        mode = conn.execute(
            text("SELECT mode FROM proof_receiver.control WHERE id=1")
        ).scalar_one()
    if mode == "unavailable":
        return Response(status_code=503, headers={"Retry-After": "1"})
    if mode == "reject":
        return Response(status_code=400)
    fresh = await run_in_threadpool(commit_receipt, key, body)
    if mode == "lose-response" and fresh:
        # Commit first, then delay beyond dispatcher timeout. Retry sees durable receipt.
        await asyncio.sleep(5)
    return Response(status_code=200, headers={"X-Receipt-Key": str(key)})


@app.get("/health")
def health() -> dict[str, str]:
    with engine.connect() as conn:
        conn.execute(text("SELECT 1 FROM proof_receiver.control"))
    return {"status": "ok", "kind": "synthetic_receiver"}


if __name__ == "__main__":
    import uvicorn

    initialize()
    uvicorn.run(app, host="127.0.0.1", port=8091)
