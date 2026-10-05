"""Controlled local recording steps; synthetic database only, no resets."""

import sys

import httpx
from app.core.db import engine
from app.webhooks.config import config
from app.webhooks.protocol import canonical, headers
from app.webhooks.worker import run_once
from sqlalchemy import text

if not engine.url.database.endswith("_proof"):
    raise SystemExit("Use a disposable *_proof database")
step = sys.argv[1]
mode = {
    "happy": "ok",
    "duplicate": "ok",
    "lost": "lose-response",
    "reject": "reject",
    "recover": "ok",
}[step]
with engine.begin() as conn:
    conn.execute(
        text("UPDATE proof_receiver.control SET mode=:mode WHERE id=1"), {"mode": mode}
    )
with httpx.Client(timeout=0.3, trust_env=False) as client:
    if step != "recover":
        version = {"happy": 1, "duplicate": 1, "lost": 2, "reject": 3}[step]
        body = canonical(
            {
                "event_id": f"demo-{version}",
                "external_id": "desk-lamp",
                "version": version,
                "title": f"Desk lamp v{version}",
                "description": "Synthetic recording sample",
            }
        )
        response = client.post(
            "http://127.0.0.1:8090/api/v1/catalog-sync/events",
            content=body,
            headers=headers(config().inbound_secret.get_secret_value(), body),
            timeout=10,
        )
        response.raise_for_status()
    run_once(engine, config(), client)
with engine.connect() as conn:
    rows = (
        conn.execute(
            text("SELECT external_id,version,apply_count FROM proof_receiver.catalog")
        )
        .mappings()
        .all()
    )
print([dict(row) for row in rows])
