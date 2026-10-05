"""Generate LOCAL demonstration credentials, never overwrite an existing config."""

import secrets
from pathlib import Path

root = Path(__file__).resolve().parents[1]
values = {
    "PROOF_DB_PASSWORD": secrets.token_hex(24),
    "PROJECT_NAME": "Catalog Webhook Reliability",
    "SECRET_KEY": secrets.token_hex(32),
    "FIRST_SUPERUSER": "operator@example.com",
    "FIRST_SUPERUSER_PASSWORD": secrets.token_urlsafe(24),
    "WEBHOOK_ENABLED": "1",
    "WEBHOOK_OWNER_ID": "11111111-1111-4111-8111-111111111111",
    "WEBHOOK_INBOUND_SECRET": secrets.token_hex(32),
    "WEBHOOK_OUTBOUND_SECRET": secrets.token_hex(32),
}
with (root / ".env.proof").open("x", encoding="utf-8") as target:
    target.write("\n".join(f"{key}={value}" for key, value in values.items()) + "\n")
print("Created .env.proof with local-only credentials. Keep it private; see README.")
