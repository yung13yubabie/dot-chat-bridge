# Semi-automatic UI pull, operator-assisted

This is an explicit human-in-the-loop procedure for an already authorized
synthetic Chat task. The earlier real test demonstrated this scope. No new UI
read, task, adapter, worker, credential or permission was created by this file.
It does not provide a server callback or a delivery ACK.

1. Parent coordinates a short exclusive slot with the sole browser operator.
   Until the slot is granted, wait; do not open another controller or disturb
   another task's tabs. Use the existing normal logged-in Chat page only.
2. Open the privately recorded existing conversation/message link read-only.
   Confirm the conversation and exact user prompt, task/nonce and DOT-to-Chat
   direction. Select the assistant reply after that prompt. A link/anchor alone
   is not proof that the displayed body is the intended message.
3. Read the complete assistant JSON using normal visible/accessible UI. Record
   its boundaries and assistant role, the related prompt and source location.
   Do not substitute preview/search text, expected values, partial text or a
   content reference. If completeness or identity is ambiguous, mark BLOCKED.
4. Operator returns the full observed body through the existing assigned task
   reporting channel. Parent DOT reads that report and checks exact task/nonce,
   direction, output schema and independent expected result. Keep raw report,
   source identities and body hash in private local evidence, not repository docs.
5. Record one operator-assisted result for that task, release the UI immediately,
   and stop. If the normal UI does not expose a formal message UUID, retain that
   UI-specific limitation even if a native reader independently confirms the ID.
   Repeated reporting must not trigger another send or any database ingestion.

The DOT review record is an operator acknowledgement only. Its label must remain
`semi_automatic_ui_pull_return`, with automatic callback/DB ingestion NOT RUN.
No silent resends, follow-up prompts, background polling or persistent UI worker
are part of this procedure. Normal login needs user handoff if missing; do not
obtain credentials or tokens. This round requires no further UI use because the
existing real reply was already read successfully.

## Minimum platform support for full automation

First, expose a documented full-message reader/resolver under the existing owner
authorization: formal message/conversation IDs, role, final/completed state,
complete assistant text and explicit omission/truncation/pagination metadata.
Current native/global readers confirm identity but do not provide that body.
Do not repeat the same blocked reads; request this specific platform capability.

After that, bind the host's real tool functions with a durable attempt ledger
and bounded calls, then identify a supported owner-authorized DOT return sink
with attempt/ACK IDs, same-task authentication/claim/nonce/TTL and duplicate
handling that can be independently read back. None is currently connected.
The fixed probe's old tasks are not this sink and must not be changed.

No new account permission is needed to describe or use the existing one-shot
procedure within its coordination scope. Any new persistent UI access, service,
credential/scope, purchase or deployment requires an exact proposal before
setup. This procedure requests none of them and creates no new external recipient.
