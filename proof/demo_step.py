"""Controlled local recording steps; synthetic database only, no resets."""

import os
import sys
import time

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
            os.environ.get("PROOF_API_URL", "http://127.0.0.1:8090")
            + "/api/v1/catalog-sync/events",
            content=body,
            headers=headers(config().inbound_secret.get_secret_value(), body),
            timeout=10,
        )
        response.raise_for_status()
    # Honour the real retry deadline; do not rewrite state to make a demo pass.
    deadline = time.monotonic() + 10
    while not run_once(engine, config(), client):
        if step != "recover":
            break
        if time.monotonic() >= deadline:
            raise RuntimeError("No recoverable delivery became due")
        time.sleep(0.1)
with engine.connect() as conn:
    rows = (
        conn.execute(
            text("SELECT external_id,version,apply_count FROM proof_receiver.catalog")
        )
        .mappings()
        .all()
    )
print([dict(row) for row in rows])
expected = {"happy": (1, 1), "duplicate": (1, 1), "lost": (2, 2), "reject": (2, 2)}
lamp = next(row for row in rows if row["external_id"] == "desk-lamp")
if step in expected:
    assert (lamp["version"], lamp["apply_count"]) == expected[step]
if step == "recover":
    assert lamp["version"] == lamp["apply_count"]
    assert lamp["version"] in {2, 3}
    with engine.connect() as conn:
        assert (
            conn.execute(
                text(
                    "SELECT count(*) FROM webhook_outbox WHERE event_id LIKE 'demo-%' AND state <> 'delivered'"
                )
            ).scalar_one()
            == 0
        )
        if lamp["version"] == 3:
            assert (
                conn.execute(
                    text(
                        "SELECT count(*) FROM webhook_audit WHERE action='manual_replay' AND reason=:reason"
                    ),
                    {
                        "reason": "Inspected partner rejection and corrected test configuration"
                    },
                ).scalar_one()
                == 1
            )
