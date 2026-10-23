"""Contract and failure tests written before the candidate implementation."""

from contextlib import closing
from dataclasses import FrozenInstanceError, replace
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest

from candidate_protocol import Lease, ProtocolError, Reply, Source, Store


MAX = (1 << 63) - 1


class Clock:
    def __init__(self, value=1000):
        self.value = value
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return self.value


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="offline-candidate-")
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "synthetic.sqlite"
        self.clock = Clock()
        self.store = Store(self.path, self.clock)
        self.addCleanup(lambda: self.store.close())

    def create(self, task="task_A", nonce="nonce_A", target="Chat", conversation="conv_A", ttl=1000):
        self.store.create(task, nonce, target, conversation, ttl)

    def claimed(self, ttl=1000, lease_ms=100):
        self.create(ttl=ttl)
        return self.store.claim("task_A", "worker_A", lease_ms)

    def reply(self, lease, **changes):
        value = Reply(lease.task_id, lease.nonce, lease.generation, lease.worker,
                      "message_A", "synthetic complete answer", "Chat")
        return replace(value, **changes)

    def ingest(self, lease, **changes):
        return self.store.ingest(lease, Source("Chat", "conv_A"), self.reply(lease, **changes))

    def reject_unchanged(self, callback):
        before = self.store.snapshot("task_A")
        events = self.store.pending_returns()
        with self.assertRaises(ProtocolError) as caught:
            callback()
        self.assertIsInstance(caught.exception.code, str)
        self.assertTrue(caught.exception.code)
        self.assertEqual(self.store.snapshot("task_A"), before)
        self.assertEqual(self.store.pending_returns(), events)
        return caught.exception.code

    def reopen(self):
        self.store.close()
        self.store = Store(self.path, self.clock)


class ValidationTests(StoreTest):
    def test_create_snapshot_fields(self):
        self.create()
        row = self.store.snapshot("task_A")
        for key, expected in {"task_id": "task_A", "nonce": "nonce_A", "target": "Chat",
                              "conversation_id": "conv_A", "state": "queued",
                              "generation": 0, "expires_at_ms": 2000}.items():
            self.assertEqual(row[key], expected)

    def test_work_target_is_supported(self):
        self.create(target="Work")
        lease = self.store.claim("task_A", "worker_A", 100)
        result = self.store.ingest(lease, Source("Work", "conv_A"), self.reply(lease, receiver="Work"))
        self.assertEqual(result["status"], "recorded")

    def test_invalid_identifiers_create_no_tasks(self):
        invalid = ["", "has space", "temp:id", "https://example.test", "é", "a" * 129,
                   "a\n", None, 1, True, b"abc"]
        for value in invalid:
            for index in (0, 1, 3):
                args = ["task_A", "nonce_A", "Chat", "conv_A", 100]
                args[index] = value
                with self.subTest(value=repr(value), index=index), self.assertRaises(ProtocolError):
                    self.store.create(*args)
        self.create()

    def test_identifier_boundaries_are_allowed(self):
        self.create(task="A" * 128, nonce="_" * 128, conversation="-" * 128)
        self.assertEqual(self.store.claim("A" * 128, "z" * 128, 1).generation, 1)

    def test_exact_target_only(self):
        for target in ("chat", "WORK", "DOT", "Chat ", None, True):
            with self.subTest(target=target), self.assertRaises(ProtocolError):
                self.create(target=target)

    def test_duration_exact_positive_int(self):
        self.create()
        for duration in (0, -1, True, False, 1.0, "1", None, MAX + 1):
            with self.subTest(duration=duration):
                with self.assertRaises(ProtocolError):
                    self.store.create("task_B", "nonce_B", "Chat", "conv_B", duration)
                self.reject_unchanged(lambda: self.store.claim("task_A", "worker_A", duration))

    def test_invalid_worker_does_not_claim(self):
        self.create()
        for worker in ("", "bad worker", 1, None, "é", "w" * 129):
            with self.subTest(worker=worker):
                self.reject_unchanged(lambda: self.store.claim("task_A", worker, 10))

    def test_create_time_addition_overflow_rejects(self):
        self.clock.value = MAX
        with self.assertRaises(ProtocolError):
            self.create(ttl=1)

    def test_claim_addition_overflow_rejects_even_if_capped(self):
        self.clock.value = MAX - 10
        self.create(ttl=10)
        self.reject_unchanged(lambda: self.store.claim("task_A", "worker_A", 11))

    def test_renew_addition_overflow_rejects(self):
        self.clock.value = MAX - 10
        lease = self.claimed(ttl=10, lease_ms=1)
        self.reject_unchanged(lambda: self.store.renew(lease, 11))

    def test_unknown_tasks_reject(self):
        for call in (lambda: self.store.snapshot("missing"), lambda: self.store.claim("missing", "w", 1),
                     lambda: self.store.cancel("missing")):
            with self.assertRaises(ProtocolError):
                call()

    def test_task_id_is_never_recycled(self):
        self.create()
        self.store.cancel("task_A")
        self.reject_unchanged(lambda: self.store.create("task_A", "nonce_B", "Chat", "conv_B", 100))

    def test_nonce_is_globally_unique_after_cancel(self):
        self.create()
        self.store.cancel("task_A")
        self.reject_unchanged(lambda: self.store.create("task_B", "nonce_A", "Chat", "conv_B", 100))

    def test_global_ids_survive_reopen_and_completion(self):
        lease = self.claimed()
        self.ingest(lease)
        self.reopen()
        for args in (("task_A", "nonce_B"), ("task_B", "nonce_A")):
            self.reject_unchanged(lambda: self.store.create(*args, "Work", "conv_B", 100))

    def test_public_dataclasses_are_value_objects(self):
        lease = self.claimed()
        self.assertIsInstance(lease, Lease)
        self.assertEqual(Reply("t", "n", 1, "w", "m", "b", "DOT").return_target, "DOT")
        with self.assertRaises((FrozenInstanceError, AttributeError)):
            lease.worker = "changed"

    def test_snapshot_and_events_are_detached(self):
        lease = self.claimed()
        self.ingest(lease)
        snapshot = self.store.snapshot("task_A")
        snapshot["state"] = "queued"
        events = self.store.pending_returns()
        events[0]["task_id"] = "different"
        self.assertEqual(self.store.snapshot("task_A")["state"], "completed")
        self.assertEqual(self.store.pending_returns()[0]["task_id"], "task_A")


class ClockTests(StoreTest):
    def test_each_mutating_call_observes_clock_once(self):
        self.create()
        lease = self.store.claim("task_A", "worker_A", 100)
        lease = self.store.renew(lease, 101)
        self.ingest(lease)
        self.ingest(lease)
        self.assertEqual(self.clock.calls, 5)
        with self.assertRaises(ProtocolError):
            self.store.cancel("task_A")
        self.assertEqual(self.clock.calls, 6)

    def test_reads_do_not_observe_clock(self):
        self.create()
        calls = self.clock.calls
        self.store.snapshot("task_A")
        self.store.pending_returns()
        self.assertEqual(self.clock.calls, calls)

    def test_invalid_clocks_fail_closed(self):
        self.create()
        for value in (True, False, -1, 1.5, "1000", None, MAX + 1):
            self.clock.value = value
            with self.subTest(value=value):
                self.reject_unchanged(lambda: self.store.claim("task_A", "worker_A", 100))

    def test_backwards_clock_rejects(self):
        self.create()
        self.clock.value = 999
        self.reject_unchanged(lambda: self.store.claim("task_A", "worker_A", 100))

    def test_rejected_expiry_persists_time_across_reopen(self):
        self.create(ttl=100)
        self.clock.value = 1100
        self.reject_unchanged(lambda: self.store.claim("task_A", "worker_A", 100))
        self.reopen()
        self.clock.value = 1099
        self.reject_unchanged(lambda: self.store.claim("task_A", "worker_A", 100))
        self.clock.value = 1100
        self.reject_unchanged(lambda: self.store.claim("task_A", "worker_A", 100))

    def test_rejected_invalid_command_also_persists_valid_time(self):
        self.create()
        self.clock.value = 1050
        self.reject_unchanged(lambda: self.store.claim("task_A", "bad worker", 1))
        self.reopen()
        self.clock.value = 1049
        self.reject_unchanged(lambda: self.store.claim("task_A", "worker_A", 1))

    def test_rejected_unknown_task_persists_time(self):
        self.create()
        self.clock.value = 1050
        with self.assertRaises(ProtocolError):
            self.store.cancel("unknown")
        self.clock.value = 1049
        self.reject_unchanged(lambda: self.store.claim("task_A", "worker_A", 1))

    def test_shared_high_water_between_connections(self):
        self.create()
        other_clock = Clock(1050)
        other = Store(self.path, other_clock)
        self.addCleanup(other.close)
        with self.assertRaises(ProtocolError):
            other.cancel("unknown")
        self.reject_unchanged(lambda: self.store.claim("task_A", "worker_A", 1))

    def test_duplicate_cannot_bypass_clock_rollback(self):
        lease = self.claimed()
        self.ingest(lease)
        self.clock.value = 999
        self.reject_unchanged(lambda: self.ingest(lease))


class LifecycleTests(StoreTest):
    def test_claim_and_reclaim_increment_fence(self):
        lease = self.claimed()
        self.assertEqual(lease, Lease("task_A", "nonce_A", "worker_A", 1, 1100))
        self.clock.value = 1100
        next_lease = self.store.claim("task_A", "worker_B", 100)
        self.assertEqual(next_lease.generation, 2)
        self.assertEqual(next_lease.lease_until_ms, 1200)

    def test_active_lease_cannot_be_stolen_even_by_same_worker(self):
        self.claimed()
        for worker in ("worker_A", "worker_B"):
            self.reject_unchanged(lambda: self.store.claim("task_A", worker, 100))

    def test_claim_capped_at_task_expiry(self):
        lease = self.claimed(ttl=50, lease_ms=100)
        self.assertEqual(lease.lease_until_ms, 1050)

    def test_task_ttl_half_open(self):
        self.create(ttl=1)
        self.clock.value = 1001
        self.reject_unchanged(lambda: self.store.claim("task_A", "worker_A", 1))

    def test_renew_extends_without_advancing_generation(self):
        lease = self.claimed()
        self.clock.value = 1050
        renewed = self.store.renew(lease, 100)
        self.assertEqual(renewed.generation, 1)
        self.assertEqual(renewed.lease_until_ms, 1150)

    def test_renew_never_shortens(self):
        lease = self.claimed()
        self.clock.value = 1050
        self.assertEqual(self.store.renew(lease, 1).lease_until_ms, 1100)

    def test_renew_caps_at_task_expiry(self):
        lease = self.claimed(ttl=150)
        self.assertEqual(self.store.renew(lease, 200).lease_until_ms, 1150)

    def test_lease_until_is_informational(self):
        lease = self.claimed()
        self.clock.value = 1050
        forged = replace(lease, lease_until_ms=MAX)
        self.assertEqual(self.store.renew(forged, 100).lease_until_ms, 1150)

    def test_renew_at_lease_expiry_rejects(self):
        lease = self.claimed()
        self.clock.value = 1100
        self.reject_unchanged(lambda: self.store.renew(lease, 100))

    def test_stale_fence_renew_rejects(self):
        lease = self.claimed()
        self.clock.value = 1100
        self.store.claim("task_A", "worker_A", 100)
        self.reject_unchanged(lambda: self.store.renew(lease, 100))

    def test_renew_requires_every_identity_field(self):
        lease = self.claimed()
        for change in ({"task_id": "other"}, {"nonce": "other"}, {"worker": "other"}, {"generation": 2}):
            self.reject_unchanged(lambda: self.store.renew(replace(lease, **change), 100))

    def test_cancel_is_terminal_and_idempotent(self):
        lease = self.claimed()
        self.store.cancel("task_A")
        before = self.store.snapshot("task_A")
        self.store.cancel("task_A")
        self.assertEqual(self.store.snapshot("task_A"), before)
        for call in (lambda: self.store.claim("task_A", "worker_B", 1),
                     lambda: self.store.renew(lease, 100), lambda: self.ingest(lease)):
            self.reject_unchanged(call)

    def test_cancel_after_task_expiry_is_allowed(self):
        self.create(ttl=1)
        self.clock.value = 1001
        self.store.cancel("task_A")
        self.assertEqual(self.store.snapshot("task_A")["state"], "cancelled")

    def test_completed_task_cannot_be_cancelled_claimed_or_renewed(self):
        lease = self.claimed()
        self.ingest(lease)
        for call in (lambda: self.store.cancel("task_A"), lambda: self.store.claim("task_A", "worker_B", 1),
                     lambda: self.store.renew(lease, 100)):
            self.reject_unchanged(call)

    def test_fence_overflow_cannot_wrap(self):
        self.create()
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE tasks SET generation=? WHERE task_id=?", (MAX, "task_A"))
        self.reject_unchanged(lambda: self.store.claim("task_A", "worker_A", 1))


class IngestTests(StoreTest):
    def test_first_result_and_exact_duplicate_have_only_scoped_outcome(self):
        lease = self.claimed()
        first = self.ingest(lease)
        self.assertEqual(set(first), {"scope", "status", "task_id", "event_id"})
        self.assertEqual(first["scope"], "offline_candidate")
        self.assertEqual(first["status"], "recorded")
        self.assertEqual(first["task_id"], "task_A")
        self.assertTrue(first["event_id"])
        second = self.ingest(lease)
        self.assertEqual(second, dict(first, status="duplicate"))
        self.assertEqual(len(self.store.pending_returns()), 1)
        self.assertEqual(self.store.snapshot("task_A")["state"], "completed")

    def test_duplicate_after_expiry_and_reopen_is_stable(self):
        lease = self.claimed()
        first = self.ingest(lease)
        events = self.store.pending_returns()
        self.clock.value = 9000
        self.reopen()
        self.assertEqual(self.ingest(lease), dict(first, status="duplicate"))
        self.assertEqual(self.store.pending_returns(), events)

    def test_pending_event_exposes_original_complete_body(self):
        lease = self.claimed()
        result = self.ingest(lease)
        event = self.store.pending_returns()[0]
        for key, value in {"task_id": "task_A", "event_id": result["event_id"], "body": "synthetic complete answer",
                           "receiver": "Chat", "return_target": "DOT"}.items():
            self.assertEqual(event[key], value)

    def test_reply_identity_fields_must_match(self):
        lease = self.claimed()
        for change in ({"task_id": "other"}, {"nonce": "other"}, {"worker": "other"}, {"generation": 2}):
            self.reject_unchanged(lambda: self.ingest(lease, **change))

    def test_lease_identity_fields_must_match(self):
        lease = self.claimed()
        reply = self.reply(lease)
        for change in ({"task_id": "other"}, {"nonce": "other"}, {"worker": "other"}, {"generation": 2}):
            self.reject_unchanged(lambda: self.store.ingest(replace(lease, **change), Source("Chat", "conv_A"), reply))

    def test_source_binding_checked_separately(self):
        lease = self.claimed()
        for source in (Source("Work", "conv_A"), Source("Chat", "conv_B"), Source("chat", "conv_A")):
            self.reject_unchanged(lambda: self.store.ingest(lease, source, self.reply(lease)))

    def test_nonfinal_or_misdirected_replies_reject(self):
        lease = self.claimed()
        for changes in ({"complete": False}, {"complete": 1}, {"role": "user"}, {"status": "running"},
                        {"receiver": "DOT"}, {"return_target": "Work"}, {"role": "Assistant"},
                        {"status": "Completed"}, {"receiver": None}):
            self.reject_unchanged(lambda: self.ingest(lease, **changes))

    def test_body_type_empty_reference_and_size_reject(self):
        lease = self.claimed()
        for body in ("", None, b"abc", True, "::chatgpt-content-reference[synthetic]", "x" * 65537,
                     "é" * 32769, "\ud800"):
            with self.subTest(body_type=type(body).__name__, length=len(body) if isinstance(body, str) else 0):
                self.reject_unchanged(lambda: self.ingest(lease, body=body))

    def test_utf8_exact_byte_limit_allowed(self):
        lease = self.claimed()
        self.assertEqual(self.ingest(lease, body="é" * 32768)["status"], "recorded")

    def test_all_reply_identifiers_are_validated(self):
        lease = self.claimed()
        for field in ("task_id", "nonce", "worker", "message_id"):
            for value in ("", "a/b", "é", None, "x" * 129):
                self.reject_unchanged(lambda: self.ingest(lease, **{field: value}))

    def test_exact_integer_generation_required_on_both_objects(self):
        lease = self.claimed()
        for value in (True, False, 0, -1, 1.0, MAX + 1, None):
            self.reject_unchanged(lambda: self.ingest(lease, generation=value))
            self.reject_unchanged(lambda: self.store.ingest(replace(lease, generation=value), Source("Chat", "conv_A"), self.reply(lease)))

    def test_lease_until_requires_valid_integer_but_is_not_authority(self):
        lease = self.claimed()
        for value in (True, -1, 1.0, MAX + 1, None):
            self.reject_unchanged(lambda: self.store.ingest(replace(lease, lease_until_ms=value), Source("Chat", "conv_A"), self.reply(lease)))
        result = self.store.ingest(replace(lease, lease_until_ms=0), Source("Chat", "conv_A"), self.reply(lease))
        self.assertEqual(result["status"], "recorded")

    def test_wrong_public_object_types_reject(self):
        lease = self.claimed()
        for call in (lambda: self.store.renew({}, 10), lambda: self.store.ingest({}, Source("Chat", "conv_A"), self.reply(lease)),
                     lambda: self.store.ingest(lease, {}, self.reply(lease)),
                     lambda: self.store.ingest(lease, Source("Chat", "conv_A"), {})):
            self.reject_unchanged(call)

    def test_ingest_exactly_at_lease_expiry_rejects(self):
        lease = self.claimed()
        self.clock.value = 1100
        self.reject_unchanged(lambda: self.ingest(lease))

    def test_ingest_exactly_at_task_expiry_rejects(self):
        lease = self.claimed(ttl=50, lease_ms=100)
        self.clock.value = 1050
        self.reject_unchanged(lambda: self.ingest(lease))

    def test_old_worker_after_reclaim_cannot_ingest(self):
        lease = self.claimed()
        self.clock.value = 1100
        fresh = self.store.claim("task_A", "worker_B", 100)
        self.reject_unchanged(lambda: self.ingest(lease))
        self.assertEqual(self.ingest(fresh)["status"], "recorded")

    def test_completed_receipt_changes_are_conflicts(self):
        lease = self.claimed()
        self.ingest(lease)
        self.clock.value = 9000
        for change in ({"message_id": "other"}, {"body": "changed"}, {"nonce": "other"},
                       {"generation": 2}, {"worker": "other"}, {"complete": False}, {"return_target": "Work"}):
            self.reject_unchanged(lambda: self.ingest(lease, **change))
        self.reject_unchanged(lambda: self.store.ingest(lease, Source("Work", "conv_A"), self.reply(lease)))

    def test_native_message_tuple_unique_across_tasks(self):
        lease = self.claimed()
        self.ingest(lease)
        self.create("task_B", "nonce_B")
        other = self.store.claim("task_B", "worker_B", 100)
        before = self.store.snapshot("task_B")
        with self.assertRaises(ProtocolError):
            self.ingest(other)
        self.assertEqual(self.store.snapshot("task_B"), before)
        self.assertEqual(len(self.store.pending_returns()), 1)

    def test_same_message_id_on_distinct_native_tuple_allowed(self):
        self.ingest(self.claimed())
        self.create("task_B", "nonce_B", conversation="conv_B")
        lease = self.store.claim("task_B", "worker_B", 100)
        self.store.ingest(lease, Source("Chat", "conv_B"), self.reply(lease))
        self.assertEqual(len(self.store.pending_returns()), 2)

    def test_sha256_fingerprint_canonical_semantic_fields(self):
        lease = self.claimed()
        source = Source("Chat", "conv_A")
        reply = self.reply(lease)
        self.store.ingest(lease, source, reply)
        payload = {"source": {"surface": "Chat", "conversation_id": "conv_A"},
                   "claim": {"task_id": lease.task_id, "nonce": lease.nonce, "worker": lease.worker,
                             "generation": lease.generation},
                   "reply": {"task_id": reply.task_id, "nonce": reply.nonce, "worker": reply.worker,
                             "generation": reply.generation, "message_id": reply.message_id,
                             "body": reply.body, "receiver": reply.receiver, "return_target": reply.return_target,
                             "complete": reply.complete, "role": reply.role, "status": reply.status}}
        expected = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()
        with closing(sqlite3.connect(self.path)) as db, db:
            fingerprint = db.execute("SELECT fingerprint FROM results").fetchone()[0]
        self.assertEqual(fingerprint, expected)

    def test_informational_lease_time_does_not_change_fingerprint(self):
        lease = self.claimed()
        first = self.ingest(lease)
        changed = replace(lease, lease_until_ms=MAX)
        self.assertEqual(self.ingest(changed), dict(first, status="duplicate"))


class DurabilityTests(StoreTest):
    def test_lease_fence_and_result_survive_reopen(self):
        lease = self.claimed()
        self.reopen()
        self.assertEqual(self.store.snapshot("task_A")["generation"], 1)
        result = self.ingest(lease)
        before = self.store.pending_returns()
        self.reopen()
        self.assertEqual(self.store.pending_returns(), before)
        self.assertEqual(self.ingest(lease), dict(result, status="duplicate"))

    def test_failed_outbox_insert_rolls_back_result_and_completion(self):
        lease = self.claimed()
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("CREATE TRIGGER fail_outbox BEFORE INSERT ON outbox BEGIN SELECT RAISE(ABORT, 'synthetic fault'); END")
        before = self.store.snapshot("task_A")
        with self.assertRaises(sqlite3.DatabaseError):
            self.ingest(lease)
        self.assertEqual(self.store.snapshot("task_A"), before)
        self.assertEqual(self.store.pending_returns(), [])
        with closing(sqlite3.connect(self.path)) as db, db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM results").fetchone()[0], 0)
            db.execute("DROP TRIGGER fail_outbox")
        self.assertEqual(self.ingest(lease)["status"], "recorded")

    def test_process_crash_during_ingest_is_atomic(self):
        lease = self.claimed()
        self.store.close()
        script = """import os, sys
from candidate_protocol import Store, Lease, Source, Reply
s = Store(sys.argv[1], lambda: 1000)
s._conn.create_function('crash_now', 0, lambda: os._exit(73))
s._conn.execute('CREATE TRIGGER crash_outbox BEFORE INSERT ON outbox BEGIN SELECT crash_now(); END')
lease = Lease('task_A','nonce_A','worker_A',1,1100)
s.ingest(lease, Source('Chat','conv_A'), Reply('task_A','nonce_A',1,'worker_A','message_A','synthetic complete answer','Chat'))
"""
        proc = subprocess.run([sys.executable, "-B", "-c", script, str(self.path)], capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 73, proc.stderr)
        self.store = Store(self.path, self.clock)
        self.assertEqual(self.store.snapshot("task_A")["state"], "claimed")
        self.assertEqual(self.store.pending_returns(), [])
        with closing(sqlite3.connect(self.path)) as db, db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM results").fetchone()[0], 0)
            db.execute("DROP TRIGGER crash_outbox")
        self.assertEqual(self.ingest(lease)["status"], "recorded")

    def race(self, action):
        barrier = threading.Barrier(2)
        answers = []
        lock = threading.Lock()

        def worker(index):
            store = Store(self.path, lambda: 1000)
            try:
                barrier.wait(timeout=10)
                try:
                    answer = ("ok", action(store, index))
                except ProtocolError as error:
                    answer = ("rejected", error.code)
                except Exception as error:
                    answer = ("error", repr(error))
                with lock:
                    answers.append(answer)
            finally:
                store.close()

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)
            self.assertFalse(thread.is_alive(), "SQLite race failed to terminate")
        self.assertEqual(len(answers), 2)
        self.assertNotIn("error", [answer[0] for answer in answers], answers)
        return answers

    def test_separate_connections_racing_claim_only_one_wins(self):
        self.create()
        answers = self.race(lambda store, index: store.claim("task_A", "worker_" + str(index), 100))
        self.assertEqual(sorted(answer[0] for answer in answers), ["ok", "rejected"])
        self.assertEqual(self.store.snapshot("task_A")["generation"], 1)

    def test_separate_connections_racing_exact_ingest_have_one_result(self):
        lease = self.claimed()
        answers = self.race(lambda store, index: store.ingest(lease, Source("Chat", "conv_A"), self.reply(lease)))
        self.assertEqual(sorted(answer[1]["status"] for answer in answers), ["duplicate", "recorded"])
        self.assertEqual(len({answer[1]["event_id"] for answer in answers}), 1)
        self.assertEqual(len(self.store.pending_returns()), 1)

    def test_separate_connections_racing_conflicting_ingest_only_one_wins(self):
        lease = self.claimed()
        answers = self.race(lambda store, index: store.ingest(lease, Source("Chat", "conv_A"), self.reply(lease, body="synthetic_" + str(index))))
        self.assertEqual(sorted(answer[0] for answer in answers), ["ok", "rejected"])
        self.assertEqual(len(self.store.pending_returns()), 1)


if __name__ == "__main__":
    unittest.main()
