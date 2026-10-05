"""Postgres-backed at-least-once dispatcher. Destination must durably deduplicate receipts."""

import logging
import random
import time
import uuid
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.webhooks.config import WebhookSettings, config
from app.webhooks.protocol import canonical, headers

log = logging.getLogger("webhooks")


def claim(engine: Engine, cfg: WebhookSettings) -> dict[str, Any] | None:
    with engine.begin() as conn:
        # Exhausted crashed leases are terminal too; never spin forever after crashes.
        conn.execute(
            text("""
            WITH exhausted AS (UPDATE webhook_outbox SET state='dead',lease_token=NULL,lease_until=NULL,
                last_error='lease_expired_budget_exhausted'
            WHERE state='delivering' AND lease_until<=clock_timestamp() AND attempts>=:max
            RETURNING id)
            INSERT INTO webhook_audit(outbox_id,action,actor,reason)
                SELECT id,'dead','worker','lease_expired_budget_exhausted' FROM exhausted
        """),
            {"max": cfg.max_attempts},
        )
        row = conn.execute(
            text("""
            SELECT id FROM webhook_outbox
            WHERE attempts<:max AND (
                (state IN ('pending','retry') AND available_at<=clock_timestamp()) OR
                (state='delivering' AND lease_until<=clock_timestamp()))
            ORDER BY created_at,id FOR UPDATE SKIP LOCKED LIMIT 1
        """),
            {"max": cfg.max_attempts},
        ).first()
        if not row:
            return None
        result = (
            conn.execute(
                text("""
            UPDATE webhook_outbox SET state='delivering',attempts=attempts+1,
                lease_token=:token,lease_until=clock_timestamp()+make_interval(secs=>:lease)
            WHERE id=:id RETURNING *
        """),
                {"id": row.id, "token": uuid.uuid4(), "lease": cfg.lease_seconds},
            )
            .mappings()
            .one()
        )
        job = dict(result)
        conn.execute(
            text("""INSERT INTO webhook_audit(outbox_id,action,actor,reason)
            VALUES (:id,'claimed','worker',:reason)"""),
            {
                "id": job["id"],
                "reason": f"attempt={job['attempts']} lease={job['lease_token']}",
            },
        )
        return job


def finish(
    engine: Engine,
    job: dict[str, Any],
    state: str,
    error: str | None = None,
    delay: float = 0,
) -> bool:
    with engine.begin() as conn:
        result = conn.execute(
            text("""
            UPDATE webhook_outbox SET state=:state,last_error=:error,lease_token=NULL,
                lease_until=NULL,available_at=clock_timestamp()+make_interval(secs=>:delay),
                delivered_at=CASE WHEN CAST(:state AS varchar)='delivered' THEN clock_timestamp() ELSE NULL END
            WHERE id=:id AND lease_token=:token AND state='delivering' RETURNING id
        """),
            {
                "state": state,
                "error": error,
                "delay": delay,
                "id": job["id"],
                "token": job["lease_token"],
            },
        )
        changed = result.first() is not None
        if changed:
            conn.execute(
                text("""INSERT INTO webhook_audit(outbox_id,action,actor,reason)
                VALUES (:id,:action,'worker',:reason)"""),
                {
                    "id": job["id"],
                    "action": state,
                    "reason": error or "destination_receipt_verified",
                },
            )
    log.info(
        "outbox_finish outbox_id=%s event_id=%s state=%s fenced=%s",
        job["id"],
        job["event_id"],
        state,
        not changed,
    )
    return changed


def dispatch(
    engine: Engine, cfg: WebhookSettings, job: dict[str, Any], client: httpx.Client
) -> None:
    body = canonical(job["payload"])
    request_headers = headers(
        cfg.outbound_secret.get_secret_value(), body, str(job["id"])
    )
    request_headers["Idempotency-Key"] = str(job["id"])
    error, retryable, retry_after = None, True, 0.0
    try:
        # No redirects, ambient proxy or client-supplied URL. Bound response memory.
        with client.stream(
            "POST", cfg.destination_url, content=body, headers=request_headers
        ) as response:
            if 200 <= response.status_code < 300:
                if response.headers.get("X-Receipt-Key") != str(job["id"]):
                    error = "missing_or_mismatched_receipt"
                else:
                    finish(engine, job, "delivered")
                    return
            else:
                error = f"http_{response.status_code}"
                retryable = (
                    response.status_code in {408, 429} or response.status_code >= 500
                )
                if response.status_code in {429, 503}:
                    try:
                        retry_after = min(
                            300.0,
                            max(0.0, float(response.headers.get("Retry-After", "0"))),
                        )
                    except ValueError:
                        pass
    except httpx.TransportError:
        # Never log a raw exception: it can contain destination URLs or headers.
        error = "transport_outcome_unknown"
    state = "retry" if retryable and job["attempts"] < cfg.max_attempts else "dead"
    delay = max(retry_after, random.uniform(1, min(60, 2 ** job["attempts"])))
    finish(engine, job, state, error, delay)


def run_once(engine: Engine, cfg: WebhookSettings, client: httpx.Client) -> bool:
    job = claim(engine, cfg)
    if job is None:
        return False
    dispatch(engine, cfg, job, client)
    return True


def main() -> None:
    from app.core.db import engine

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    cfg = config()
    with httpx.Client(
        timeout=httpx.Timeout(3), follow_redirects=False, trust_env=False
    ) as client:
        while True:
            try:
                worked = run_once(engine, cfg, client)
            except Exception:
                log.error(
                    "worker_iteration_failed; lease will recover; inspect DB availability"
                )
                worked = False
            if not worked:
                time.sleep(1)


if __name__ == "__main__":
    main()
