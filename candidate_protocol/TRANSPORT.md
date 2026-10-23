# Injected Chat transport candidate

This new boundary joins native-tool-shaped receipts and complete reads to the existing
SQLite candidate. It contains no network client, endpoint, authentication, scheduler,
live tool binding, Work adapter or external callback endpoint. Default use is BLOCKED.
All integration evidence in this repository is synthetic fixture evidence.

## Interface and reproduction

Python 3.11 standard library; no packages, credentials or network are required:

    python -B -m unittest candidate_protocol.tests.test_transport
    python -B -m unittest candidate_protocol.redteam.test_transport_adversarial
    python -B tools/verify_candidate.py
    python -B tools/run_offline_suites.py

```python
from candidate_protocol.transport import Bridge, InjectedChatTransport

# Host-owned callbacks: each receives one native-tool argument dict and returns
# a surfaced MCP envelope. No callable is provided or invoked by this example.
transport = InjectedChatTransport(send=send_callback, read=read_callback, fixture=True)
bridge = Bridge(store, transport, validate_output=independent_output_validator)
bridge.dispatch(current_lease, synthetic_instruction, requested_model=None)
bridge.poll(current_lease)          # at most one read per explicit invocation
bridge.accept_read(current_lease, observed_read_envelope)  # trusted-host ingress
```

The intended existing Chat operations are the supported tools
`mcp__codex_app__send_message_to_thread` and `mcp__codex_app__read_thread`.
The host must supply authorized bindings; names above are not callable Python APIs.
The send callback receives only `threadId` and `prompt`. The read callback receives
`threadId`, `turnLimit`, `includeOutputs` and `maxOutputCharsPerItem`.
Requested model is stored separately; routing inherits the conversation model and
actual model remains unknown. Work is explicitly unwired in this Chat adapter.

## Durable state and ingress gates

1. The caller creates and claims a task through Store. Dispatch reads the exact
   bound conversation baseline, retaining both turn and message identities.
2. Before calling send, Store atomically commits an `uncertain` attempt, prompt,
   baseline, lease fence, requested model and deadline. A task has at most one
   send attempt, including across reopen, renewed/reclaimed leases and exceptions.
   There is no resend/recovery override. An uncertain attempt requires external
   reconciliation, which is not implemented here.
3. A surfaced formal `threadId` matching the immutable Chat conversation may bind
   the receipt. `clientThreadId`, provisional IDs, wrong kind/source and errors
   cannot bind. A bound receipt means `awaiting_result`, never delivery success.
4. Each explicit poll reserves its read count before I/O. At most three post-send
   reads are allowed, before 90 seconds or earlier task/lease expiry. Late reads
   and output validation cannot bypass the deadline at atomic ingestion. This is
   a persisted admission deadline, not preemption of a synchronous callback;
   any future live host must independently deadline-bound its callbacks.
5. Envelopes must contain structured JSON, one JSON text item, or structured JSON
   with one identical JSON text mirror. Multiple/contradictory payloads, snippets,
   omitted/truncated/paginated content and explicit failure flags reject.
6. Require a single new completed turn, exact sent user prompt, unique formal
   identities, one unambiguous final assistant after that user, and complete
   nonempty JSON body. Baseline IDs cannot be reused. Contradictory role/status
   metadata, references, malformed shapes, duplicate JSON keys and nonfinite
   numbers reject. No snippet or manually supplied expected answer repairs a body.
7. Result keys are exactly `task_id`, `nonce`, `receiver`, `return_target`, `output`.
   Task/nonce must match the claim, receiver is Chat, return target is DOT, output
   is an object and the caller's independent validator must return exactly True.
8. `Store.ingest_transport` adds observed turn/request IDs to the semantic result
   fingerprint in the same transaction as one result, completion and one pending
   local DOT return event. Exact replay returns the same event as `duplicate`;
   changed turn/user/source/nonce/body/message/fence rejects. Failure rolls back
   result/identity/outbox together. The core `Store.ingest` contract is retained.

Expected boundary rejections return `blocked` with a stable code. Ambiguous send
outcomes return `uncertain`. No returned status claims a live bridge success:
`live_verified` is always False. Fixture mode requires explicit fixture envelopes;
injected mode still authenticates neither callbacks nor provider identity.
The trusted host owns callback provenance, authorization, clock and validator.
Unexpected database errors propagate after rollback; they never produce success.

## Evidence limits

Saved native MCP shapes informed generated fixtures; no raw account capture or
actual conversation/message identifier was copied. Passing fixture integration
does not prove provider execution, actual host mode/model, real callback, delivery
or acknowledgement of the pending event, original backend ingestion, recovered
source, original 36/12 tests, or cross-system exactly-once execution.
Complete real Chat body remains omitted. No new real Chat/Work task was sent.
