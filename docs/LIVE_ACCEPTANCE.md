# Real single-message acceptance, 2026-10-23

**PASS within scope: native DOT dispatch to the existing Chat, receiver execution,
and coordinated UI pull-return to parent DOT.** This was one newly authorized real
message, not a fixture. No automatic callback or database ingestion was performed.

## Observations and provenance

- One native `mcp__codex_app__send_message_to_thread` call used the already named
  Chat and only `threadId` / `prompt`. Its successful receipt acknowledged the
  destination; it supplied no user or assistant message ID. No resend occurred.
- The fresh prompt carried a new task ID and nonce, DOT-to-Chat direction and five
  integers: `[832, 300, 792, 538, 380]`. It requested a single JSON object with
  task, nonce, receiver, return target and sum/min/max. The expected output object
  was not supplied. A comparison oracle was saved before dispatch.
- An authorized browser worker's first read saw the complete JSON under the
  assistant label and reply controls after the new prompt. The parent read that
  completed worker report and relayed it to this session. This evidence is a
  browser-worker observation relayed by the parent, not this session's raw UI
  capture or a native complete-message reader receipt.
- The observed task and nonce exactly match the prepared attempt; receiver is
  Chat and return target is DOT. The observed output is sum **2842**, min **300**,
  max **832**, matching both the saved pre-dispatch oracle and the parent's
  independent calculation. Local validation only compared these records; it
  never dispatched, opened a database or fabricated a receiver result.

The exact attempt ledger, prompt hash, native acknowledgement, relayed source
identities and validation hashes remain in the authorized local evidence folder,
outside this repository. Published documents contain no private conversation URL,
message identifier, raw conversation or raw tool receipt.

## Follow-up real reader diagnosis

One subsequent native read returned the exact sent prompt in a completed turn
and a formal assistant message UUID, but its assistant text was only a content
reference. The parent's exact global read of that newly observed message
confirmed the same anchor UUID and exact user prompt. It returned empty assistant
text, `content_omitted=true`, `truncated=false` and no next cursor. The global
result is parent-reported evidence, not a raw local global-reader receipt.
Formal identity is now confirmed; complete-body access through those tools is
still BLOCKED. Do not repeat those same reads. The earlier UI-body observation
remains separate and was not independently UUID-visible within that UI capture.

## Limits that remain

| Gate | Status |
|---|---|
| Single real native dispatch and complete assistant UI reply | PASS within the scope above |
| Receiver execution, fresh task/nonce/direction and independent arithmetic | PASS within the scope above |
| Return of that full result to parent DOT by coordinated UI read | PASS; UI pull-return only |
| Formal assistant message UUID | CONFIRMED by native read and parent-reported exact global anchor; UI itself did not expose it |
| Native/global reader returning a complete body | BLOCKED; native content reference and exact global content omission; UI does not repair either tool |
| Actual model | UNKNOWN; inherit existing conversation, no model override |
| Automatic callback / unattended reader | NOT RUN / UNWIRED |
| Original or candidate database ingestion | NOT RUN; intentionally excluded |
| Original source, original 36/12 tests, original deployment lifecycle and cross-system exactly-once | NOT VERIFIED |
| Work acceptance | NOT RUN in this single-Chat test |

The historical local suites passed 265 methods (90 preserved, 92 candidate,
83 independent). They are fixture/protocol evidence. They were not rerun for
this documentation-only checkpoint and are not evidence of the real route above.
The manifest's `live_bridge_acceptance: NOT RUN` denotes full bridge acceptance,
which remains unverified despite this narrower real pass.

## Minimum real wiring still needed

1. **Supported complete-body reader.** The native sender is available, but the
   candidate adapter has no live tool binding. The available conversation reader
   has no content-resource resolver. Its prior exact read had an empty assistant
   body, `content_omitted=true`, `truncated=false` and no cursor, now confirmed for the fresh test as well. Increasing output
   length cannot resolve it. A normal logged-in UI can show the body, as observed,
   but no unattended UI reader is configured and the shared browser is released.
   Any reader must preserve assistant role, task/nonce, completed state, fresh
   attempt correlation and a verifiable source identity. Formal message identity
   is now available; the complete-body tool requirement remains unmet.
2. **Host binding and one-shot return.** A host that already owns the authorized
   send/read tools must bind them to the adapter, enforce call deadlines and keep
   a durable attempt ledger. The current candidate defaults to unwired and has
   no scheduler or provider authentication. Its pending outbox is local data,
   not delivery. No such live binding was installed during this test.
3. **Actual return sink and acknowledgement.** Identify the supported DOT sink,
   authentication contract, same-task claim/nonce binding, authoritative TTL and
   attempt/ACK IDs before connecting a result. A successful sink write must be
   independently read back once and a duplicate must produce no second result
   or effect. No existing end-to-end sink contract is proven here.

The fixed probe plugin's read-only health check in this checkpoint reports
`events=disabled`, `external_model_calls=false`, Chat/Work dispatch `unverified`,
and both acceptance flags `unmet`. These are capability claims of that plugin,
not a contradiction of the separately observed native Chat route. Its public
tools only create a fixed synthetic task, claim it for a 120-second lease,
submit a same-task answer with claim token and nonce, and read the stored result.
There is no exposed arbitrary enqueue, event-enable, callback destination or
delivery-ACK subscription operation. Its task/claim contract cannot accept this
unrelated live attempt as if it were an active probe claim.

## Bounded next proposal; not executed

There is no exposed usable complete-body resolver in this session. The minimum
platform support request is a documented authorized read of the existing final
assistant message that returns its complete text together with its formal ID,
role, completed state and explicit completeness/omission status. No new dispatch
is needed. More characters or another identical read is not that capability.

An explicitly labeled [semi-automatic UI pull procedure](SEMI_AUTOMATIC_UI_PULL.md)
can be used under the existing one-shot UI coordination, without new credentials.
It is not an unattended host binding or callback. After a usable reader exists,
the real host binding and authorized DOT sink/ACK contract still need wiring and
verification. Neither was created in this diagnosis.

If the only viable reader is browser UI, obtain a dedicated short browser lease
before any UI use. Persistent UI automation, a new sink/service, new OAuth/API
key/scope, purchase or deployment requires a concrete proposal and approval
before setup. No such access, service or deployment was created. Do not invent
an endpoint or route around omitted/denied content. Automatic callback stays
BLOCKED until those missing capabilities and contracts actually exist.
