# Demonstration and recovery

Start local Compose as in README. Open `/proof` and sign in using generated credentials. Do not include passwords, keys or tokens in recordings.

1. `python proof/send.py demo-1`; refresh. One delivered event; see its Item in the upstream application.
2. Repeat the command: one receipt/delivery, unchanged Item count.
3. Make the **synthetic receiver** commit then delay its response:

```sh
docker compose --env-file .env.proof -f compose.proof.yml exec db psql -U proof -d webhook_proof -c "UPDATE proof_receiver.control SET mode='lose-response' WHERE id=1"
python proof/send.py demo-2 --version 2 --title "Desk lamp revised"
```

Receiver commits, then waits five seconds; worker timeout is three. Ledger shows retry then delivered. Check real partner state:

```sh
docker compose --env-file .env.proof -f compose.proof.yml exec db psql -U proof -d webhook_proof -c "SELECT external_id,version,apply_count FROM proof_receiver.catalog; SELECT key,created_at FROM proof_receiver.receipt"
```

4. Set mode `reject`, send `demo-3 --version 3`; it becomes dead/http_400. Set mode `ok`, select Replay, explain the correction. Same delivery ID, audited reason, eventual receipt.
5. Stop worker, send a new version, restart worker: it picks up durable work. Ordinary database container restart preserves records; wait for readiness.

Modes: `ok`, `unavailable` (503), `reject` (400), `lose-response` (commit then delay first response). These are simulator DB controls, not public application endpoints.

## Operator decisions

- Ingress 409: inspect source identity/version; don't invent an ID to evade a conflict.
- 401: inspect keys/clocks; don't disable verification.
- Dead delivery: inspect partner outcome/contract and audit before replay.
- Unknown outcome without durable provider idempotency: stop and reconcile.
- Managed Item: update through the signed source.

No external emails, transactions or customer writes are part of this demonstration.
