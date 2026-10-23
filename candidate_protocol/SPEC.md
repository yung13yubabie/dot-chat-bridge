# Offline reconstruction candidate v1

This is a new local reference protocol, not recovered bridge code or a provider API.
The core contract below has no live transport, callback sender, credential, service or background process.
An optional injected Chat boundary is specified separately in TRANSPORT.md; its integration tests use fixtures.
Passing tests proves only these local invariants. Original 36/12 tests and real Chat/Work gates remain NOT RUN.

## Public Python contract

Use standard-library SQLite, JSON, dataclasses and unittest. All test data is synthetic.
`Store(path, clock)` opens its own SQLite connection. `clock()` is injected and returns integer milliseconds.
The caller owns the clock and observed-source trust boundary; this module authenticates neither.

```python
Source(surface: str, conversation_id: str)
Lease(task_id: str, nonce: str, worker: str, generation: int, lease_until_ms: int)
Reply(task_id: str, nonce: str, generation: int, worker: str,
      message_id: str, body: str, receiver: str, return_target: str = "DOT",
      complete: bool = True, role: str = "assistant", status: str = "completed")
Store.create(task_id, nonce, target, conversation_id, ttl_ms)
Store.claim(task_id, worker, lease_ms) -> Lease
Store.renew(lease, lease_ms) -> Lease
Store.cancel(task_id)
Store.ingest(lease, source, reply) -> dict
Store.snapshot(task_id) -> dict
Store.pending_returns() -> list[dict]
Store.close()
ProtocolError  # expected fail-closed rejection; exposes a stable .code string
```

`target` and `Source.surface` are exactly Chat or Work; task origin and return destination are DOT.
All IDs/worker values are nonempty ASCII identifiers matching `[A-Za-z0-9_-]{1,128}`.
This rejects known provisional provider formats containing delimiters (such as local-chatgpt:), account URLs,
whitespace and ambiguous composite keys. Identifier shape alone does not prove a provider-issued formal ID;
formal binding remains the trusted caller/adapter's responsibility.
Body is nonempty str, at most 65536 UTF-8 bytes; an unresolved `::chatgpt-content-reference` prefix is rejected.
Counters and time values must be exact int (not bool), nonnegative, within signed 64-bit range.
Durations are positive; generation is positive. Additions must not overflow that range.
Invalid public inputs reject as ProtocolError without task/result/outbox mutations.

## Time and lifecycle

- `create` assigns queued state and immutable `(task_id, nonce, target, conversation_id, expires_at_ms)`.
- Both task IDs and nonces are globally unique and never recycled, even after cancel/completion.
- Every mutating operation observes the injected clock once under an SQLite write transaction.
  Persist a nondecreasing clock high-water mark, including valid times observed by rejected protocol commands.
  This includes invalid field values on calls using the documented method signature; field validation happens
  inside that transaction. Python calls with the wrong number of arguments are outside this command contract.
  Backwards time rejects; no time rollback may revive an expired task or lease.
  Clock trust and restart clock synchronization remain integration requirements.
- Expiry is the half-open boundary `now < expires_at_ms`; exactly at expiry is too late.
- `claim` succeeds only for queued tasks or expired leases on nonterminal tasks before task expiry.
  Lease end is `min(now + lease_ms, task expiry)`. Each successful claim increments the durable fencing generation.
  An active lease cannot be stolen, including by the same worker. Wrong/unknown tasks reject.
- `renew` requires exact current task/nonce/worker/generation and both unexpired task and lease.
  It does not advance generation. It may extend but never shorten the lease or exceed task expiry.
  Caller-supplied lease_until is informational: authorization is the stored tuple and stored current expiry.
- `cancel` is authoritative local control-plane input. Cancellation is idempotent and terminal;
  cancellation after completion rejects and never erases the result. No remote cancellation is implied.
- Completed/cancelled task IDs cannot be claimed, renewed or replaced. Snapshot exposes stored fields;
  elapsed time is enforced on writes, not represented as an externally verified provider state.

## Ingest, replay and outbox

- Require a current claim and matching lease/reply task, nonce, worker and generation.
- Compare the separately supplied observed Source to the immutable target/conversation binding.
  A matching string is correlation only, not authenticated provider identity or actual host mode.
- Require complete final assistant/completed content, reply.receiver equal to the immutable task target
  (Chat or Work), and reply.return_target equal to DOT.
  An expected answer, model self-report, requested model or `success` flag is never an execution proof.
- Store a SHA256 fingerprint over all semantic fields, including source, claim identity, message and body.
  Use canonical JSON with explicit field names, not ambiguous string concatenation.
  Lease.lease_until_ms is informational and excluded from the fingerprint; stored current expiry enforces authorization.
- First valid result before both task and lease expiry atomically commits one result, task completion,
  and one durable pending-return event. Event ID is stable, task scoped, and contains no private data.
- Exact duplicate after completion returns `status=duplicate` with the original event ID and no task/result/outbox side effect,
  even after task/lease expiry; still validate all identity/source/content fields and clock monotonicity.
  The clock high-water mark may advance on duplicates and rejected commands as specified above.
- Changed message/body/source/nonce/fence under an old receipt rejects; it cannot be treated as a duplicate.
- A `(surface, conversation_id, message_id)` can belong to only one result across tasks.
- Failed transactions leave task/result/outbox unchanged. Results and events survive reopen.
  Separate connections racing claims or ingests cannot both win. Reopen and crash/rollback tests are required.
- `pending_returns` reads committed local events only. There is no delivery or acknowledgement function.
  The module cannot mark callback or live bridge success. Ingest returns only
  `{scope: "offline_candidate", status: "recorded" | "duplicate", task_id, event_id}`.

## Acceptance boundaries

Durable local result uniqueness is not exactly-once provider execution or cross-system delivery.
Lease fencing protects only this local database; remote effects are uncontrolled.
Observed Source is an adapter observation supplied by a trusted caller; an attacker who controls that caller
can fabricate an observation. No network identity, signatures, OAuth, model routing or real receiver evidence is tested.
Real callback, full final Chat body, temporary-to-formal provider binding, actual mode/model, original lifecycle
compatibility and original 36/12 tests are NOT RUN. Never loosen these gates to make the candidate pass.
