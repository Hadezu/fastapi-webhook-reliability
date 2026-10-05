# Verification

Local check 2026-10-05; upstream `1762adac607a1b29cfc4da129557780beea71616`.

- Python 3.14.4, uv 0.12.23, unchanged upstream uv.lock.
- PostgreSQL 18.6 EDB portable binaries linked from postgresql.org; isolated loopback cluster with SCRAM authentication, no system service installation.
- Upstream Items API + CRUD before extension activation: **21 passed**, scoped baseline only.
- Extension: **41 passed**, real PostgreSQL; separate HTTP receiver; concurrent inputs/claims; pre-commit and post-partner-commit process deaths; auth, ordering, retries, audited replay and managed Item guards.
- Status-classification/missing-receipt tests use an explicit HTTP transport double. Lease expiry is accelerated by updating test timestamp fields. These are not endurance tests.
- Bun 1.3.12 frozen install and original TypeScript/Vite frontend production build passed.
- Inherited Starlette TestClient httpx-deprecation warning remains visible; no tests skipped for it.

Final published CI, Compose and browser evidence will be recorded after execution. Until recorded, those are pending.

Not claimed: full upstream email/browser suite, third-party vendor acceptance, production deployment, security audit, capacity/SLA, high availability or disaster recovery. No real funds, stock, client records or live emails involved.
