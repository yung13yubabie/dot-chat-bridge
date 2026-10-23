# Decisions

- Original provenance is metadata only; never label reconstruction as restored original source.
- Publish only allowlisted de-identified code, synthetic fixtures, hashes and documents.
- Historical account captures and full archives stay outside this repository.
- Keep payload correlation, provider mapping, actual execution and complete bridge acceptance separate.
- Save a local Git commit and recoverable bundle before remote publication; private publication uses existing authorization only.
- The resumed candidate uses its own explicit SQLite contract and separate manifest; the old baseline stays traceable and code/tests stay unchanged.
- Time and observed-source inputs are trusted caller boundaries. Correlation and local transaction fencing do not authenticate a provider or control its external side effects.
- A duplicate/rejected operation may advance the persistent clock floor but cannot change task/result/outbox data.
- Keep receiver equal to the immutable Chat/Work target and the return destination equal to DOT; never infer direction from a payload success flag.
- The optional Chat transport is injection-only, unwired by default, with requested model recorded separately from inherited routing and unknown actual model.
- Persist one uncertain attempt before send and read reservations before I/O. No automatic resend, fallback or uncertain-attempt override exists.
- Transport ingestion fingerprints the observed turn and user-message identity in the same transaction as result/completion/outbox. This binds local replay semantics, not provider authentication or external callback delivery.
