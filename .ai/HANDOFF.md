# Handoff

Start with README.md, provenance/VERSION_INDEX.json, docs/FINAL_HANDOFF.md, docs/REBUILD_GATES.md and docs/RESTORE.md. Verify snapshot bytes and run the 90 local tests after restoring into a new directory.

Raw account records, original source bytes and the original 36/12 tests are intentionally unavailable here. Generated fixtures are not live evidence. Do not retry inaccessible archives, acquire credentials, invent provider APIs, mutate queued tasks or deploy as part of saving this repository.

For the new offline development candidate, read candidate_protocol/SPEC.md and docs/INTEGRATION_EVIDENCE_REQUIRED.md.
Original parsers and the 90-test suite remain protected by the old manifest. New code/tests are isolated and reviewed separately.
Use tools/verify_candidate.py and tools/run_offline_suites.py at the development save point; no live gate is implied.

Latest candidate overview: docs/OFFLINE_CANDIDATE_HANDOFF.md. Session evidence contains exact commit/tree,
artifact hashes, combined/restore results and independent reports. Keep 90 preserved, 67 candidate and 33 independent
methods separate; the 340 subtests are expansions within independent methods. Never call PARTIAL rows fully covered.
