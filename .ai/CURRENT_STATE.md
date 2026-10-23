# Current state

Readable local evidence utilities and 90 test methods are preserved. Account captures were replaced with generated synthetic fixtures; a minimal pure-code history snapshot replaces the original raw archive dependency. This repository proves no live delivery.

Original bridge source and original 36 database / 12 panel tests are missing. Original deployment commit and archive checksum are metadata only. Lifecycle, provider binding, actual mode/model, push callback and full bridge acceptance remain unverified. See docs/FINAL_HANDOFF.md and docs/REBUILD_GATES.md.

This is an isolated offline development copy restored from the verified source ZIP. It reproduces the exact preservation
base commit and tree. Historical protocol-only baseline: 90 preserved, 67 regression and 33 independent methods
(340 subtests within the historical independent suite). The injected Chat adapter adds 25 integration and
41 independent methods, joining native-tool-shaped fixture receipts/full reads to atomic local ingestion.
The full current 256-method run passed: 90 preserved, 92 candidate and 74 independent methods.
Independent adapter review approved within local fixture scope. It has no live provider binding, external
callback or deployment. See candidate_protocol/TRANSPORT.md; original/live gates remain NOT RUN.

Latest connectivity-only checkpoint: docs/CONNECTIVITY_STATUS.md. Complete final Chat body is omitted even in
the parent's precise global read, without truncation/pagination. Full-body return remains BLOCKED; canary is
not approved or dispatched. That checkpoint is read-only evidence. Separate adapter development runs local
fixture integration and regression only; no real Chat/Work task or original deployment is touched.
