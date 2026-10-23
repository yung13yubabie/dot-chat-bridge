# DOT to Chat connectivity status

Latest checkpoint: **one real native dispatch, Chat execution and coordinated
UI pull-return to parent DOT passed within scope**. Read the observations,
provenance and limits in [real acceptance](LIVE_ACCEPTANCE.md).

| Stage | Observed | Remaining limit |
|---|---|---|
| Dispatch | One acknowledged native send to the existing Chat; no resend | Receipt supplied no message ID |
| Execution | Fresh task/nonce; prompt did not contain the expected output; complete assistant JSON matched independent arithmetic | Actual model unknown |
| Complete reply | Authorized worker saw full assistant JSON; parent read and relayed the worker report | Formal assistant message UUID not independently visible; no raw native full-body receipt |
| Return to DOT | Parent received the full result through coordinated UI pull-return | No automatic callback or unattended reader |
| Ingestion | Neither original probe nor candidate database was used | Original lifecycle, ingestion and cross-system exactly-once unverified |

Prior reader diagnostics remain distinct: an exact global read returned an
empty assistant text with `content_omitted=true`, `truncated=false` and no cursor.
The observed UI body does not repair that reader. Historical search snippets,
the legacy answer-disclosing prompt, queued receipts and open panels are not
used as independent execution evidence for this new test.

The fixed probe plugin's current read-only health still reports disabled events,
no external model calls and Chat/Work acceptance unmet. It is a separate route.
Do not write this native test into an old cancelled task or treat local outbox
data as an external acknowledgement.

Missing original source and original 36 database / 12 panel tests remain missing.
The 265 passing local fixture/protocol methods are a previous save point, not
live acceptance. No new tests, task dispatch, deployment or permission changes
were made while saving this checkpoint. Main is unchanged.
