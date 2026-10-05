import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
from app.core.db import engine
from app.main import app
from app.webhooks.config import config
from proof_receiver import initialize
from proof_seed import seed
from sqlalchemy import text

BACKEND = Path(__file__).resolve().parents[1] / "backend"


@pytest.fixture(scope="session", autouse=True)
def receiver():
    if (
        not engine.url.database.endswith("_proof")
        or os.environ.get("PROOF_TEST_ALLOW_RESET") != "1"
    ):
        raise RuntimeError(
            "Tests require a disposable *_proof database and PROOF_TEST_ALLOW_RESET=1"
        )
    initialize()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    os.environ["WEBHOOK_DESTINATION_URL"] = f"http://127.0.0.1:{port}/catalog"
    config.cache_clear()
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "proof_receiver:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=BACKEND,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(100):
            if process.poll() is not None:
                raise RuntimeError("Receiver exited during startup")
            try:
                if (
                    httpx.get(
                        f"http://127.0.0.1:{port}/health", timeout=0.5, trust_env=False
                    ).status_code
                    == 200
                ):
                    break
            except httpx.TransportError:
                time.sleep(0.05)
        else:
            raise RuntimeError("Receiver startup timed out")
        yield
    finally:
        process.terminate()
        process.wait(timeout=10)


@pytest.fixture(autouse=True)
def clean(receiver):
    with engine.begin() as conn:
        conn.execute(
            text("""TRUNCATE webhook_audit,webhook_outbox,webhook_inbox,
            webhook_entity,proof_receiver.receipt,proof_receiver.catalog,item RESTART IDENTITY CASCADE""")
        )
        conn.execute(text("UPDATE proof_receiver.control SET mode='ok' WHERE id=1"))
    seed()
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def http_client():
    with httpx.Client(timeout=0.25, trust_env=False, follow_redirects=False) as client:
        yield client
