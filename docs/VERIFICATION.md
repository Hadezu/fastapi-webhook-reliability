# Verification

Local check 2026-10-05; upstream `1762adac607a1b29cfc4da129557780beea71616`.

- Python 3.14.4, uv 0.12.23, unchanged upstream uv.lock.
- PostgreSQL 18.6 EDB portable binaries linked from postgresql.org; isolated loopback cluster with SCRAM authentication, no system service installation.
- Upstream Items API + CRUD before extension activation: **21 passed**, scoped baseline only.
- Extension: **41 passed**, real PostgreSQL; separate HTTP receiver; concurrent inputs/claims; pre-commit and post-partner-commit process deaths; auth, ordering, retries, audited replay and managed Item guards.
- Status-classification/missing-receipt tests use an explicit HTTP transport double. Lease expiry is accelerated by updating test timestamp fields. These are not endurance tests.
- Bun 1.3.12 frozen install and original TypeScript/Vite frontend production build passed.
- Inherited Starlette TestClient httpx-deprecation warning remains visible; no tests skipped for it.

- Browser automation passed: actual localhost login, duplicate input, lost-response retry, recovery, dead-delivery operator replay, 390px viewport without page overflow, logout. No browser page errors. Screenshots and original WebM are in `docs/images/`. Partner version/apply_count progressed 1/1 → 2/2 → 3/3, not once per HTTP attempt.
- Ruff lint/format and module mypy passed. Migration downgrade/upgrade and post-change upstream Items/CRUD regression passed (21 tests).

- A pending `restart-proof` delivery survived an actual restart of the isolated PostgreSQL server. Dispatch after restart reached `delivered`; the partner recorded `apply_count=1`. This was an ordinary database restart, not a disk-loss, backup-restore or high-availability test.

Implementation checked locally: `61540587fd9deaa4ae135e01284cce4f8194e93c`.

[GitHub Actions run for that revision](https://github.com/Hadezu/fastapi-webhook-reliability/actions/runs/37368604732) completed **SUCCESS** on 2026-10-05. On a clean Ubuntu runner it passed the pristine upstream Items/CRUD baseline, migration roundtrip, post-change upstream regression, all extension tests, frontend build, lint/format/types, and actual Docker Compose build/startup/delivery smoke. The Compose smoke submitted the same event twice and verified one delivered outbox entry with a matching destination receipt. It is a bounded smoke test, not the entire fault suite repeated inside Compose.

Docker was unavailable on the local Windows host; its execution evidence comes from that hosted run. Subsequent documentation-only commits do not change the tested implementation. Test XML and Compose logs are attached to the run with 14-day artifact retention.

Local browser recording: `docs/images/recovery-demo.webm`, SHA-256 `CB90E18DE2B1EC75EAA7EA0E621A0308FAF92CC6956D3B338B6CB204354385E5`.

Not claimed: full upstream email/browser suite, third-party vendor acceptance, production deployment, security audit, capacity/SLA, high availability or disaster recovery. No real funds, stock, client records or live emails involved.
