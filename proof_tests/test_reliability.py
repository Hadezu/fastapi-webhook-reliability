import json
import os
import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pytest
from app.core.config import settings
from app.core.db import engine
from app.core.security import get_password_hash
from app.main import app
from app.models import Item, User
from app.webhooks.config import config
from app.webhooks.protocol import canonical, headers, signature
from app.webhooks.worker import claim, dispatch, finish, run_once
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlmodel import Session, select

URL = "/api/v1/catalog-sync"


def payload(**changes):
    return {
        "event_id": "event-1",
        "external_id": "sku-1",
        "version": 1,
        "title": "Desk lamp",
        "description": "Synthetic catalog",
        **changes,
    }


def send(value=None, raw=None, head=None):
    body = raw if raw is not None else canonical(value or payload())
    signed = headers(config().inbound_secret.get_secret_value(), body)
    if head:
        signed.update(head)
    with TestClient(app) as client:
        return client.post(URL + "/events", content=body, headers=signed)


def scalar(sql, params=None):
    with engine.connect() as conn:
        return conn.execute(text(sql), params or {}).scalar_one()


def execute(sql, params=None):
    with engine.begin() as conn:
        conn.execute(text(sql), params or {})


def state():
    return scalar("SELECT state FROM webhook_outbox")


def due():
    execute(
        "UPDATE webhook_outbox SET available_at=clock_timestamp()-interval '1 second',lease_until=clock_timestamp()-interval '1 second'"
    )


def operator_headers():
    with TestClient(app) as client:
        token = client.post(
            "/api/v1/login/access-token",
            data={
                "username": settings.FIRST_SUPERUSER,
                "password": settings.FIRST_SUPERUSER_PASSWORD,
            },
        ).json()["access_token"]
    return {"Authorization": "Bearer " + token}


def test_happy_path_changes_upstream_item_and_partner(http_client):
    assert send().status_code == 202
    with Session(engine) as session:
        item = session.exec(select(Item)).one()
        assert item.title == "Desk lamp" and item.owner_id == config().owner_id
    assert run_once(engine, config(), http_client)
    assert state() == "delivered"
    assert scalar("SELECT apply_count FROM proof_receiver.catalog") == 1
    with TestClient(app) as client:
        visible = client.get("/api/v1/items/", headers=operator_headers())
        assert visible.status_code == 200 and visible.json()["count"] == 1


def test_24_concurrent_duplicates_create_one_effect(http_client):
    with ThreadPoolExecutor(max_workers=12) as pool:
        responses = list(pool.map(lambda _: send(), range(24)))
    assert all(r.status_code == 202 for r in responses)
    assert sum(r.json()["receipt"] == "new" for r in responses) == 1
    assert scalar("SELECT count(*) FROM item") == 1
    assert scalar("SELECT count(*) FROM webhook_inbox") == 1
    assert scalar("SELECT count(*) FROM webhook_outbox") == 1
    run_once(engine, config(), http_client)
    assert scalar("SELECT apply_count FROM proof_receiver.catalog") == 1


def test_semantically_equal_json_retry_is_duplicate():
    assert send().status_code == 202
    assert (
        send(raw=json.dumps(payload(), indent=4).encode()).json()["receipt"]
        == "duplicate"
    )


def test_conflicting_event_id_rolls_back():
    assert send().status_code == 202
    assert send(payload(title="Different")).status_code == 409
    assert scalar("SELECT title FROM item") == "Desk lamp"
    assert scalar("SELECT count(*) FROM webhook_inbox") == 1


def test_version_order_and_conflicts():
    assert send(payload(event_id="v2", version=2)).json()["outcome"] == "applied"
    assert (
        send(payload(event_id="v1", version=1, title="Old")).json()["outcome"]
        == "stale"
    )
    assert send(payload(event_id="same", version=2)).json()["outcome"] == "unchanged"
    assert (
        send(payload(event_id="conflict", version=2, title="Conflict")).status_code
        == 409
    )
    assert scalar("SELECT title FROM item") == "Desk lamp"
    assert scalar("SELECT count(*) FROM webhook_outbox") == 1


def test_concurrent_versions_converge():
    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(
            pool.map(
                lambda n: send(payload(event_id=f"v{n}", version=n, title=f"v{n}")),
                range(1, 21),
            )
        )
    assert all(r.status_code == 202 for r in results)
    assert scalar("SELECT version FROM webhook_entity") == 20
    assert scalar("SELECT title FROM item") == "v20"


@pytest.mark.parametrize("offset", [-301, 301])
def test_old_and_future_signed_requests_rejected(offset):
    body = canonical(payload())
    stamp = str(int(time.time()) + offset)
    assert (
        send(
            raw=body,
            head={
                "X-Webhook-Timestamp": stamp,
                "X-Webhook-Signature": signature(
                    config().inbound_secret.get_secret_value(), stamp, body
                ),
            },
        ).status_code
        == 401
    )
    assert scalar("SELECT count(*) FROM webhook_inbox") == 0


@pytest.mark.parametrize(
    "change",
    [
        {"X-Webhook-Signature": "0" * 64},
        {"X-Webhook-Timestamp": "abc"},
        {"X-Webhook-Signature": "bad"},
    ],
)
def test_bad_auth_has_no_effect(change):
    assert send(head=change).status_code == 401
    assert scalar("SELECT count(*) FROM item") == 0


@pytest.mark.parametrize(
    "value",
    [
        payload(version=True),
        payload(version="1"),
        payload(owner_id=str(uuid.uuid4())),
        payload(version=0),
        payload(external_id="../../secret"),
        payload(title="x" * 256),
    ],
)
def test_invalid_schema_has_no_effect(value):
    assert send(value).status_code == 422
    assert scalar("SELECT count(*) FROM item") == 0


def test_body_limits_and_duplicate_keys():
    assert send(raw=b"x" * 65537).status_code == 413
    assert send(raw=b'{"event_id":"a","event_id":"b"}').status_code == 422
    assert send(raw=b"\xff").status_code == 422
    assert send(head={"Content-Type": "text/plain"}).status_code == 415


def test_inactive_owner_blocks_new_events():
    execute('UPDATE "user" SET is_active=false WHERE id=:id', {"id": config().owner_id})
    try:
        assert send().status_code == 503
        assert scalar("SELECT count(*) FROM webhook_inbox") == 0
    finally:
        execute(
            'UPDATE "user" SET is_active=true WHERE id=:id', {"id": config().owner_id}
        )


def test_upstream_ownership_is_preserved():
    send()
    with Session(engine) as session:
        user = User(
            email="outsider@example.com",
            hashed_password=get_password_hash("test-password-001"),
        )
        existing = session.exec(select(User).where(User.email == user.email)).first()
        if not existing:
            session.add(user)
            session.commit()
    with TestClient(app) as client:
        token = client.post(
            "/api/v1/login/access-token",
            data={"username": "outsider@example.com", "password": "test-password-001"},
        ).json()["access_token"]
        head = {"Authorization": "Bearer " + token}
        assert client.get("/api/v1/items/", headers=head).json()["count"] == 0
        assert client.get(URL + "/status", headers=head).status_code == 403
        assert (
            client.post(
                URL + "/deliveries/" + str(uuid.uuid4()) + "/replay",
                json={"reason": "Attempt unauthorized replay"},
                headers=head,
            ).status_code
            == 403
        )


def test_operator_endpoints_require_auth():
    with TestClient(app) as client:
        assert client.get(URL + "/status").status_code == 401
        assert (
            client.post(
                URL + "/deliveries/" + str(uuid.uuid4()) + "/replay",
                json={"reason": "unauthorized replay"},
            ).status_code
            == 401
        )


def test_503_retries_then_recovers(http_client):
    send()
    execute("UPDATE proof_receiver.control SET mode='unavailable'")
    run_once(engine, config(), http_client)
    assert state() == "retry"
    assert scalar("SELECT count(*) FROM proof_receiver.receipt") == 0
    execute("UPDATE proof_receiver.control SET mode='ok'")
    due()
    run_once(engine, config(), http_client)
    assert state() == "delivered"


def test_lost_response_does_not_repeat_partner_effect(http_client):
    send()
    execute("UPDATE proof_receiver.control SET mode='lose-response'")
    run_once(engine, config(), http_client)
    assert state() == "retry"
    assert scalar("SELECT apply_count FROM proof_receiver.catalog") == 1
    due()
    run_once(engine, config(), http_client)
    assert state() == "delivered"
    assert scalar("SELECT apply_count FROM proof_receiver.catalog") == 1
    assert scalar("SELECT count(*) FROM proof_receiver.receipt") == 1


def test_permanent_failure_requires_audited_operator_replay(http_client):
    send()
    execute("UPDATE proof_receiver.control SET mode='reject'")
    run_once(engine, config(), http_client)
    assert state() == "dead"
    identity = str(scalar("SELECT id FROM webhook_outbox"))
    with TestClient(app) as client:
        endpoint = URL + f"/deliveries/{identity}/replay"
        assert (
            client.post(
                endpoint, json={"reason": "x"}, headers=operator_headers()
            ).status_code
            == 422
        )
        assert (
            client.post(
                endpoint,
                json={"reason": "Corrected partner configuration"},
                headers=operator_headers(),
            ).status_code
            == 200
        )
        assert (
            client.post(
                endpoint,
                json={"reason": "Must not replay active work"},
                headers=operator_headers(),
            ).status_code
            == 409
        )
    execute("UPDATE proof_receiver.control SET mode='ok'")
    run_once(engine, config(), http_client)
    assert state() == "delivered"
    assert str(scalar("SELECT id FROM webhook_outbox")) == identity
    assert (
        scalar("SELECT count(*) FROM webhook_audit WHERE action='manual_replay'") == 1
    )


def test_retry_budget_is_bounded(http_client):
    send()
    execute("UPDATE proof_receiver.control SET mode='unavailable'")
    for _ in range(config().max_attempts):
        due()
        assert run_once(engine, config(), http_client)
    assert state() == "dead"
    assert not run_once(engine, config(), http_client)


def test_parallel_workers_claim_once():
    send()
    with ThreadPoolExecutor(max_workers=8) as pool:
        claims = list(pool.map(lambda _: claim(engine, config()), range(8)))
    assert sum(job is not None for job in claims) == 1


def test_expired_lease_fences_old_worker():
    send()
    old = claim(engine, config())
    due()
    new = claim(engine, config())
    assert old and new and old["lease_token"] != new["lease_token"]
    assert not finish(engine, old, "delivered")
    assert state() == "delivering"
    assert finish(engine, new, "delivered")


def test_exhausted_crash_lease_moves_to_dead():
    send()
    claim(engine, config())
    execute(
        "UPDATE webhook_outbox SET attempts=:max,lease_until=clock_timestamp()-interval '1 second'",
        {"max": config().max_attempts},
    )
    assert claim(engine, config()) is None
    assert state() == "dead"


def probe(mode):
    script = Path(__file__).with_name("process_case.py")
    result = subprocess.run(
        [sys.executable, str(script), mode],
        env=os.environ.copy(),
        timeout=15,
        check=False,
    )
    return result.returncode


def test_process_death_before_commit_rolls_back_entire_unit():
    assert probe("before-commit") == 66
    assert scalar("SELECT count(*) FROM item") == 0
    assert scalar("SELECT count(*) FROM webhook_inbox") == 0
    assert scalar("SELECT count(*) FROM webhook_outbox") == 0
    assert (
        send(
            payload(
                event_id="crash",
                external_id="product",
                title="Before crash",
                description=None,
            )
        ).status_code
        == 202
    )


def test_process_death_after_remote_commit_recovers(http_client):
    send()
    assert probe("after-partner-commit") == 67
    assert state() == "delivering"
    assert scalar("SELECT apply_count FROM proof_receiver.catalog") == 1
    engine.dispose()  # Discard local pools; recovery cannot depend on a prior session.
    due()
    run_once(engine, config(), http_client)
    assert state() == "delivered"
    assert scalar("SELECT apply_count FROM proof_receiver.catalog") == 1


def test_partner_out_of_order_delivery_preserves_newest(http_client):
    send(payload(event_id="v1"))
    first = claim(engine, config())
    send(payload(event_id="v2", version=2, title="New"))
    second = claim(engine, config())
    dispatch(engine, config(), second, http_client)
    dispatch(engine, config(), first, http_client)
    assert scalar("SELECT version FROM proof_receiver.catalog") == 2
    assert scalar("SELECT count(*) FROM webhook_outbox WHERE state='delivered'") == 2


@pytest.mark.parametrize(
    "code,expected", [(302, "dead"), (401, "dead"), (429, "retry"), (500, "retry")]
)
def test_http_classification(code, expected):
    send()
    with httpx.Client(
        transport=httpx.MockTransport(lambda req: httpx.Response(code))
    ) as client:
        run_once(engine, config(), client)
    assert state() == expected


def test_200_without_receipt_is_not_success():
    send()
    with httpx.Client(
        transport=httpx.MockTransport(lambda req: httpx.Response(200))
    ) as client:
        run_once(engine, config(), client)
    assert state() == "retry"


def test_receiver_rejects_same_key_different_content(http_client):
    send()
    job = claim(engine, config())
    dispatch(engine, config(), job, http_client)
    body = canonical(payload(title="Altered"))
    head = headers(config().outbound_secret.get_secret_value(), body, str(job["id"]))
    head["Idempotency-Key"] = str(job["id"])
    assert (
        http_client.post(
            config().destination_url, content=body, headers=head
        ).status_code
        == 409
    )
    assert scalar("SELECT apply_count FROM proof_receiver.catalog") == 1


def test_receiver_signature_binds_delivery_key(http_client):
    body = canonical(payload())
    head = headers(config().outbound_secret.get_secret_value(), body, str(uuid.uuid4()))
    head["Idempotency-Key"] = str(uuid.uuid4())
    assert (
        http_client.post(
            config().destination_url, content=body, headers=head
        ).status_code
        == 401
    )
    assert scalar("SELECT count(*) FROM proof_receiver.receipt") == 0


def test_managed_items_cannot_be_edited_or_deleted_outside_source():
    send()
    item_id = str(scalar("SELECT id FROM item"))
    with TestClient(app) as client:
        head = operator_headers()
        assert (
            client.put(
                "/api/v1/items/" + item_id,
                json={"title": "Manual conflict"},
                headers=head,
            ).status_code
            == 409
        )
        assert (
            client.delete("/api/v1/items/" + item_id, headers=head).status_code == 409
        )
    assert scalar("SELECT title FROM item") == "Desk lamp"


def test_database_unavailable_returns_retryable_503(monkeypatch):
    from app.webhooks import routes

    unavailable = create_engine(
        engine.url.set(port=1), connect_args={"connect_timeout": 1}
    )
    monkeypatch.setattr(routes, "engine", unavailable)
    try:
        assert send().status_code == 503
        assert scalar("SELECT count(*) FROM webhook_inbox") == 0
    finally:
        unavailable.dispose()


def test_console_available_but_no_event_data_without_auth():
    with TestClient(app) as client:
        assert client.get("/proof").status_code == 200
        assert client.get(URL + "/status").status_code == 401
        assert not any(
            getattr(route, "path", "").startswith("/api/v1/private/")
            for route in app.routes
        )
