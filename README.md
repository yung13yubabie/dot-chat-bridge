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
