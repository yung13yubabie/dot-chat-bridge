"""SQLite implementation of the newly authored offline candidate contract.

Source and clock are caller observations, not authenticated external evidence.
This module stores pending local events and implements no delivery mechanism.
"""

from dataclasses import asdict, dataclass
import hashlib
import json
import re
import sqlite3


_MAX = (1 << 63) - 1
_IDENTIFIER = re.compile(r"[A-Za-z0-9_-]{1,128}")


class ProtocolError(Exception):
    """An expected protocol rejection; code is stable and contains no input data."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class Source:
    surface: str
    conversation_id: str


@dataclass(frozen=True)
class Lease:
    task_id: str
    nonce: str
    worker: str
    generation: int
    lease_until_ms: int


@dataclass(frozen=True)
class Reply:
    task_id: str
    nonce: str
    generation: int
    worker: str
    message_id: str
    body: str
    receiver: str
    return_target: str = "DOT"
    complete: bool = True
    role: str = "assistant"
    status: str = "completed"


def _identifier(value):
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise ProtocolError("invalid_input")


def _integer(value, *, positive=False):
    if type(value) is not int or value < (1 if positive else 0) or value > _MAX:
        raise ProtocolError("invalid_input")


def _choice(value, choices):
    if not isinstance(value, str) or value not in choices:
        raise ProtocolError("invalid_input")


def _add(left, right):
    if right > _MAX - left:
        raise ProtocolError("overflow")
    return left + right


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _lease_input(lease):
    if not isinstance(lease, Lease):
        raise ProtocolError("invalid_input")
    for value in (lease.task_id, lease.nonce, lease.worker):
        _identifier(value)
    _integer(lease.generation, positive=True)
    _integer(lease.lease_until_ms)


def _ingest_input(lease, source, reply):
    _lease_input(lease)
    if not isinstance(source, Source) or not isinstance(reply, Reply):
        raise ProtocolError("invalid_input")
    _choice(source.surface, ("Chat", "Work"))
    _identifier(source.conversation_id)
    for value in (reply.task_id, reply.nonce, reply.worker, reply.message_id):
        _identifier(value)
    _integer(reply.generation, positive=True)
    _choice(reply.receiver, ("Chat", "Work"))
    _choice(reply.return_target, ("DOT",))
    _choice(reply.role, ("assistant",))
    _choice(reply.status, ("completed",))
    if reply.complete is not True or not isinstance(reply.body, str) or not reply.body:
        raise ProtocolError("invalid_reply")
    try:
        body_size = len(reply.body.encode("utf-8"))
    except UnicodeEncodeError:
        raise ProtocolError("invalid_reply") from None
    if body_size > 65536 or reply.body.lstrip().startswith("::chatgpt-content-reference"):
        raise ProtocolError("invalid_reply")


class Store:
    """One SQLite connection; use separate Store instances for separate workers."""

    def __init__(self, path, clock):
        if not callable(clock):
            raise ProtocolError("invalid_input")
        self._clock = clock
        self._conn = sqlite3.connect(path, timeout=10, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        try:
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.execute("PRAGMA synchronous=FULL")
            self._conn.execute("BEGIN IMMEDIATE")
            self._conn.execute("""CREATE TABLE IF NOT EXISTS clock_state (
                singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                high_water_ms INTEGER NOT NULL CHECK(high_water_ms>=0))""")
            self._conn.execute("INSERT OR IGNORE INTO clock_state VALUES(1, 0)")
            self._conn.execute("""CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                nonce TEXT NOT NULL UNIQUE,
                origin TEXT NOT NULL DEFAULT 'DOT' CHECK(origin='DOT'),
                target TEXT NOT NULL CHECK(target IN ('Chat','Work')),
                conversation_id TEXT NOT NULL,
                expires_at_ms INTEGER NOT NULL,
                state TEXT NOT NULL CHECK(state IN ('queued','claimed','cancelled','completed')),
                generation INTEGER NOT NULL DEFAULT 0 CHECK(generation>=0),
                worker TEXT,
                lease_until_ms INTEGER,
                created_at_ms INTEGER NOT NULL,
                cancelled_at_ms INTEGER,
                completed_at_ms INTEGER)""")
            self._conn.execute("""CREATE TABLE IF NOT EXISTS results (
                task_id TEXT PRIMARY KEY REFERENCES tasks(task_id),
                fingerprint TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                surface TEXT NOT NULL,
                conversation_id TEXT NOT NULL,
                message_id TEXT NOT NULL,
                body TEXT NOT NULL,
                receiver TEXT NOT NULL,
                return_target TEXT NOT NULL CHECK(return_target='DOT'),
                recorded_at_ms INTEGER NOT NULL,
                UNIQUE(surface, conversation_id, message_id))""")
            self._conn.execute("""CREATE TABLE IF NOT EXISTS outbox (
                event_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL UNIQUE REFERENCES results(task_id),
                payload_json TEXT NOT NULL,
                recorded_at_ms INTEGER NOT NULL)""")
            self._conn.execute("""CREATE TABLE IF NOT EXISTS dispatch_attempts (
                task_id TEXT PRIMARY KEY REFERENCES tasks(task_id),
                nonce TEXT NOT NULL, worker TEXT NOT NULL, generation INTEGER NOT NULL,
                prompt TEXT NOT NULL, baseline_json TEXT NOT NULL, baseline_messages_json TEXT NOT NULL,
                requested_model TEXT,
                state TEXT NOT NULL CHECK(state IN ('uncertain','bound')),
                deadline_ms INTEGER NOT NULL, reads INTEGER NOT NULL DEFAULT 0,
                conversation_id TEXT NOT NULL)""")
            self._conn.commit()
        except BaseException:
            self._conn.rollback()
            self._conn.close()
            raise

    def _mutate(self, operation):
        # The clock floor survives expected protocol rejection, while a savepoint
        # guarantees such a rejection cannot partially change protocol records.
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            now = self._clock()
            _integer(now)
            floor = self._conn.execute("SELECT high_water_ms FROM clock_state WHERE singleton=1").fetchone()[0]
            if now < floor:
                raise ProtocolError("clock_rollback")
            if now > floor:
                self._conn.execute("UPDATE clock_state SET high_water_ms=? WHERE singleton=1", (now,))
            self._conn.execute("SAVEPOINT command")
            try:
                result = operation(now)
            except ProtocolError:
                self._conn.execute("ROLLBACK TO command")
                self._conn.execute("RELEASE command")
                self._conn.commit()
                raise
            self._conn.execute("RELEASE command")
            self._conn.commit()
            return result
        except BaseException:
            if self._conn.in_transaction:
                self._conn.rollback()
            raise

    def _task(self, task_id):
        row = self._conn.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        if row is None:
            raise ProtocolError("not_found")
        return row

    @staticmethod
    def _matching(row, lease):
        if (row["task_id"], row["nonce"], row["worker"], row["generation"]) != (
                lease.task_id, lease.nonce, lease.worker, lease.generation):
            raise ProtocolError("lease_mismatch")

    @staticmethod
    def _live(row, now):
        if row["state"] in ("completed", "cancelled"):
            raise ProtocolError("terminal")
        if now >= row["expires_at_ms"]:
            raise ProtocolError("task_expired")

    @staticmethod
    def _lease(row):
        return Lease(row["task_id"], row["nonce"], row["worker"], row["generation"], row["lease_until_ms"])

    def create(self, task_id, nonce, target, conversation_id, ttl_ms):
        def command(now):
            for value in (task_id, nonce, conversation_id):
                _identifier(value)
            _choice(target, ("Chat", "Work"))
            _integer(ttl_ms, positive=True)
            expires_at = _add(now, ttl_ms)
            if self._conn.execute("SELECT 1 FROM tasks WHERE task_id=? OR nonce=?", (task_id, nonce)).fetchone():
                raise ProtocolError("identity_conflict")
            self._conn.execute("""INSERT INTO tasks
                (task_id, nonce, target, conversation_id, expires_at_ms, state, created_at_ms)
                VALUES (?, ?, ?, ?, ?, 'queued', ?)""",
                (task_id, nonce, target, conversation_id, expires_at, now))
        return self._mutate(command)

    def claim(self, task_id, worker, lease_ms):
        def command(now):
            _identifier(task_id)
            _identifier(worker)
            _integer(lease_ms, positive=True)
            requested_end = _add(now, lease_ms)
            row = self._task(task_id)
            self._live(row, now)
            if row["state"] == "claimed" and now < row["lease_until_ms"]:
                raise ProtocolError("lease_active")
            generation = _add(row["generation"], 1)
            until = min(requested_end, row["expires_at_ms"])
            self._conn.execute("""UPDATE tasks SET state='claimed', worker=?, generation=?, lease_until_ms=?
                WHERE task_id=?""", (worker, generation, until, task_id))
            return Lease(task_id, row["nonce"], worker, generation, until)
        return self._mutate(command)

    def renew(self, lease, lease_ms):
        def command(now):
            _lease_input(lease)
            _integer(lease_ms, positive=True)
            requested_end = _add(now, lease_ms)
            row = self._task(lease.task_id)
            self._matching(row, lease)
            self._live(row, now)
            if row["state"] != "claimed":
                raise ProtocolError("lease_mismatch")
            if now >= row["lease_until_ms"]:
                raise ProtocolError("lease_expired")
            until = min(max(row["lease_until_ms"], requested_end), row["expires_at_ms"])
            self._conn.execute("UPDATE tasks SET lease_until_ms=? WHERE task_id=?", (until, lease.task_id))
            return Lease(lease.task_id, lease.nonce, lease.worker, lease.generation, until)
        return self._mutate(command)

    def cancel(self, task_id):
        def command(now):
            _identifier(task_id)
            row = self._task(task_id)
            if row["state"] == "completed":
                raise ProtocolError("terminal")
            if row["state"] != "cancelled":
                self._conn.execute("UPDATE tasks SET state='cancelled', cancelled_at_ms=? WHERE task_id=?", (now, task_id))
        return self._mutate(command)

    def ingest(self, lease, source, reply):
        return self._ingest(lease, source, reply, None)

    def ingest_transport(self, lease, source, reply, turn_id, user_message_id):
        """Atomically bind the observed receiver turn/request to result identity."""
        return self._ingest(lease, source, reply, (turn_id, user_message_id))

    def _ingest(self, lease, source, reply, transport_identity):
        def command(now):
            _ingest_input(lease, source, reply)
            row = self._task(lease.task_id)
            self._matching(row, lease)
            if (reply.task_id, reply.nonce, reply.worker, reply.generation) != (
                    lease.task_id, lease.nonce, lease.worker, lease.generation):
                raise ProtocolError("reply_mismatch")
            if (source.surface, source.conversation_id) != (row["target"], row["conversation_id"]):
                raise ProtocolError("source_mismatch")
            if reply.receiver != row["target"]:
                raise ProtocolError("receiver_mismatch")
            if transport_identity is not None:
                for identity in transport_identity:
                    _identifier(identity)
                attempt = self.dispatch_snapshot(lease)
                if attempt["state"] != "bound":
                    raise ProtocolError("dispatch_unresolved")
                if row["state"] != "completed" and now >= attempt["deadline_ms"]:
                    raise ProtocolError("dispatch_timeout")
            payload = {"source": asdict(source),
                       "claim": {"task_id": lease.task_id, "nonce": lease.nonce,
                                 "worker": lease.worker, "generation": lease.generation},
                       "reply": asdict(reply)}
            if transport_identity is not None:
                payload["transport_identity"] = {"turn_id": transport_identity[0],
                                                 "user_message_id": transport_identity[1]}
            canonical = _canonical(payload)
            fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            if row["state"] == "completed":
                recorded = self._conn.execute("SELECT fingerprint FROM results WHERE task_id=?", (lease.task_id,)).fetchone()
                if recorded["fingerprint"] != fingerprint:
                    raise ProtocolError("result_conflict")
                event_id = self._conn.execute("SELECT event_id FROM outbox WHERE task_id=?", (lease.task_id,)).fetchone()[0]
                return self._outcome("duplicate", lease.task_id, event_id)
            self._live(row, now)
            if row["state"] != "claimed":
                raise ProtocolError("lease_mismatch")
            if now >= row["lease_until_ms"]:
                raise ProtocolError("lease_expired")
            if self._conn.execute("SELECT 1 FROM results WHERE surface=? AND conversation_id=? AND message_id=?",
                                  (source.surface, source.conversation_id, reply.message_id)).fetchone():
                raise ProtocolError("message_conflict")
            self._conn.execute("""INSERT INTO results
                (task_id, fingerprint, payload_json, surface, conversation_id, message_id,
                 body, receiver, return_target, recorded_at_ms) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (lease.task_id, fingerprint, canonical, source.surface, source.conversation_id,
                 reply.message_id, reply.body, reply.receiver, reply.return_target, now))
            self._conn.execute("UPDATE tasks SET state='completed', completed_at_ms=? WHERE task_id=?", (now, lease.task_id))
            event_id = "event_" + hashlib.sha256(_canonical({"scope": "offline_candidate", "task_id": lease.task_id}).encode("utf-8")).hexdigest()
            event = {"scope": "offline_candidate", "event_id": event_id, "task_id": lease.task_id,
                     "nonce": lease.nonce, "worker": lease.worker, "generation": lease.generation,
                     "surface": source.surface, "conversation_id": source.conversation_id,
                     "message_id": reply.message_id, "body": reply.body,
                     "receiver": reply.receiver, "return_target": reply.return_target}
            self._conn.execute("INSERT INTO outbox (event_id, task_id, payload_json, recorded_at_ms) VALUES (?, ?, ?, ?)",
                               (event_id, lease.task_id, _canonical(event), now))
            return self._outcome("recorded", lease.task_id, event_id)
        return self._mutate(command)

    @staticmethod
    def _outcome(status, task_id, event_id):
        return {"scope": "offline_candidate", "status": status, "task_id": task_id, "event_id": event_id}

    def snapshot(self, task_id):
        _identifier(task_id)
        return dict(self._task(task_id))

    def _active_claim(self, lease, now):
        _lease_input(lease)
        row = self._task(lease.task_id)
        self._matching(row, lease)
        self._live(row, now)
        if row["state"] != "claimed":
            raise ProtocolError("lease_mismatch")
        if now >= row["lease_until_ms"]:
            raise ProtocolError("lease_expired")
        return row

    def dispatch_snapshot(self, lease):
        """Local dispatch journal only; it does not attest external delivery."""
        _lease_input(lease)
        task = self._task(lease.task_id)
        self._matching(task, lease)
        attempt = self._conn.execute("SELECT * FROM dispatch_attempts WHERE task_id=?", (lease.task_id,)).fetchone()
        if attempt is None:
            raise ProtocolError("dispatch_not_found")
        if (attempt["nonce"], attempt["worker"], attempt["generation"]) != (
                lease.nonce, lease.worker, lease.generation):
            raise ProtocolError("dispatch_fence_mismatch")
        result = dict(attempt)
        result["baseline_turn_ids"] = json.loads(result.pop("baseline_json"))
        result["baseline_message_ids"] = json.loads(result.pop("baseline_messages_json"))
        result["target"] = task["target"]
        return result

    def reserve_dispatch(self, lease, prompt, baseline_turn_ids, requested_model=None, *, baseline_message_ids):
        """Commit uncertainty before external I/O. A task can never be re-dispatched."""
        def command(now):
            row = self._active_claim(lease, now)
            if row["target"] != "Chat":
                raise ProtocolError("channel_unwired")
            if not isinstance(prompt, str) or not prompt.strip():
                raise ProtocolError("invalid_input")
            try:
                if len(prompt.encode("utf-8")) > 16384:
                    raise ProtocolError("invalid_input")
            except UnicodeEncodeError:
                raise ProtocolError("invalid_input") from None
            for identities in (baseline_turn_ids, baseline_message_ids):
                if not isinstance(identities, list) or len(identities) > 10000:
                    raise ProtocolError("invalid_input")
                for identity in identities:
                    _identifier(identity)
                if len(set(identities)) != len(identities):
                    raise ProtocolError("invalid_input")
            if requested_model is not None and (not isinstance(requested_model, str)
                    or not requested_model.strip() or len(requested_model) > 128):
                raise ProtocolError("invalid_input")
            if self._conn.execute("SELECT 1 FROM dispatch_attempts WHERE task_id=?", (lease.task_id,)).fetchone():
                raise ProtocolError("dispatch_already_attempted")
            deadline = min(_add(now, 90000), row["expires_at_ms"], row["lease_until_ms"])
            self._conn.execute("""INSERT INTO dispatch_attempts
                (task_id,nonce,worker,generation,prompt,baseline_json,baseline_messages_json,requested_model,state,deadline_ms,conversation_id)
                VALUES (?,?,?,?,?,?,?,?,'uncertain',?,?)""",
                (lease.task_id, lease.nonce, lease.worker, lease.generation, prompt,
                 _canonical(baseline_turn_ids), _canonical(baseline_message_ids), requested_model, deadline, row["conversation_id"]))
            return self.dispatch_snapshot(lease)
        return self._mutate(command)

    def bind_dispatch(self, lease, conversation_id):
        def command(now):
            row = self._active_claim(lease, now)
            _identifier(conversation_id)
            attempt = self.dispatch_snapshot(lease)
            if attempt["state"] != "uncertain" or now >= attempt["deadline_ms"]:
                raise ProtocolError("dispatch_unresolved")
            if conversation_id != row["conversation_id"]:
                raise ProtocolError("source_mismatch")
            self._conn.execute("UPDATE dispatch_attempts SET state='bound' WHERE task_id=?", (lease.task_id,))
            return self.dispatch_snapshot(lease)
        return self._mutate(command)

    def prepare_dispatch_read(self, lease, *, consume=False):
        """Check persisted deadline/fence and reserve each read before its I/O."""
        def command(now):
            _lease_input(lease)
            attempt = self.dispatch_snapshot(lease)
            if attempt["state"] != "bound":
                raise ProtocolError("dispatch_unresolved")
            row = self._task(lease.task_id)
            if consume or row["state"] != "completed":
                self._active_claim(lease, now)
                if now >= attempt["deadline_ms"]:
                    raise ProtocolError("dispatch_timeout")
            if consume:
                if attempt["reads"] >= 3:
                    raise ProtocolError("read_budget_exhausted")
                self._conn.execute("UPDATE dispatch_attempts SET reads=reads+1 WHERE task_id=?", (lease.task_id,))
                attempt["reads"] += 1
            return attempt
        return self._mutate(command)

    def pending_returns(self):
        rows = self._conn.execute("SELECT payload_json FROM outbox ORDER BY recorded_at_ms, event_id").fetchall()
        return [json.loads(row[0]) for row in rows]

    def close(self):
        self._conn.close()
