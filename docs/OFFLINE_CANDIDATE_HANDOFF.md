# Offline candidate handoff

This branch is newly authored reconstruction work, based on the exact preserved commit
`68f99e9d820f739a4c32db4f7203c89efab71a90`. It does not recover or replace the original bridge.

## Implemented local contract

`candidate_protocol` provides one SQLite transaction boundary for monotone injected time,
immutable task/nonce/source binding, claim/renewal fencing, terminal cancellation, result uniqueness,
and an atomic pending-return outbox. Exact completed duplicates remain stable after expiry/restart;
altered identities/content cannot reuse that receipt. No delivery/acknowledgement method exists.
Read SPEC.md before adopting any field: none is a discovered original/provider API field.

The trusted local caller supplies time and Source observations. Matching source strings and ID syntax
do not authenticate a provider, prove actual Chat/Work host mode, or validate an actual model.
Local fencing does not control external effects. Local one-time recording is not cross-system exactly-once delivery.

## Recorded bounded reviews

- Preserved utilities: 90 methods unchanged and passed.
- New candidate: 67 methods passed, including concurrency, transaction rollback and process recovery.
- Independent suite: 33 methods and 340 subtests passed, no failures/errors/skips.
  Of 45 matrix rows, 36 are RUN and 9 PARTIAL; unexecuted variants are NOT RUN in the saved review report.
  Race checks are bounded schedules, not exhaustive schedule exploration or power-loss certification.
- Fresh quality review: approved within offline scope, no confirmed Critical/Important issue.
  Narrow helper/store checks were separate from broad suites.
- The first test-only Windows cleanup errors were fixed by closing SQLite handles; original failure evidence is retained.

The full combined run and restored-copy evidence, final commit/tree, artifact SHA256 and independent reports
are saved with the session evidence as `LOCAL_RESULT.json`, `FINAL_HANDOFF.md` and review logs.
These references describe delivered verification evidence, not a provider result.

## Reproduce

```text
python -B tools/verify_candidate.py
python -B tools/run_offline_suites.py
```

The runner rejects missing/miscounted suites and propagates bytecode suppression to subprocesses.
The separate candidate manifest preserves the original baseline manifest and hashes 20 protected baseline files.
Ignored Python caches and synthetic databases retained in outside review evidence are not shipped.

The deliverable bundle includes Git history; its source ZIP contains tracked files only.
Restore into a new directory. Where local Git clone cannot create its Windows shell pipe, use supported
`git init`, `git bundle unbundle`, and detached checkout of the saved candidate commit instead.
Run both commands above from the restored directory. Never restore over an existing project.

## NOT RUN live gates

Original bridge source/36 database/12 panel tests, original lifecycle compatibility, complete final Chat body,
provider provisional-to-formal binding, actual host mode/model, independent receiver execution, real callback,
remote cancellation and full bridge acceptance remain NOT RUN. Host power-loss and exhaustive race schedules
are also outside this bounded local run. See INTEGRATION_EVIDENCE_REQUIRED.md for minimum supported next steps.

No real task was sent/retried, no probe configuration changed, no archive restriction retried,
no credential or permission added, and no deployment or browser action performed.
