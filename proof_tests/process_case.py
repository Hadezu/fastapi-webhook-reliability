"""Intentional hard-crash probes, only used by tests in a disposable database."""

import os
import sys

import httpx
from app.core.db import engine
from app.webhooks.config import config
from app.webhooks.protocol import CatalogEvent, canonical, headers
from app.webhooks.service import accept
from app.webhooks.worker import claim
from sqlalchemy import event as sql_event

cfg = config()
if sys.argv[1] == "before-commit":

    @sql_event.listens_for(engine, "before_cursor_execute")
    def crash(conn, cursor, statement, parameters, context, executemany):
        if "INSERT INTO webhook_outbox" in statement:
            os._exit(66)

    accept(
        engine,
        cfg.owner_id,
        CatalogEvent(
            event_id="crash", external_id="product", version=1, title="Before crash"
        ),
    )
elif sys.argv[1] == "after-partner-commit":
    job = claim(engine, cfg)
    assert job is not None
    body = canonical(job["payload"])
    head = headers(cfg.outbound_secret.get_secret_value(), body, str(job["id"]))
    head["Idempotency-Key"] = str(job["id"])
    response = httpx.post(
        cfg.destination_url, content=body, headers=head, trust_env=False
    )
    assert response.status_code == 200
    os._exit(67)
else:
    raise ValueError("Unknown test probe")
