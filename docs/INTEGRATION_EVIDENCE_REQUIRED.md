# Evidence still required for a real bridge

The offline candidate has no adapter, transport or callback. Nothing here changes probe_chat_v1.
These are next-step requirements, not completed actions or permission to create credentials.

| Gate | Evidence required | This round |
|---|---|---|
| Original compatibility | Readable source snapshot, uncommitted diff, schema/config structure and original 36 database / 12 panel tests | NOT RUN; original bytes unavailable |
| Complete Chat body | Supported read of the existing completed final assistant message, formal conversation/message identifiers, full body and no omission/content reference | NOT RUN |
| Provider binding | Actual surfaced provisional-to-formal mapping where relevant; requested target versus observed host mode kept separate | NOT RUN |
| Actual model | Provider/tool metadata; otherwise record inherit-existing-conversation and actual model unknown | NOT RUN |
| Live lifecycle | Authoritative task/claim/fence/TTL/cancel state checked by the real receiving store | NOT RUN |
| Real return | DOT-side receipt of the full receiver result correlated to the original task/nonce plus receiver evidence | NOT RUN |
| Callback | Real authorized destination, attempt/ack identifiers, retry/dedup contract and receiver evidence | NOT RUN |
| Independent execution | A future authorized synthetic task without its answer disclosed in its prompt, receiver-produced full reply and independent verifier | NOT RUN; no dispatch this round |

## Minimum next user steps, only when resuming integration

1. If the original source exists in a readable local checkout or previously downloaded source archive, place a copy
   in the authorized workspace and provide its exact path. Include source/tests and a separately exported uncommitted
   diff; remove environment files, tokens, cookies, database/account records and credential values. Preserve the original.
   Acceptance: compare the readable source to the recorded deployment commit/archive checksum and inspect its own rules
   before editing an isolated copy. A speculative reconstruction cannot pass this compatibility gate.
   Do not retry the already invisible Library archive or broaden file permissions.

2. In the already existing Chat test conversation, locate the final assistant reply for the saved task/nonce;
   do not send a new message or ask it to calculate again. Use an existing supported export/read path to provide the
   complete final body together with formal conversation/message identifiers, completed state and the related user prompt.
   Acceptance: exact saved task/nonce, DOT-to-Chat direction, same completed turn, complete final body, unambiguous identities,
   no omission marker and no earlier-reply substitution. If only manual text is available, label it a manual copy:
   it can support payload comparison but does not establish authenticated tool provenance, provider mode/model or callback.
   Existing conversation details remain in the original private handoff, outside this de-identified repository.

3. Before any real adapter or callback integration, provide the already authorized supported channel contract and
   exact receiver/return destination. If it needs a new OAuth scope, API key or persistent permission, stop and report
   the specific minimum requirement; do not configure it automatically. A supported pull result may be recorded as
   pull-return evidence only. Pending local outbox data, manual copying, queued receipts and open panels are not callback proof.

No new task, permission or deployment is required to run the offline candidate tests. This round intentionally performs
none of the actions above. Source identity and time in the candidate are supplied by a trusted local caller; authentication,
clock synchronization, external side effects and cross-system exactly-once semantics remain adapter responsibilities.
