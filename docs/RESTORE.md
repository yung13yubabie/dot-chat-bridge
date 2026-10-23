# Restore

The local Git bundle and source ZIP are produced outside the repository after validation.
Restore the bundle into a new directory, then run integrity and local tests:

    git clone dot-chat-bridge.bundle restored-dot-chat-bridge
    cd restored-dot-chat-bridge
    python tools/verify_snapshot.py
    python tools/run_tests.py

Compare the restored HEAD with the saved local commit and compare every file with
provenance/SNAPSHOT_MANIFEST.json. A ZIP restores files without Git history;
the Git bundle restores the commit and branch. Never extract over an existing project.

The initial commit uses a generic preservation identity and a fixed archival date.
Its tree and commit can be reproduced from the exact bundle and commit metadata.
Remote publication must use only the explicitly authorized private destination,
after de-identification review and existing authorization checks. There is no deployment step.
