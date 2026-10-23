# dot-chat-bridge preservation

This repository preserves readable, de-identified local work. It is not a recovery
of the missing original bridge and it is not a deployed or accepted Chat/Work bridge.

Contents:

- provenance/: traceable deployment metadata and pure code history; original source bytes are unavailable.
- native-bridge-probe/: newly authored evidence parsers and 90 preserved local test methods.
- fixtures/: generated synthetic data replacing all original account captures.
- docs/FINAL_HANDOFF.md: de-identified latest handoff and remaining limits.
- docs/REBUILD_GATES.md: unimplemented reconstruction candidate and integration requirements.
- missing/: missing content types only, never secret values.

Run with Python 3.11 and Git; all code uses the standard library:

    python tools/verify_snapshot.py
    python tools/run_tests.py

There are no original 36 database / 12 panel tests here. Passing the 90 local
tests proves utility behavior, not live delivery, leases, exactly-once ingestion,
provider mode/model, push callbacks, or full bridge acceptance.

No deployment configuration, queued task data, credentials, account transcripts,
or raw account archives are included. See provenance/VERSION_INDEX.json.

## New offline candidate branch

This isolated branch adds `candidate_protocol`, a newly authored SQLite reference model
for TTL, monotone time, claims/renewals, fencing, terminal cancellation, source/nonce/message
correlation and atomic local result/outbox ingestion. Its optional injected Chat boundary now
joins dispatch receipts, complete reads, validation and atomic ingestion. It implements no
live provider binding, authentication, external callback, acknowledgement or delivery worker.
Source, clock and injected callbacks remain caller trust boundaries.

The original 90 methods remain unchanged. New candidate and independent counterexample suites are separate:

    python -B tools/verify_candidate.py
    python -B tools/run_offline_suites.py

`provenance/SNAPSHOT_MANIFEST.json` remains the original preservation manifest. Its original
unlisted-file check is intended for that snapshot, so the new branch uses the distinct
`provenance/OFFLINE_CANDIDATE_MANIFEST.json`. The new verifier protects baseline source/tests/fixtures/indexes
and checks the full development allowlist. No baseline hashes are rewritten to hide changed code.

See `candidate_protocol/SPEC.md` for the local contract and
`docs/INTEGRATION_EVIDENCE_REQUIRED.md` for live gates and minimum next evidence.
Passing the offline suites cannot certify the missing original bridge or cross-system exactly-once delivery.

Run the synthetic transport integration and independent counterexamples with:

    python -B -m unittest candidate_protocol.tests.test_transport
    python -B -m unittest candidate_protocol.redteam.test_transport_adversarial

See [the injectable transport contract](candidate_protocol/TRANSPORT.md). Default transport is
unwired and BLOCKED; the real complete-body route remains unavailable. No real task is dispatched by tests.

Latest de-identified live-gap checkpoint: [connectivity status](docs/CONNECTIVITY_STATUS.md) and
[single-canary acceptance specification](docs/CONNECTIVITY_ACCEPTANCE.md). Full-body retrieval is BLOCKED
(content_omitted); no canary was sent. That checkpoint records read-only live evidence;
the separate transport tests above use generated fixtures only.
