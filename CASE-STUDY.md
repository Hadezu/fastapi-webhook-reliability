# Recovering after an ambiguous integration outcome

## Buyer problem

A [Shopify synchronization brief](https://www.upwork.com/freelance-jobs/apply/Custom-inventory-tracker-Shopify_~022102676996535394210/) asks about duplicate deductions, loops and synchronization examples. A [FastAPI brief](https://www.upwork.com/freelance-jobs/apply/Senior-Backend-Full-Stack-API-Engineer_~022092816057309936126/) asks about spoofing, replay, duplicate processing, migrations and downstream-failure tests. The [e-conomic hiring exercise](https://github.com/e-conomic/hiring-assignment-devex) requests reproducible services, CI and integration/fault testing.

These are requirement references checked 2026-10-05, not our clients or newly qualified email leads. No application or contact was made. This example does not satisfy their mandatory production-history gates.

## Existing system and contribution

The upstream FastAPI template supplies authentication, users, Item CRUD, migrations and React. Our extension receives a signed catalog snapshot, updates an existing application's Item owned by a dedicated user, and queues a partner update in one transaction. The partner is an explicitly synthetic separate HTTP process with persistent receipts, not a vendor integration.

## The difficult scenario

The worker sends a delivery. The partner commits its record and receipt, but its response is lost — or the worker process exits before recording success. A later worker reuses the original key and obtains the existing receipt. The partner effect is not repeated.

Tests exercise actual delayed HTTP and explicit hard process termination. Injected faults are labeled as tests, never disguised as upstream defects.

## Engineering decisions

- Atomic local transaction: no changed Item without an outbox task.
- Immutable event identity and monotonic entity version: duplicates and ordering are different concerns.
- Absolute snapshots: stale versions may safely be ignored; deltas need another protocol.
- PostgreSQL outbox instead of a broker: fewer components for this bounded example.
- HTTP outside the database transaction: a slow partner does not hold local application locks.
- Lease plus token: recovery without a stale worker overwriting newer completion.
- Durable partner receipt: at-least-once transport only gives a single effect under this contract.
- Operator replay: dead state, authorization, explicit reason, same delivery key, audit trail.

## Codex and verification

Codex assisted source inspection, design, implementation, tests and documentation. Execution against PostgreSQL exposed an ambiguous SQL parameter type; it was fixed and retested. Review tightened outbound signatures to include the idempotency key. No measured speed/cost advantage or fictional manual-versus-AI comparison is claimed.

This proves an inspectable implementation of scoped application extension, transactions, signed HTTP and recovery testing. It does not prove five years of experience, client history, financial correctness, security certification or universal exactly-once delivery. [Executed scope](docs/VERIFICATION.md).
