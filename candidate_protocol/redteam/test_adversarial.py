"""Bounded independent checks derived from SPEC, never live bridge acceptance.

Run from repository root with ``python -B -m candidate_protocol.redteam.test_adversarial``.
Every database is synthetic and retained under a named system temporary directory.
Set OFFLINE_REDTEAM_DATA to choose an explicit evidence directory instead.
"""

from contextlib import closing
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest

from candidate_protocol import Lease, ProtocolError, Reply, Source, Store


MAX = 2**63 - 1
REPO = Path(__file__).resolve().parents[2]
DATA = Path(os.environ.get("OFFLINE_REDTEAM_DATA", str(Path(tempfile.gettempdir()) / "dot-offline-protocol-redteam-data")))
DATA.mkdir(parents=True, exist_ok=True)


class Clock:
    def __init__(self, now=1000):
        self.now = now
        self.calls = 0
        self.transactions = []
        self.probe = None

    def __call__(self):
        self.calls += 1
        if self.probe:
            self.transactions.append(self.probe())
        return self.now


class AdversarialTests(unittest.TestCase):
    def fixture(self, *, now=1000):
        root = Path(tempfile.mkdtemp(prefix=self._testMethodName + "-", dir=DATA))
        f = SimpleNamespace(path=root / "synthetic.sqlite", clock=Clock(now))
        f.s = Store(f.path, f.clock)
        f.clock.probe = lambda: f.s._conn.in_transaction
        self.addCleanup(lambda: f.s.close())
        return f

    def reopen(self, f):
        f.s.close()
        f.s = Store(f.path, f.clock)

    def claim(self, f, *, suffix="A", target="Chat", conversation="conversation_A", ttl=100, lease=40):
        f.s.create("task_" + suffix, "nonce_" + suffix, target, conversation, ttl)
        return f.s.claim("task_" + suffix, "worker_" + suffix, lease)

    def reply(self, lease, **changes):
        value = Reply(lease.task_id, lease.nonce, lease.generation, lease.worker,
                      "message_A", 'synthetic line\n{"answer":"\u4e2d"}', "Chat")
        return replace(value, **changes)

    def ingest(self, f, lease, **changes):
        return f.s.ingest(lease, Source("Chat", "conversation_A"), self.reply(lease, **changes))

    def domain(self, f):
        with closing(sqlite3.connect(f.path)) as db:
            return {table: db.execute("SELECT * FROM " + table + " ORDER BY 1").fetchall()
                    for table in ("tasks", "results", "outbox")}

    def floor(self, f):
        with closing(sqlite3.connect(f.path)) as db:
            return db.execute("SELECT high_water_ms FROM clock_state").fetchone()[0]

    def reject(self, f, action):
        before = self.domain(f)
        with self.assertRaises(ProtocolError) as caught:
            action()
        self.assertIsInstance(caught.exception.code, str)
        self.assertTrue(caught.exception.code)
        self.assertEqual(self.domain(f), before)
        return caught.exception.code

    def race(self, f, actions, *, now=1000):
        barrier = threading.Barrier(2)
        answers = [None, None]

        def worker(index):
            store = None
            try:
                store = Store(f.path, lambda: now)
                barrier.wait(timeout=8)
                try:
                    answers[index] = ("ok", actions[index](store))
                except ProtocolError as error:
                    answers[index] = ("reject", error.code)
            except BaseException as error:
                answers[index] = ("unexpected", repr(error))
            finally:
                if store:
                    store.close()

        workers = [threading.Thread(target=worker, args=(index,), daemon=True) for index in range(2)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=12)
            self.assertFalse(worker.is_alive(), "bounded race exceeded join timeout")
        self.assertNotIn(None, answers)
        self.assertNotIn("unexpected", [answer[0] for answer in answers], answers)
        return answers

    def test_chat_work_and_scoped_outcome(self):
        """B01: each target requires its matching receiver and only local outcome fields."""
        for target in ("Chat", "Work"):
            with self.subTest(target=target):
                f = self.fixture()
                lease = self.claim(f, target=target)
                result = f.s.ingest(lease, Source(target, "conversation_A"), self.reply(lease, receiver=target))
                self.assertEqual(set(result), {"scope", "status", "task_id", "event_id"})
                self.assertEqual((result["scope"], result["status"]), ("offline_candidate", "recorded"))
                self.assertEqual(len(f.s.pending_returns()), 1)
                for private in ("nonce_A", "worker_A", "conversation_A", self.reply(lease).body):
                    self.assertNotIn(private, result["event_id"])

    def test_claim_reply_identity_and_completed_replay_changes(self):
        """B02/B07: every identity and completed semantic field remains bound."""
        f = self.fixture()
        lease = self.claim(f)
        reply = self.reply(lease)
        source = Source("Chat", "conversation_A")
        identity = {"task_id": "task_other", "nonce": "nonce_other", "worker": "worker_other", "generation": 2}
        for field, value in identity.items():
            with self.subTest(phase="live", field=field):
                self.reject(f, lambda: f.s.ingest(replace(lease, **{field: value}), source, reply))
                self.reject(f, lambda: f.s.ingest(lease, source, replace(reply, **{field: value})))
                self.reject(f, lambda: f.s.ingest(replace(lease, **{field: value}), source,
                                                replace(reply, **{field: value})))
        self.ingest(f, lease)
        f.clock.now = 9000
        changes = dict(identity, message_id="message_other", body="changed", receiver="Work",
                       return_target="Work", complete=False, role="user", status="pending")
        for field, value in changes.items():
            with self.subTest(phase="completed", field=field):
                self.reject(f, lambda: f.s.ingest(lease, source, replace(reply, **{field: value})))
        self.assertEqual(self.ingest(f, lease)["status"], "duplicate")

    def test_source_receiver_and_return_binding_before_and_after_completion(self):
        """B03/B04/B07: supplied Source and both destinations are independently checked."""
        f = self.fixture()
        lease = self.claim(f)
        reply = self.reply(lease)
        for completed in (False, True):
            if completed:
                self.ingest(f, lease)
            for source in (Source("Work", "conversation_A"), Source("Chat", "conversation_B")):
                with self.subTest(completed=completed, source=source):
                    self.reject(f, lambda: f.s.ingest(lease, source, reply))
            for changes in ({"receiver": "Work"}, {"receiver": "DOT"}, {"return_target": "Chat"},
                            {"return_target": "dot"}):
                with self.subTest(completed=completed, changes=changes):
                    self.reject(f, lambda: self.ingest(f, lease, **changes))

    def test_final_content_flags(self):
        """B05: truthy values are not final assistant/completed content."""
        f = self.fixture()
        lease = self.claim(f)
        for changes in ({"complete": False}, {"complete": 1}, {"complete": "true"},
                        {"role": "user"}, {"role": "system"}, {"status": "pending"}, {"status": "failed"}):
            with self.subTest(changes=changes):
                self.reject(f, lambda: self.ingest(f, lease, **changes))

    def test_duplicate_at_expiries_restart_and_informational_timestamp(self):
        """B06/T11/A03: completed duplicate survives expiry, restart, and changed informational expiry."""
        f = self.fixture()
        lease = self.claim(f)
        result = self.ingest(f, lease)
        before = self.domain(f)
        for now in (1000, 1040, 1100, 9000):
            f.clock.now = now
            self.reopen(f)
            for until in (0, MAX):
                with self.subTest(now=now, informational_until=until):
                    duplicate = f.s.ingest(replace(lease, lease_until_ms=until), Source("Chat", "conversation_A"), self.reply(lease))
                    self.assertEqual(duplicate, dict(result, status="duplicate"))
                    self.assertEqual(self.domain(f), before)
        self.assertEqual(self.floor(f), 9000)
        self.reopen(f)
        f.clock.now = 8999
        self.assertEqual(self.reject(f, lambda: self.ingest(f, lease)), "clock_rollback")

    def test_message_conflict_does_not_consume_loser_and_distinct_tuple_allowed(self):
        """B08/B09/P12: conflicting global tuple rejects without poisoning a second task."""
        f = self.fixture()
        first = self.claim(f)
        second = self.claim(f, suffix="B")
        self.ingest(f, first)
        self.reject(f, lambda: self.ingest(f, second))
        self.assertEqual(self.ingest(f, second, message_id="message_B")["status"], "recorded")
        third = self.claim(f, suffix="C", conversation="conversation_C")
        self.assertEqual(f.s.ingest(third, Source("Chat", "conversation_C"), self.reply(third))["status"], "recorded")
        fourth = self.claim(f, suffix="D", target="Work")
        self.assertEqual(f.s.ingest(fourth, Source("Work", "conversation_A"), self.reply(fourth, receiver="Work"))["status"], "recorded")
        self.assertEqual(len(f.s.pending_returns()), 4)

    def test_fingerprint_matches_explicit_canonical_semantics(self):
        """B10: canonical JSON binds all semantic fields and excludes informational lease expiry."""
        f = self.fixture()
        lease = self.claim(f)
        reply = self.reply(lease)
        self.ingest(f, lease)
        expected = {"claim": {"task_id": "task_A", "nonce": "nonce_A", "worker": "worker_A", "generation": 1},
                    "source": {"surface": "Chat", "conversation_id": "conversation_A"},
                    "reply": {"task_id": "task_A", "nonce": "nonce_A", "generation": 1, "worker": "worker_A",
                              "message_id": "message_A", "body": reply.body, "receiver": "Chat", "return_target": "DOT",
                              "complete": True, "role": "assistant", "status": "completed"}}
        canonical = json.dumps(expected, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        with closing(sqlite3.connect(f.path)) as db:
            fingerprint, payload = db.execute("SELECT fingerprint,payload_json FROM results").fetchone()
        self.assertEqual(payload, canonical)
        self.assertEqual(fingerprint, hashlib.sha256(canonical.encode("utf-8")).hexdigest())
        self.assertEqual(len(fingerprint), 64)

    def test_identifier_rejections_across_public_positions(self):
        """B11: every identifier entry point rejects a bounded set of malformed values."""
        f = self.fixture()
        lease = self.claim(f)
        source = Source("Chat", "conversation_A")
        reply = self.reply(lease)
        invalid = ("", " ", "local-chatgpt:synthetic", "https://example.invalid/a", "a/b", "a\n", "\u4e2d", "a" * 129, None, True, 7)
        positions = {
            "create.task": lambda v: f.s.create(v, "nonce_new", "Chat", "conversation_new", 100),
            "create.nonce": lambda v: f.s.create("task_new", v, "Chat", "conversation_new", 100),
            "create.conversation": lambda v: f.s.create("task_new", "nonce_new", "Chat", v, 100),
            "claim.task": lambda v: f.s.claim(v, "worker_A", 10),
            "claim.worker": lambda v: f.s.claim("task_A", v, 10),
            "cancel.task": lambda v: f.s.cancel(v),
            "source.conversation": lambda v: f.s.ingest(lease, replace(source, conversation_id=v), reply),
        }
        for field in ("task_id", "nonce", "worker", "message_id"):
            positions["reply." + field] = lambda v, field=field: f.s.ingest(lease, source, replace(reply, **{field: v}))
        for field in ("task_id", "nonce", "worker"):
            positions["lease." + field] = lambda v, field=field: f.s.ingest(replace(lease, **{field: v}), source, reply)
        for position, action in positions.items():
            for value in invalid:
                with self.subTest(position=position, value=repr(value)):
                    self.reject(f, lambda: action(value))
        for value in invalid:
            with self.subTest(position="snapshot", value=repr(value)):
                self.reject(f, lambda: f.s.snapshot(value))

    def test_identifier_legal_boundaries_and_target_exactness(self):
        """B11: ASCII identifier boundaries are syntax, not provider formality proof."""
        for length in (1, 128):
            with self.subTest(length=length):
                f = self.fixture()
                f.s.create("A" * length, "_" * length, "Chat", "-" * length, 100)
                self.assertEqual(f.s.claim("A" * length, "z" * length, 10).generation, 1)
        f = self.fixture()
        for target in ("chat", "WORK", "DOT", None, True, "Chat "):
            with self.subTest(target=target):
                self.reject(f, lambda: f.s.create("task_new", "nonce_new", target, "conversation_new", 100))

    def test_body_utf8_limits_prefix_and_invalid_encoding(self):
        """B12: byte count, final text shape, and literal unresolved prefix are enforced."""
        f = self.fixture()
        lease = self.claim(f)
        for body in ("", None, True, b"body", "x" * 65537, "\u00e9" * 32769,
                     "::chatgpt-content-reference[synthetic]", "\ud800"):
            with self.subTest(kind=type(body).__name__, length=len(body) if isinstance(body, str) else 0):
                self.reject(f, lambda: self.ingest(f, lease, body=body))
        for body in ("x" * 65536, "\u00e9" * 32768):
            f = self.fixture()
            lease = self.claim(f)
            with self.subTest(valid_utf8_bytes=len(body.encode("utf-8"))):
                self.assertEqual(self.ingest(f, lease, body=body)["status"], "recorded")

    def test_numeric_validation_public_positions(self):
        """B13: bool/float/string/range inputs never become counters or timestamps."""
        f = self.fixture()
        lease = self.claim(f)
        reply = self.reply(lease)
        source = Source("Chat", "conversation_A")
        positive = (0, -1, True, False, 1.0, "1", None, MAX + 1)
        actions = {"create.ttl": lambda v: f.s.create("task_new", "nonce_new", "Chat", "conversation_new", v),
                   "claim.duration": lambda v: f.s.claim("task_A", "worker_A", v),
                   "renew.duration": lambda v: f.s.renew(lease, v),
                   "lease.generation": lambda v: f.s.ingest(replace(lease, generation=v), source, reply),
                   "reply.generation": lambda v: f.s.ingest(lease, source, replace(reply, generation=v))}
        for label, action in actions.items():
            for value in positive:
                with self.subTest(position=label, value=repr(value)):
                    self.reject(f, lambda: action(value))
        for value in positive[1:]:
            with self.subTest(position="lease.until", value=repr(value)):
                self.reject(f, lambda: f.s.ingest(replace(lease, lease_until_ms=value), source, reply))

    def test_wrong_object_shapes_are_protocol_errors(self):
        """B14: malformed documented arguments fail as ProtocolError without domain mutations."""
        f = self.fixture()
        lease = self.claim(f)
        source = Source("Chat", "conversation_A")
        reply = self.reply(lease)
        for value in (None, {}, [], "not_an_object", 1):
            for position, action in (
                ("renew.lease", lambda: f.s.renew(value, 10)),
                ("ingest.lease", lambda: f.s.ingest(value, source, reply)),
                ("ingest.source", lambda: f.s.ingest(lease, value, reply)),
                ("ingest.reply", lambda: f.s.ingest(lease, source, value)),
            ):
                with self.subTest(position=position, kind=type(value).__name__):
                    self.reject(f, action)

    def test_exact_task_and_lease_boundaries(self):
        """T01/T02/T03: -1/0/+1 around task and lease expiry remain half-open."""
        for action in ("claim_task", "ingest_task", "ingest_lease", "renew_lease"):
            for offset in (-1, 0, 1):
                with self.subTest(action=action, offset=offset):
                    f = self.fixture()
                    if action == "claim_task":
                        f.s.create("task_A", "nonce_A", "Chat", "conversation_A", 100)
                        boundary = 1100
                        callback = lambda: f.s.claim("task_A", "worker_A", 10)
                    else:
                        lease = self.claim(f, lease=100 if action == "ingest_task" else 40)
                        boundary = 1100 if action == "ingest_task" else 1040
                        callback = (lambda: f.s.renew(lease, 20)) if action == "renew_lease" else (lambda: self.ingest(f, lease))
                    f.clock.now = boundary + offset
                    if offset < 0:
                        callback()
                    else:
                        self.reject(f, callback)

    def test_active_lease_reclaim_and_fence_survive_restart(self):
        """T04/T05/T11: same-worker stealing and stale fences fail across reopen."""
        f = self.fixture()
        old = self.claim(f)
        for worker in ("worker_A", "worker_B"):
            self.reject(f, lambda: f.s.claim("task_A", worker, 40))
        f.clock.now = 1040
        fresh = f.s.claim("task_A", "worker_A", 40)
        self.assertEqual(fresh.generation, 2)
        self.reopen(f)
        self.assertEqual(f.s.snapshot("task_A")["generation"], 2)
        self.reject(f, lambda: f.s.renew(old, 40))
        self.reject(f, lambda: self.ingest(f, old))
        self.reject(f, lambda: f.s.ingest(old, Source("Chat", "conversation_A"), self.reply(fresh)))
        self.reject(f, lambda: f.s.ingest(fresh, Source("Chat", "conversation_A"), self.reply(old)))
        self.assertEqual(self.ingest(f, fresh)["status"], "recorded")

    def test_renew_never_shortens_and_uses_stored_expiry(self):
        """T06/T07: caller timestamps are informational; stored expiry and task cap govern."""
        f = self.fixture()
        lease = self.claim(f)
        f.clock.now = 1020
        for until in (0, MAX):
            renewed = f.s.renew(replace(lease, lease_until_ms=until), 1)
            self.assertEqual((renewed.generation, renewed.lease_until_ms), (1, 1040))
        renewed = f.s.renew(lease, 100)
        self.assertEqual((renewed.generation, renewed.lease_until_ms), (1, 1100))
        f.clock.now = 1100
        self.reject(f, lambda: f.s.renew(replace(lease, lease_until_ms=MAX), 1))
        self.reject(f, lambda: self.ingest(f, replace(lease, lease_until_ms=MAX)))

    def test_every_mutating_invalid_field_observes_clock_and_persists_floor(self):
        """T08/T10/T11/A02: invalid fields observe exactly once inside transaction and survive restart."""
        factories = {
            "create": lambda f, lease: lambda: f.s.create(None, "nonce_new", "Chat", "conversation_new", 10),
            "claim": lambda f, lease: lambda: f.s.claim("task_A", None, 10),
            "renew": lambda f, lease: lambda: f.s.renew(None, 10),
            "cancel": lambda f, lease: lambda: f.s.cancel(None),
            "ingest": lambda f, lease: lambda: f.s.ingest(lease, None, self.reply(lease)),
        }
        for name, factory in factories.items():
            with self.subTest(command=name):
                f = self.fixture()
                lease = self.claim(f)
                calls = f.clock.calls
                f.clock.now = 1050
                self.reject(f, factory(f, lease))
                self.assertEqual(f.clock.calls, calls + 1)
                self.assertTrue(f.clock.transactions[-1])
                self.assertEqual(self.floor(f), 1050)
                self.reopen(f)
                f.clock.now = 1049
                self.assertEqual(self.reject(f, lambda: f.s.cancel("task_A")), "clock_rollback")

    def test_clock_once_for_success_duplicate_and_rejected_commands(self):
        """T08: command clock sampling occurs once under write transaction, reads never sample."""
        f = self.fixture()
        f.s.create("task_A", "nonce_A", "Chat", "conversation_A", 100)
        lease = f.s.claim("task_A", "worker_A", 40)
        lease = f.s.renew(lease, 50)
        self.ingest(f, lease)
        self.ingest(f, lease)
        self.reject(f, lambda: f.s.cancel("task_A"))
        self.assertEqual(f.clock.calls, 6)
        self.assertEqual(f.clock.transactions, [True] * 6)
        f.s.snapshot("task_A")
        f.s.pending_returns()
        self.assertEqual(f.clock.calls, 6)

    def test_rejected_valid_clock_floor_and_shared_connection_restart(self):
        """T09/T10/T11: unknown, binding, lease and expiry failures advance durable shared floor."""
        failures = ("unknown", "binding", "active", "expired")
        for failure in failures:
            with self.subTest(failure=failure):
                f = self.fixture()
                lease = self.claim(f)
                f.clock.now = 1050 if failure != "active" else 1020
                if failure == "unknown":
                    action = lambda: f.s.cancel("task_missing")
                elif failure == "binding":
                    action = lambda: self.ingest(f, replace(lease, nonce="nonce_other"))
                elif failure == "active":
                    action = lambda: f.s.claim("task_A", "worker_B", 10)
                else:
                    f.clock.now = 1100
                    action = lambda: f.s.claim("task_A", "worker_B", 10)
                code = self.reject(f, action)
                self.assertEqual(self.floor(f), f.clock.now)
                observed = f.clock.now
                other = Store(f.path, lambda: observed - 1)
                try:
                    with self.assertRaises(ProtocolError) as caught:
                        other.cancel("task_A")
                    self.assertEqual(caught.exception.code, "clock_rollback")
                finally:
                    other.close()
                self.reopen(f)
                f.clock.now = observed - 1
                self.assertEqual(self.reject(f, lambda: f.s.cancel("task_A")), "clock_rollback")
                f.clock.now = observed
                self.assertEqual(self.reject(f, action), code)

    def test_invalid_clocks_never_poison_floor(self):
        """T12/B13: invalid time rejects and leaves prior valid floor usable."""
        f = self.fixture()
        f.s.create("task_A", "nonce_A", "Chat", "conversation_A", 100)
        for value in (True, False, -1, 1.5, "1000", None, MAX + 1):
            with self.subTest(value=repr(value)):
                f.clock.now = value
                self.reject(f, lambda: f.s.claim("task_A", "worker_A", 10))
                self.assertEqual(self.floor(f), 1000)
        f.clock.now = 1000
        self.assertEqual(f.s.claim("task_A", "worker_A", 10).generation, 1)

    def test_addition_and_durable_fence_overflow(self):
        """T13: capped deadlines and durable fence cannot hide arithmetic overflow."""
        f = self.fixture(now=MAX - 10)
        self.reject(f, lambda: f.s.create("task_A", "nonce_A", "Chat", "conversation_A", 11))
        lease = self.claim(f, ttl=10, lease=1)
        self.reject(f, lambda: f.s.claim("task_A", "worker_B", 11))
        self.reject(f, lambda: f.s.renew(lease, 11))
        g = self.fixture()
        g.s.create("task_A", "nonce_A", "Chat", "conversation_A", 100)
        with closing(sqlite3.connect(g.path)) as db, db:
            db.execute("UPDATE tasks SET generation=?", (MAX,))
        self.reject(g, lambda: g.s.claim("task_A", "worker_A", 10))

    def test_cancelled_state_is_immutable_and_identity_reserved(self):
        """L01/L02: cancellation stays terminal and idempotent after expiry and reopen."""
        for initial in ("queued", "claimed"):
            with self.subTest(initial=initial):
                f = self.fixture()
                if initial == "claimed":
                    lease = self.claim(f)
                else:
                    f.s.create("task_A", "nonce_A", "Chat", "conversation_A", 100)
                    lease = Lease("task_A", "nonce_A", "worker_A", 1, 1040)
                f.s.cancel("task_A")
                before = self.domain(f)
                f.clock.now = 9000
                self.reopen(f)
                f.s.cancel("task_A")
                self.assertEqual(self.domain(f), before)
                for action in (lambda: f.s.claim("task_A", "worker_B", 10), lambda: f.s.renew(lease, 10),
                               lambda: self.ingest(f, lease),
                               lambda: f.s.create("task_A", "nonce_new", "Work", "conversation_new", 10),
                               lambda: f.s.create("task_new", "nonce_A", "Chat", "conversation_new", 10)):
                    self.reject(f, action)
                f.s.create("task_new", "nonce_new", "Chat", "conversation_new", 10)

    def test_completed_state_and_immutable_fields_survive_all_controls(self):
        """L03/L05: completion cannot be cancelled, replaced, renewed, or erased."""
        f = self.fixture()
        lease = self.claim(f)
        self.ingest(f, lease)
        before = self.domain(f)
        self.reopen(f)
        for action in (lambda: f.s.cancel("task_A"), lambda: f.s.claim("task_A", "worker_B", 10),
                       lambda: f.s.renew(lease, 10), lambda: self.ingest(f, lease, body="replacement"),
                       lambda: f.s.create("task_A", "nonce_new", "Work", "conversation_new", 999)):
            self.reject(f, action)
        self.assertEqual(self.domain(f), before)

    def test_nonce_uniqueness_through_every_lifecycle_and_failed_create_recovery(self):
        """L04/L05: expiry and all states retain global identity without reserving failed fresh ID."""
        for state in ("queued", "claimed", "expired", "cancelled", "completed"):
            with self.subTest(state=state):
                f = self.fixture()
                if state == "queued":
                    f.s.create("task_A", "nonce_A", "Chat", "conversation_A", 100)
                else:
                    lease = self.claim(f)
                    if state == "expired":
                        f.clock.now = 1100
                    elif state == "cancelled":
                        f.s.cancel("task_A")
                    elif state == "completed":
                        self.ingest(f, lease)
                self.reject(f, lambda: f.s.create("task_B", "nonce_A", "Work", "conversation_B", 100))
                self.reject(f, lambda: f.s.create("task_A", "nonce_B", "Work", "conversation_B", 100))
                f.s.create("task_B", "nonce_B", "Work", "conversation_B", 100)

    def test_elapsed_snapshot_preserves_stored_state(self):
        """L06: elapsed time on read/reopen is not an invented provider transition."""
        f = self.fixture()
        self.claim(f)
        before = f.s.snapshot("task_A")
        f.clock.now = 9000
        self.reopen(f)
        self.assertEqual(f.s.snapshot("task_A"), before)
        self.assertEqual(self.floor(f), 1000)

    def test_two_connections_race_initial_and_expired_claims(self):
        """P01: exactly one generation increment wins each two-connection claim race."""
        f = self.fixture()
        f.s.create("task_A", "nonce_A", "Chat", "conversation_A", 100)
        for now, generation in ((1000, 1), (1040, 2)):
            with self.subTest(now=now):
                answers = self.race(f, [lambda s: s.claim("task_A", "worker_A", 40),
                                        lambda s: s.claim("task_A", "worker_B", 40)], now=now)
                self.assertEqual(sorted(a[0] for a in answers), ["ok", "reject"])
                self.assertEqual(f.s.snapshot("task_A")["generation"], generation)

    def test_two_connections_race_exact_and_changed_ingress(self):
        """P02/P03: exact duplicate shares one event; changed body has only one winner."""
        for same in (True, False):
            with self.subTest(same=same):
                f = self.fixture()
                lease = self.claim(f)
                source = Source("Chat", "conversation_A")
                replies = [self.reply(lease, body="synthetic_A"), self.reply(lease, body="synthetic_A" if same else "synthetic_B")]
                answers = self.race(f, [lambda s: s.ingest(lease, source, replies[0]),
                                        lambda s: s.ingest(lease, source, replies[1])])
                if same:
                    self.assertEqual(sorted(a[1]["status"] for a in answers), ["duplicate", "recorded"])
                    self.assertEqual(len({a[1]["event_id"] for a in answers}), 1)
                else:
                    self.assertEqual(sorted(a[0] for a in answers), ["ok", "reject"])
                dump = self.domain(f)
                self.assertEqual((len(dump["results"]), len(dump["outbox"])), (1, 1))

    def test_two_connections_race_shared_message_across_tasks(self):
        """P04: shared message tuple cannot complete both tasks or orphan an event."""
        f = self.fixture()
        leases = [self.claim(f), self.claim(f, suffix="B")]
        source = Source("Chat", "conversation_A")
        answers = self.race(f, [lambda s: s.ingest(leases[0], source, self.reply(leases[0])),
                                lambda s: s.ingest(leases[1], source, self.reply(leases[1]))])
        self.assertEqual(sorted(a[0] for a in answers), ["ok", "reject"])
        self.assertEqual(sorted(f.s.snapshot(lease.task_id)["state"] for lease in leases), ["claimed", "completed"])
        self.assertEqual((len(self.domain(f)["results"]), len(f.s.pending_returns())), (1, 1))

    def test_two_connections_race_cancel_and_ingest(self):
        """P05: cancellation/completion has a coherent serialized winner."""
        f = self.fixture()
        lease = self.claim(f)
        answers = self.race(f, [lambda s: s.cancel("task_A"),
                                lambda s: s.ingest(lease, Source("Chat", "conversation_A"), self.reply(lease))])
        self.assertEqual(sorted(a[0] for a in answers), ["ok", "reject"])
        state = f.s.snapshot("task_A")["state"]
        expected = 1 if state == "completed" else 0
        self.assertIn(state, ("cancelled", "completed"))
        self.assertEqual((len(self.domain(f)["results"]), len(f.s.pending_returns())), (expected, expected))

    def test_two_connections_race_reclaim_with_renew_or_stale_ingest(self):
        """P06: exactly at expiry old holder cannot renew/ingest before or after reclaim."""
        for stale_action in ("renew", "ingest"):
            with self.subTest(stale_action=stale_action):
                f = self.fixture()
                lease = self.claim(f)
                callback = ((lambda s: s.renew(lease, 40)) if stale_action == "renew" else
                            (lambda s: s.ingest(lease, Source("Chat", "conversation_A"), self.reply(lease))))
                answers = self.race(f, [lambda s: s.claim("task_A", "worker_B", 40), callback], now=1040)
                self.assertEqual([a[0] for a in answers], ["ok", "reject"])
                self.assertEqual(f.s.snapshot("task_A")["generation"], 2)
                self.assertEqual(f.s.pending_returns(), [])

    def test_pending_returns_detached_stable_and_never_acknowledged(self):
        """P07: reads expose committed local events only and never acknowledge them."""
        f = self.fixture()
        lease = self.claim(f)
        recorded = self.ingest(f, lease)
        before = self.domain(f)
        events = f.s.pending_returns()
        events[0]["body"] = "mutated local copy"
        self.assertEqual(f.s.pending_returns()[0]["body"], self.reply(lease).body)
        self.reopen(f)
        self.assertEqual(f.s.pending_returns()[0]["event_id"], recorded["event_id"])
        self.assertEqual(self.domain(f), before)

    def test_abort_at_each_ingest_stage_is_atomic_and_retryable(self):
        """P08/P12: result, completion, and outbox statement aborts all preserve original claim."""
        stages = {"result": "BEFORE INSERT ON results", "completion": "BEFORE UPDATE OF state ON tasks",
                  "outbox": "BEFORE INSERT ON outbox"}
        for name, clause in stages.items():
            with self.subTest(stage=name):
                f = self.fixture()
                lease = self.claim(f)
                with closing(sqlite3.connect(f.path)) as db, db:
                    db.execute("CREATE TRIGGER redteam_abort " + clause + " BEGIN SELECT RAISE(ABORT,'synthetic redteam fault'); END")
                before = self.domain(f)
                with self.assertRaises(sqlite3.DatabaseError):
                    self.ingest(f, lease)
                self.reopen(f)
                self.assertEqual(self.domain(f), before)
                with closing(sqlite3.connect(f.path)) as db, db:
                    db.execute("DROP TRIGGER redteam_abort")
                self.assertEqual(self.ingest(f, lease)["status"], "recorded")
                self.assertEqual((len(self.domain(f)["results"]), len(f.s.pending_returns())), (1, 1))

    def test_process_exit_before_commit_rolls_back_and_after_return_persists(self):
        """P09/P10: bounded child exits immediately before COMMIT and after successful API return."""
        script = """import os,sys
from candidate_protocol import Store,Lease,Source,Reply
s=Store(sys.argv[1],lambda:1000)
if sys.argv[2]=='before':
    def trace(sql):
        if sql.strip().upper()=='COMMIT': os._exit(83)
    s._conn.set_trace_callback(trace)
s.ingest(Lease('task_A','nonce_A','worker_A',1,1040),Source('Chat','conversation_A'),Reply('task_A','nonce_A',1,'worker_A','message_A','synthetic crash body','Chat'))
os._exit(84)
"""
        for mode, expected_exit in (("before", 83), ("after", 84)):
            with self.subTest(mode=mode):
                f = self.fixture()
                lease = self.claim(f)
                f.s.close()
                child = subprocess.run([sys.executable, "-B", "-c", script, str(f.path), mode],
                                       cwd=REPO, capture_output=True, text=True, timeout=15)
                self.assertEqual(child.returncode, expected_exit, child.stderr)
                f.s = Store(f.path, f.clock)
                dump = self.domain(f)
                if mode == "before":
                    self.assertEqual(f.s.snapshot("task_A")["state"], "claimed")
                    self.assertEqual((len(dump["results"]), len(dump["outbox"])), (0, 0))
                    self.assertEqual(self.ingest(f, lease)["status"], "recorded")
                else:
                    self.assertEqual(f.s.snapshot("task_A")["state"], "completed")
                    self.assertEqual((len(dump["results"]), len(dump["outbox"])), (1, 1))
                    self.assertEqual(f.s.pending_returns()[0]["body"], "synthetic crash body")

    def test_observer_never_sees_uncommitted_return(self):
        """P11: independent observer reads while ingest is paused before outbox insertion."""
        f = self.fixture()
        lease = self.claim(f)
        paused, release = threading.Event(), threading.Event()
        outcome = []

        def writer():
            s = None
            try:
                s = Store(f.path, lambda: 1000)

                def trace(sql):
                    if sql.lstrip().upper().startswith("INSERT INTO OUTBOX"):
                        paused.set()
                        if not release.wait(timeout=8):
                            outcome.append("pause_timeout")

                s._conn.set_trace_callback(trace)
                outcome.append(s.ingest(lease, Source("Chat", "conversation_A"), self.reply(lease)))
            except BaseException as error:
                outcome.append(repr(error))
            finally:
                if s:
                    s.close()

        thread = threading.Thread(target=writer, daemon=True)
        thread.start()
        try:
            self.assertTrue(paused.wait(timeout=8), "writer never reached the bounded pause")
            self.assertEqual(f.s.pending_returns(), [])
            self.assertEqual(f.s.snapshot("task_A")["state"], "claimed")
        finally:
            release.set()
            thread.join(timeout=12)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(outcome), 1, outcome)
        self.assertEqual(outcome[0]["status"], "recorded")
        self.assertEqual(len(f.s.pending_returns()), 1)


class CountResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.subtest_count = 0

    def addSubTest(self, test, subtest, err):
        self.subtest_count += 1
        super().addSubTest(test, subtest, err)


class CountRunner(unittest.TextTestRunner):
    resultclass = CountResult

    def run(self, test):
        result = super().run(test)
        self.stream.writeln("INDEPENDENT_COUNTS " + json.dumps({
            "methods_run": result.testsRun, "subtests_run": result.subtest_count,
            "failures": len(result.failures), "errors": len(result.errors), "skipped": len(result.skipped),
            "scope": "offline_candidate_only", "synthetic_data_root": str(DATA),
        }, sort_keys=True))
        return result


if __name__ == "__main__":
    unittest.main(testRunner=CountRunner(verbosity=2))
