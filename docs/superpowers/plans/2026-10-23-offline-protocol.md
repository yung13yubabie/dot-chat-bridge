# Offline protocol candidate implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a bounded, durable, offline reconstruction candidate covering replay, TTL, fencing, duplicate ingestion and source/nonce confusion without claiming live bridge acceptance.

**Architecture:** Keep the preserved 90-test parsers byte-identical. A new `candidate_protocol` package implements the explicit local contract in SPEC.md using SQLite transactions and injected time; it has no transport. Independent reviewers attack the contract and implementation in separate tests. Preserve the old 33-file baseline manifest and generate a distinct development manifest at closeout.

**Tech Stack:** Python standard library, SQLite, unittest, local Git and SHA256; no network or dependencies.

---

### Task 1: Restore and verify baseline

- [x] Restore the verified saved ZIP into a nonexistent directory; initialize a new branch locally and record baseline commit/tree equivalence.
- [x] Run `python -B tools/verify_snapshot.py` on the unchanged preservation copy and `python -B tools/run_tests.py` in the restored development copy; save exit codes and the 90-test log outside the candidate. New development files require their own manifest.

### Task 2: New protocol and regression suite

**Files:** Create `candidate_protocol/__init__.py`, `candidate_protocol/store.py`, `candidate_protocol/tests/test_store.py`.

- [x] Write tests importing `Store, Source, Lease, Reply, ProtocolError` and asserting the public contract before implementation; run `python -B -m unittest discover -s candidate_protocol/tests -v` and save expected import failure.
- [x] Implement SPEC.md: strict input validation, monotone time, atomic fenced claim/renew/cancel, identity-bound ingestion, durable uniqueness and an atomic unsent outbox. No provider adapters or callbacks. Independent conformance review follows.
- [x] Run the new tests, including boundary/overflow values, reopen, distinct-connection races and rollback/crash recovery; save command/results. Initial GREEN: 67 methods; Windows test-owned connection cleanup was corrected with original failure retained.

### Task 3: Independent spec and adversarial review

**Files:** Independent tests in `candidate_protocol/redteam/`; reports outside the candidate.

- [x] Fresh reviewer compares implementation to SPEC.md and writes independent counterexamples for nonce/source/task/message/fence replay and TTL/lease boundaries. Bounded verdict: compliant; 33 methods and 340 subtests pass. Matrix variants outside that run stay explicitly untested.
- [x] Resolve spec ambiguities before oracles: receiver equals task target; HWM-only duplicate/rejection writes are allowed; invalid fields observe clock in transaction; informational lease timestamp is not fingerprinted. No confirmed production defect from the independent run.
- [x] After spec compliance passes, fresh quality reviewer inspects transaction boundaries, validation, persistence, concurrency and overclaims. Bounded approval; no confirmed important issue.

### Task 4: Reproducible local delivery

**Files:** Candidate handoff, local verification/run helper, separate development manifest; workspace evidence and .ai handoff.

- [ ] Preserve the original baseline manifest verbatim. A new development manifest indexes all tracked candidate files and preserved baseline hashes; do not pass the old unlisted-file check by silently dropping files.
- [ ] Rerun the preserved 90 tests and all new suites; mark real Chat/Work, callback, source recovery and 36/12 tests NOT RUN.
- [ ] Save local generic-author commit, patch, source ZIP, Git bundle and SHA index. Verify restore into a new directory without overwriting work. Save a new candidate branch only to the previously approved private repository after checking its owner/private state and branch collision; no force push, main update, new credentials or deployment.
- [ ] Report exact local deliverables, counts, fixed counterexamples, trusted-clock/source limits and minimum supported next evidence needed from the user.
