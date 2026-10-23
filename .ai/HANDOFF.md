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
made the initial 92 candidate/74 independent/90 preserved save point pass 256 methods. The reader request fix
adds redteam/test_reader_contract.py with 9 independent methods: the current 90/92/83 suites pass 265 methods.
It separates the known accepted 20,000-character native profile from the 65,536-byte local body ceiling.
The new suite rejects unsupported request arguments, unresolved/omitted content, truncation and pagination;
changing request size is not reference resolution. Non-author reader-profile review approved within offline scope.
Independent adapter review and exact run logs are retained outside the published repository. No live binding
or external callback exists. Run tools/verify_candidate.py and tools/run_offline_suites.py to reproduce.
Original compatibility and full bridge gates remain BLOCKED/NOT RUN.

Latest real evidence: docs/LIVE_ACCEPTANCE.md and docs/CONNECTIVITY_STATUS.md. One fresh native
Chat send plus coordinated UI pull-return to parent DOT passed within scope. Evidence is the
parent-relayed browser worker's complete assistant JSON and a saved pre-dispatch oracle; exact
private identities and raw receipts remain outside Git. The UI did not independently expose
the assistant message UUID. Native full-body reading, automatic callback and database ingestion
are not passed. No new test or task was created during this documentation save; the existing
265 methods were not rerun without code changes. Do not resend, backfill a cancelled probe,
ingest into the candidate DB or occupy the released shared browser.

Next work is actual supported reader/host/sink wiring, with explicit capability and permission
checks described in docs/LIVE_ACCEPTANCE.md. No credentials, persistent access or deployment
were added. Original source is still missing; do not retry denied archives or invent endpoints.
