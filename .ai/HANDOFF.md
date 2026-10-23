# Handoff

Start with README.md, provenance/VERSION_INDEX.json, docs/FINAL_HANDOFF.md, docs/REBUILD_GATES.md and docs/RESTORE.md. Verify snapshot bytes and run the 90 local tests after restoring into a new directory.

Raw account records, original source bytes and the original 36/12 tests are intentionally unavailable here. Generated fixtures are not live evidence. Do not retry inaccessible archives, acquire credentials, invent provider APIs, mutate queued tasks or deploy as part of saving this repository.

For the new offline development candidate, read candidate_protocol/SPEC.md and docs/INTEGRATION_EVIDENCE_REQUIRED.md.
Original parsers and the 90-test suite remain protected by the old manifest. New code/tests are isolated and reviewed separately.
Use tools/verify_candidate.py and tools/run_offline_suites.py at the development save point; no live gate is implied.

Historical protocol overview: docs/OFFLINE_CANDIDATE_HANDOFF.md. Session evidence contains exact commit/tree,
artifact hashes, combined/restore results and independent reports. Keep 90 preserved, 67 candidate and 33 independent
methods separate; the 340 subtests are expansions within independent methods. Never call PARTIAL rows fully covered.

Latest executable candidate: candidate_protocol/TRANSPORT.md, transport.py, tests/test_transport.py and
redteam/test_transport_adversarial.py. The injected Chat boundary uses Store's persistent attempt/read journal
and atomic ingest_transport. Historical 67/33 methods remain; added 25 integration and 41 independent methods
make 92 candidate and 74 independent methods, plus 90 preserved methods. The combined 256-method run passed.
Independent adapter review and exact run logs are retained outside the published repository. No live binding
or external callback exists. Run tools/verify_candidate.py and tools/run_offline_suites.py to reproduce.
Complete real Chat body and original/live gates remain BLOCKED/NOT RUN.

Latest live-gap notes: docs/CONNECTIVITY_STATUS.md and docs/CONNECTIVITY_ACCEPTANCE.md. Body retrieval remains
BLOCKED with content_omitted; original deployed ingestion/callback is unproved and canary was not sent.
The notes contain no actual conversation/message IDs or raw receipts. Do not retry the same omitted body, send a
new task, overwrite the fixed probe or infer live success from historical offline tests.
