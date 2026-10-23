# Recovering after an ambiguous integration outcome

## Business problem

A receiving service can commit an update while the sender loses the response. Retrying without a durable identity can repeat the effect; stopping indefinitely leaves operations with unresolved deliveries. This implementation connects transactional delivery state to an operator recovery workflow.

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


[Requirement research](REQUIREMENT-RESEARCH.md) · [Discuss an integration](https://work.matiushkin.com/en/contact)
