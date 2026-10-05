"""Verify actual Compose receipt, not just a health check or HTTP 202."""

import time
from pathlib import Path

import httpx
from dotenv import dotenv_values

values = dotenv_values(Path(__file__).resolve().parents[1] / ".env.proof")
with httpx.Client(base_url="http://127.0.0.1:8090", trust_env=False) as client:
    response = client.post(
        "/api/v1/login/access-token",
        data={
            "username": values["FIRST_SUPERUSER"],
            "password": values["FIRST_SUPERUSER_PASSWORD"],
        },
    )
    response.raise_for_status()
    token = response.json()["access_token"]
    for _ in range(30):
        current = client.get(
            "/api/v1/catalog-sync/status", headers={"Authorization": "Bearer " + token}
        )
        current.raise_for_status()
        rows = [
            row for row in current.json()["deliveries"] if row["event_id"] == "ci-smoke"
        ]
        if len(rows) == 1 and rows[0]["state"] == "delivered":
            break
        time.sleep(1)
    else:
        raise RuntimeError("Compose did not produce exactly one delivered receipt")
    assert client.get("/proof").status_code == 200
print(
    "Compose PASS: duplicate input, one delivered receipt, operator console available"
)
