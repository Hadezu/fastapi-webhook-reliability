"""Standard-library sender for the localhost demonstration only."""

import argparse
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("event_id")
parser.add_argument("--item", default="lamp-1")
parser.add_argument("--version", type=int, default=1)
parser.add_argument("--title", default="Desk lamp")
parser.add_argument("--url", default="http://127.0.0.1:8090/api/v1/catalog-sync/events")
args = parser.parse_args()
values = dict(os.environ)
env_file = Path(__file__).resolve().parents[1] / ".env.proof"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1)
            values[key] = value
if not args.url.startswith("http://127.0.0.1:"):
    raise SystemExit("This demonstration sender only permits localhost URLs")
body = json.dumps(
    {
        "event_id": args.event_id,
        "external_id": args.item,
        "version": args.version,
        "title": args.title,
        "description": "Synthetic catalog sample",
    }
).encode()
stamp = str(int(time.time()))
signed = hmac.new(
    values["WEBHOOK_INBOUND_SECRET"].encode(),
    stamp.encode() + b"." + body,
    hashlib.sha256,
).hexdigest()
request = urllib.request.Request(
    args.url,
    data=body,
    headers={
        "Content-Type": "application/json",
        "X-Webhook-Timestamp": stamp,
        "X-Webhook-Signature": signed,
    },
)
try:
    with urllib.request.urlopen(request, timeout=10) as response:
        print(response.status, response.read().decode())
except urllib.error.HTTPError as error:
    print(error.code, error.read().decode())
    raise SystemExit(1)
