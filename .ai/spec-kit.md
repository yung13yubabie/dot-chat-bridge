# Collaboration rules

Read CURRENT_STATE, TASKS, DECISIONS and HANDOFF before edits. This is a de-identified preservation repository, not the missing original bridge. Keep provenance metadata, newly authored tools, generated fixtures and reconstruction design distinct.

Run tools/verify_snapshot.py and tools/run_tests.py before a save point. Preserve 90 test behaviors. Do not add raw account captures, credentials, cookies, environment files or databases. Source hashes do not imply source bytes are present. Do not contact providers, resend tasks or deploy while preserving files.

This isolated development branch adds a new offline candidate. Keep the original baseline manifest unchanged;
its unlisted-file check intentionally does not cover a development tree. For this branch use
`python -B tools/verify_candidate.py` and `python -B tools/run_offline_suites.py` after sealing the separate candidate manifest.
Candidate tests and local outbox records do not establish provider authentication, callback or original compatibility.
