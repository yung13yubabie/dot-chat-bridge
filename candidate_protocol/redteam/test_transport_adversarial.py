"""Independent injected-transport counterexamples; no live provider actions.

Run with ``python -B -m candidate_protocol.redteam.test_transport_adversarial``.
Synthetic databases are retained in a named temporary evidence directory.
"""

from contextlib import closing
from copy import deepcopy
from dataclasses import replace
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
from types import SimpleNamespace
import unittest

from candidate_protocol import Store
from candidate_protocol.transport import Bridge, InjectedChatTransport


DATA = Path(os.environ.get("OFFLINE_TRANSPORT_REDTEAM_DATA", str(
    Path(tempfile.gettempdir()) / "dot-transport-redteam-synthetic-data")))
DATA.mkdir(parents=True, exist_ok=True)
EXPECTED = {"sum": 145, "min": 8, "max": 53}
INSTRUCTION = "Compute sum, min and max for values [17,41,8,26,53]. Return one JSON object."


class Clock:
    def __init__(self):
        self.now = 1000

    def __call__(self):
        return self.now


class TransportAdversarialTests(unittest.TestCase):
    def fixture(self, *, ttl=200000, lease_ms=150000, target="Chat"):
        directory = Path(tempfile.mkdtemp(prefix=self._testMethodName + "-", dir=DATA))
        f = SimpleNamespace(path=directory / "synthetic.sqlite", clock=Clock(), sent=[], reads=[])
        f.store = Store(f.path, f.clock)
        self.addCleanup(lambda: f.store.close())
        f.store.create("task_red", "nonce_red", target, "chat_synthetic", ttl)
        f.lease = f.store.claim("task_red", "worker_red", lease_ms)
        f.baseline = self.envelope({"thread": {"id": "chat_synthetic", "kind": "chatgpt"}, "turns": []})
        f.receipt = self.envelope({"threadId": "chat_synthetic", "kind": "chatgpt"})
        f.read_next = lambda: self.final_read(f)

        def send(arguments):
            f.sent.append(deepcopy(arguments))
            return deepcopy(f.receipt)

        def read(arguments):
            f.reads.append(deepcopy(arguments))
            if not f.sent:
                return deepcopy(f.baseline)
            return f.read_next()

        f.send = send
        f.read = read
        f.transport = InjectedChatTransport(send=send, read=read, fixture=True)
        f.bridge = Bridge(f.store, f.transport, validate_output=lambda output: output == EXPECTED)
        return f

    @staticmethod
    def envelope(payload):
        return {"fixture_only": True, "structuredContent": payload}

    def final_read(self, f, *, body=None, turn_id="turn_new", message_id="assistant_new"):
        if body is None:
            body = json.dumps({"task_id": f.lease.task_id, "nonce": f.lease.nonce,
                               "receiver": "Chat", "return_target": "DOT", "output": EXPECTED})
        return self.envelope({"thread": {"id": "chat_synthetic", "kind": "chatgpt"}, "turns": [
            {"id": turn_id, "status": "completed", "error": None, "items": [
                {"type": "userMessage", "id": "user_new", "content": [
                    {"type": "text", "text": f.sent[-1]["prompt"] if f.sent else INSTRUCTION}]},
                {"type": "agentMessage", "id": message_id, "text": body}]}]})

    @staticmethod
    def domain(f):
        with closing(sqlite3.connect(f.path)) as database:
            return {table: database.execute("SELECT * FROM " + table + " ORDER BY 1").fetchall()
                    for table in ("tasks", "results", "outbox")}

    def blocked(self, outcome):
        self.assertEqual(outcome["status"], "blocked", outcome)
        self.assertIsInstance(outcome.get("code"), str)
        self.assertTrue(outcome["code"])
        self.assertIs(outcome.get("live_verified"), False)

    def dispatch(self, f):
        outcome = f.bridge.dispatch(f.lease, INSTRUCTION)
        self.assertEqual(outcome["status"], "awaiting_result", outcome)
        self.assertIs(outcome.get("live_verified"), False)
        self.assertEqual(len(f.sent), 1)
        return outcome

    def reopen(self, f):
        f.store.close()
        f.store = Store(f.path, f.clock)
        f.bridge = Bridge(f.store, f.transport, validate_output=lambda output: output == EXPECTED)

    def reject_read(self, f, raw):
        before = self.domain(f)
        self.blocked(f.bridge.accept_read(f.lease, raw))
        self.assertEqual(self.domain(f), before)

    @staticmethod
    def at(raw, path):
        value = raw
        for key in path:
            value = value[key]
        return value

    def test_unwired_reports_blocked_without_domain_mutation(self):
        f = self.fixture()
        before = self.domain(f)
        self.blocked(Bridge(f.store).dispatch(f.lease, INSTRUCTION))
        self.assertEqual(self.domain(f), before)
        self.assertEqual((f.sent, f.reads), ([], []))

    def test_missing_validator_never_sends(self):
        f = self.fixture()
        before = self.domain(f)
        self.blocked(Bridge(f.store, f.transport).dispatch(f.lease, INSTRUCTION))
        self.assertEqual(self.domain(f), before)
        self.assertEqual((f.sent, f.reads), ([], []))

    def test_full_chain_records_once_and_exact_replay_survives_reopen(self):
        f = self.fixture()
        self.dispatch(f)
        raw = self.final_read(f)
        f.read_next = lambda: deepcopy(raw)
        first = f.bridge.poll(f.lease)
        self.assertEqual(first["status"], "recorded", first)
        self.assertIs(first.get("live_verified"), False)
        self.assertEqual(len(f.reads), 2)
        saved = self.domain(f)
        self.assertEqual((len(saved["results"]), len(saved["outbox"])), (1, 1))
        self.reopen(f)
        duplicate = f.bridge.accept_read(f.lease, deepcopy(raw))
        self.assertEqual(duplicate["status"], "duplicate", duplicate)
        self.assertEqual(duplicate["event_id"], first["event_id"])
        self.assertIs(duplicate.get("live_verified"), False)
        self.assertEqual(self.domain(f), saved)

    def test_send_uses_only_thread_and_prompt_and_no_disclosed_answers(self):
        f = self.fixture()
        self.dispatch(f)
        self.assertEqual(set(f.sent[0]), {"threadId", "prompt"})
        self.assertEqual(f.sent[0]["threadId"], "chat_synthetic")
        self.assertIn(INSTRUCTION, f.sent[0]["prompt"])
        self.assertIn(f.lease.task_id, f.sent[0]["prompt"])
        self.assertIn(f.lease.nonce, f.sent[0]["prompt"])
        self.assertNotIn('"sum": 145', f.sent[0]["prompt"])
        self.assertNotIn('"sum":145', f.sent[0]["prompt"])
        self.assertEqual(len(f.reads), 1, "dispatch must not auto-poll after its baseline")

    def test_requested_model_cannot_change_tool_model(self):
        f = self.fixture()
        outcome = f.bridge.dispatch(f.lease, INSTRUCTION, requested_model="synthetic_requested")
        self.assertIn(outcome["status"], ("blocked", "awaiting_result"))
        self.assertIs(outcome.get("live_verified"), False)
        for sent in f.sent:
            self.assertEqual(set(sent), {"threadId", "prompt"})
        self.assertLessEqual(len(f.sent), 1)

    def test_unreserved_result_cannot_be_ingested(self):
        f = self.fixture()
        self.reject_read(f, self.final_read(f))
        self.assertEqual((f.sent, f.reads), ([], []))

    def test_bad_baseline_blocks_before_send(self):
        cases = [((), "content_omitted", True), ((), "truncated", True),
                 ((), "cursor", "next_page"), (("structuredContent",), "content_omitted", True),
                 (("structuredContent",), "cursor", "next_page"),
                 (("structuredContent", "thread"), "id", "chat_other"),
                 (("structuredContent", "thread"), "kind", "codex"),
                 (("structuredContent",), "turns", "not_a_list"),
                 ((), "fixture_only", False), ((), "isError", True)]
        for path, key, value in cases:
            with self.subTest(path=path, key=key):
                f = self.fixture()
                self.at(f.baseline, path)[key] = value
                before = self.domain(f)
                self.blocked(f.bridge.dispatch(f.lease, INSTRUCTION))
                self.assertEqual(f.sent, [])
                self.assertEqual(self.domain(f), before)

    def test_omission_markers_at_each_layer_override_valid_body(self):
        paths = [(), ("structuredContent",), ("structuredContent", "thread"),
                 ("structuredContent", "turns", 0),
                 ("structuredContent", "turns", 0, "items", 0),
                 ("structuredContent", "turns", 0, "items", 0, "content", 0),
                 ("structuredContent", "turns", 0, "items", 1)]
        for path in paths:
            for key, value in (("content_omitted", True), ("truncated", True), ("cursor", "next_page")):
                with self.subTest(path=path, marker=key):
                    f = self.fixture()
                    self.dispatch(f)
                    raw = self.final_read(f)
                    self.at(raw, path)[key] = value
                    raw["snippet"] = self.final_read(f)["structuredContent"]["turns"][0]["items"][1]["text"]
                    self.reject_read(f, raw)

    def test_empty_reference_or_unparseable_body_never_uses_snippet(self):
        bodies = ["", " \n\t", "::chatgpt-content-reference synthetic", "not json", "[]", "null",
                  "{}", '{"task_id":', '{"task_id":"task_red"} {}']
        for body in bodies:
            with self.subTest(body=body):
                f = self.fixture()
                self.dispatch(f)
                raw = self.final_read(f, body=body)
                raw["snippet"] = self.final_read(f)["structuredContent"]["turns"][0]["items"][1]["text"]
                self.reject_read(f, raw)

    def test_duplicate_json_keys_and_nonfinite_values_reject(self):
        for fragment in ('"nonce":"stale","nonce":"nonce_red",',
                         '"nonce":"nonce_red","nonce":"nonce_red",',
                         '"output":{"sum":0,"sum":145,"min":8,"max":53},',
                         '"output":{"sum":NaN,"min":8,"max":53},',
                         '"output":{"sum":Infinity,"min":8,"max":53},'):
            with self.subTest(fragment=fragment):
                f = self.fixture()
                self.dispatch(f)
                prefix = '{"task_id":"task_red","receiver":"Chat","return_target":"DOT",'
                rest = ('"output":' + json.dumps(EXPECTED)) if fragment.startswith('"nonce"') else '"nonce":"nonce_red"'
                self.reject_read(f, self.final_read(f, body=prefix + fragment + rest + "}"))

    def test_payload_identity_shape_and_direction_are_exact(self):
        changes = [("task_id", "task_stale"), ("nonce", "nonce_stale"), ("receiver", "Work"),
                   ("return_target", "Chat"), ("output", []), ("output", None),
                   ("extra", True)]
        for key, value in changes:
            with self.subTest(key=key, value=value):
                f = self.fixture()
                self.dispatch(f)
                payload = json.loads(self.final_read(f)["structuredContent"]["turns"][0]["items"][1]["text"])
                payload[key] = value
                self.reject_read(f, self.final_read(f, body=json.dumps(payload)))
        for missing in ("task_id", "nonce", "receiver", "return_target", "output"):
            with self.subTest(missing=missing):
                f = self.fixture()
                self.dispatch(f)
                payload = json.loads(self.final_read(f)["structuredContent"]["turns"][0]["items"][1]["text"])
                del payload[missing]
                self.reject_read(f, self.final_read(f, body=json.dumps(payload)))

    def test_output_validator_must_return_the_boolean_true(self):
        for validation in (False, None, 1, "yes", {}):
            with self.subTest(validation=validation):
                f = self.fixture()
                f.bridge = Bridge(f.store, f.transport, validate_output=lambda output: validation)
                self.dispatch(f)
                self.reject_read(f, self.final_read(f))

    def test_wrong_output_and_validator_exception_fail_closed(self):
        f = self.fixture()
        self.dispatch(f)
        payload = json.loads(self.final_read(f)["structuredContent"]["turns"][0]["items"][1]["text"])
        payload["output"]["sum"] = 144
        self.reject_read(f, self.final_read(f, body=json.dumps(payload)))
        g = self.fixture()

        def broken_validator(output):
            raise RuntimeError("synthetic validator failure")

        g.bridge = Bridge(g.store, g.transport, validate_output=broken_validator)
        self.dispatch(g)
        self.reject_read(g, self.final_read(g))

    def test_wrong_source_status_role_or_prompt_rejects(self):
        changes = [(("structuredContent", "thread"), "id", "chat_other"),
                   (("structuredContent", "thread"), "kind", "codex"),
                   (("structuredContent", "turns", 0), "status", "queued"),
                   (("structuredContent", "turns", 0), "error", {"message": "synthetic error"}),
                   (("structuredContent", "turns", 0, "items", 1), "type", "userMessage"),
                   (("structuredContent", "turns", 0, "items", 0, "content", 0), "text", "old prompt"),
                   (("structuredContent", "turns", 0, "items", 0), "type", "agentMessage")]
        for path, key, value in changes:
            with self.subTest(path=path, key=key):
                f = self.fixture()
                self.dispatch(f)
                raw = self.final_read(f)
                self.at(raw, path)[key] = value
                self.reject_read(f, raw)

    def test_provisional_missing_or_ambiguous_identifiers_reject(self):
        paths = [("structuredContent", "thread"), ("structuredContent", "turns", 0),
                 ("structuredContent", "turns", 0, "items", 0),
                 ("structuredContent", "turns", 0, "items", 1)]
        for path in paths:
            for identifier in (None, "", "local-chatgpt:synthetic", "ambiguous id"):
                with self.subTest(path=path, identifier=identifier):
                    f = self.fixture()
                    self.dispatch(f)
                    raw = self.final_read(f)
                    self.at(raw, path)["id"] = identifier
                    self.reject_read(f, raw)

    def test_baseline_turn_cannot_be_reused_even_with_new_correct_body(self):
        f = self.fixture()
        f.baseline["structuredContent"]["turns"] = [{
            "id": "turn_prior", "status": "completed", "error": None, "items": []}]
        self.dispatch(f)
        self.reject_read(f, self.final_read(f, turn_id="turn_prior"))

    def test_split_turn_and_multiple_candidate_results_reject(self):
        for mode in ("split_turn", "two_turns", "two_agents"):
            with self.subTest(mode=mode):
                f = self.fixture()
                self.dispatch(f)
                raw = self.final_read(f)
                turns = raw["structuredContent"]["turns"]
                if mode == "split_turn":
                    agent = turns[0]["items"].pop()
                    turns.append({"id": "turn_other", "status": "completed", "error": None, "items": [agent]})
                elif mode == "two_turns":
                    other = deepcopy(turns[0])
                    other["id"] = "turn_other"
                    other["items"][0]["id"] = "user_other"
                    other["items"][1]["id"] = "assistant_other"
                    turns.append(other)
                else:
                    other = deepcopy(turns[0]["items"][1])
                    other["id"] = "assistant_other"
                    turns[0]["items"].append(other)
                self.reject_read(f, raw)

    def test_fixture_marker_and_error_flags_are_not_success_evidence(self):
        for path, key, value in [((), "fixture_only", False), ((), "fixture_only", 1),
                                 ((), "isError", True), ((), "success", False),
                                 (("structuredContent",), "success", False),
                                 (("structuredContent", "turns", 0), "success", False),
                                 (("structuredContent", "turns", 0, "items", 1), "success", False)]:
            with self.subTest(path=path, key=key, value=value):
                f = self.fixture()
                self.dispatch(f)
                raw = self.final_read(f)
                self.at(raw, path)[key] = value
                self.reject_read(f, raw)

    def test_unique_json_text_envelopes_are_supported_without_structured_content(self):
        f = self.fixture()

        def fallback(raw):
            return {"fixture_only": True, "content": [
                {"type": "text", "text": json.dumps(raw["structuredContent"])}]}

        f.baseline = fallback(f.baseline)
        f.receipt = fallback(f.receipt)
        self.dispatch(f)
        outcome = f.bridge.accept_read(f.lease, fallback(self.final_read(f)))
        self.assertEqual(outcome["status"], "recorded", outcome)
        self.assertIs(outcome.get("live_verified"), False)

    def test_ambiguous_or_non_json_text_envelopes_reject(self):
        for mode in ("two_json", "extra_text", "not_json", "duplicate_keys"):
            with self.subTest(mode=mode):
                f = self.fixture()
                self.dispatch(f)
                payload = self.final_read(f)["structuredContent"]
                text = json.dumps(payload)
                if mode == "not_json":
                    text = "summary with expected answer"
                elif mode == "duplicate_keys":
                    text = '{"thread":null,' + text[1:]
                content = [{"type": "text", "text": text}]
                if mode in ("two_json", "extra_text"):
                    content.append({"type": "text", "text": text if mode == "two_json" else "summary"})
                self.reject_read(f, {"fixture_only": True, "content": content})

    def test_malformed_raw_envelopes_never_raise_or_ingest(self):
        for raw in (None, "text", [], {}, {"fixture_only": True, "structuredContent": []},
                    {"fixture_only": True, "structuredContent": {"thread": None, "turns": []}}):
            with self.subTest(raw=raw):
                f = self.fixture()
                self.dispatch(f)
                self.reject_read(f, raw)

    def test_malformed_or_wrong_dispatch_receipt_cannot_claim_success(self):
        receipts = [None, {}, self.envelope({"threadId": "chat_other", "kind": "chatgpt"}),
                    self.envelope({"threadId": "local-chatgpt:synthetic", "kind": "chatgpt"}),
                    self.envelope({"success": True}),
                    self.envelope({"threadId": "chat_synthetic", "success": False}),
                    {"fixture_only": True, "isError": True, "structuredContent": {"threadId": "chat_synthetic"}}]
        for receipt in receipts:
            with self.subTest(receipt=receipt):
                f = self.fixture()
                f.receipt = receipt
                before = self.domain(f)
                outcome = f.bridge.dispatch(f.lease, INSTRUCTION)
                self.assertIn(outcome["status"], ("blocked", "uncertain"), outcome)
                self.assertIs(outcome.get("live_verified"), False)
                self.assertEqual(self.domain(f), before)
                self.assertEqual(len(f.sent), 1)
                self.reopen(f)
                again = f.bridge.dispatch(f.lease, INSTRUCTION)
                self.assertIn(again["status"], ("blocked", "uncertain"), again)
                self.assertEqual(len(f.sent), 1)

    def test_uncertain_send_is_reserved_across_reopen_without_resend(self):
        f = self.fixture()

        def uncertain(arguments):
            f.sent.append(deepcopy(arguments))
            raise TimeoutError("synthetic send may have happened")

        f.transport = InjectedChatTransport(send=uncertain, read=f.read, fixture=True)
        f.bridge = Bridge(f.store, f.transport, validate_output=lambda output: output == EXPECTED)
        before = self.domain(f)
        outcome = f.bridge.dispatch(f.lease, INSTRUCTION)
        self.assertEqual(outcome["status"], "uncertain", outcome)
        self.assertIs(outcome.get("live_verified"), False)
        self.assertEqual(self.domain(f), before)
        self.reopen(f)
        repeated = f.bridge.dispatch(f.lease, INSTRUCTION)
        self.assertIn(repeated["status"], ("blocked", "uncertain"), repeated)
        self.assertEqual(len(f.sent), 1)
        self.assertEqual(self.domain(f), before)

    def test_crash_during_send_does_not_release_reservation(self):
        f = self.fixture()

        def stopped(arguments):
            f.sent.append(deepcopy(arguments))
            raise SystemExit("synthetic process stop")

        f.transport = InjectedChatTransport(send=stopped, read=f.read, fixture=True)
        f.bridge = Bridge(f.store, f.transport, validate_output=lambda output: output == EXPECTED)
        try:
            outcome = f.bridge.dispatch(f.lease, INSTRUCTION)
            self.assertIn(outcome["status"], ("blocked", "uncertain"))
        except SystemExit:
            pass
        self.reopen(f)
        outcome = f.bridge.dispatch(f.lease, INSTRUCTION)
        self.assertIn(outcome["status"], ("blocked", "uncertain"))
        self.assertEqual(len(f.sent), 1)
        self.assertEqual(f.store.pending_returns(), [])

    def test_reservation_is_committed_before_send_io(self):
        f = self.fixture()
        nested = []

        def reentrant(arguments):
            f.sent.append(deepcopy(arguments))
            if len(f.sent) == 1:
                with closing(Store(f.path, f.clock)) as other:
                    nested.append(Bridge(other, f.transport, validate_output=lambda output: output == EXPECTED)
                                  .dispatch(f.lease, INSTRUCTION))
            return deepcopy(f.receipt)

        f.transport = InjectedChatTransport(send=reentrant, read=f.read, fixture=True)
        f.bridge = Bridge(f.store, f.transport, validate_output=lambda output: output == EXPECTED)
        self.dispatch(f)
        self.assertEqual(len(nested), 1)
        self.assertIn(nested[0]["status"], ("blocked", "uncertain"))
        self.assertEqual(len(f.sent), 1)

    def test_each_poll_has_one_read_and_budget_survives_reopen(self):
        f = self.fixture()
        self.dispatch(f)
        f.read_next = lambda: self.envelope({"thread": {"id": "chat_synthetic", "kind": "chatgpt"}, "turns": []})
        for _ in range(5):
            before = len(f.reads)
            outcome = f.bridge.poll(f.lease)
            self.assertIn(outcome["status"], ("blocked", "awaiting_result"))
            self.assertLessEqual(len(f.reads) - before, 1)
            self.assertLessEqual(len(f.reads), 4)
            self.reopen(f)
        self.assertEqual(len(f.sent), 1)
        self.assertEqual(f.store.pending_returns(), [])

    def test_crashed_reads_consume_durable_budget_before_io(self):
        f = self.fixture()
        self.dispatch(f)

        def stopped_read():
            raise SystemExit("synthetic read process stop")

        f.read_next = stopped_read
        for _ in range(5):
            try:
                outcome = f.bridge.poll(f.lease)
                self.assertIn(outcome["status"], ("blocked", "awaiting_result"))
            except SystemExit:
                pass
            self.reopen(f)
        self.assertLessEqual(len(f.reads), 4, "baseline plus at most three reserved reads")
        self.assertEqual(f.store.pending_returns(), [])

    def test_ninety_second_and_earlier_lease_deadlines_stop_before_read(self):
        for lease_ms, elapsed in ((150000, 90000), (50, 50)):
            with self.subTest(lease_ms=lease_ms):
                f = self.fixture(lease_ms=lease_ms)
                self.dispatch(f)
                f.clock.now += elapsed
                before = self.domain(f)
                reads = len(f.reads)
                self.blocked(f.bridge.poll(f.lease))
                self.assertEqual(len(f.reads), reads)
                self.assertEqual(self.domain(f), before)

    def test_read_finishing_after_deadline_cannot_be_ingested(self):
        f = self.fixture()
        self.dispatch(f)

        def late_read():
            raw = self.final_read(f)
            f.clock.now += 90000
            return raw

        f.read_next = late_read
        before = self.domain(f)
        self.blocked(f.bridge.poll(f.lease))
        self.assertEqual(self.domain(f), before)

    def test_expired_cancelled_work_or_wrong_lease_never_dispatch(self):
        for state in ("expired", "cancelled", "work", "wrong_worker", "wrong_generation", "wrong_nonce"):
            with self.subTest(state=state):
                f = self.fixture(target="Work" if state == "work" else "Chat")
                lease = f.lease
                if state == "expired":
                    f.clock.now += 150000
                elif state == "cancelled":
                    f.store.cancel(lease.task_id)
                elif state == "wrong_worker":
                    lease = replace(lease, worker="worker_other")
                elif state == "wrong_generation":
                    lease = replace(lease, generation=2)
                elif state == "wrong_nonce":
                    lease = replace(lease, nonce="nonce_other")
                before = self.domain(f)
                self.blocked(f.bridge.dispatch(lease, INSTRUCTION))
                self.assertEqual(f.sent, [])
                if state != "expired":
                    self.assertEqual(f.reads, [])
                self.assertEqual(self.domain(f), before)

    def test_changed_replay_cannot_replace_completed_result(self):
        f = self.fixture()
        self.dispatch(f)
        raw = self.final_read(f)
        first = f.bridge.accept_read(f.lease, deepcopy(raw))
        self.assertEqual(first["status"], "recorded", first)
        for path, key, value in [(("structuredContent", "turns", 0, "items", 1), "id", "assistant_other"),
                                 (("structuredContent", "thread"), "id", "chat_other")]:
            with self.subTest(path=path):
                changed = deepcopy(raw)
                self.at(changed, path)[key] = value
                self.reject_read(f, changed)

    def test_malformed_item_types_are_blocked_not_uncaught_type_errors(self):
        for value in ([], {}, ["agentMessage"]):
            with self.subTest(value=value):
                f = self.fixture()
                self.dispatch(f)
                raw = self.final_read(f)
                raw["structuredContent"]["turns"][0]["items"][1]["type"] = value
                self.reject_read(f, raw)

    def test_malformed_baseline_status_is_blocked_before_send(self):
        for value in ([], {}, ["completed"]):
            with self.subTest(value=value):
                f = self.fixture()
                f.baseline["structuredContent"]["turns"] = [{
                    "id": "turn_prior", "status": value, "error": None, "items": []}]
                before = self.domain(f)
                self.blocked(f.bridge.dispatch(f.lease, INSTRUCTION))
                self.assertEqual(f.sent, [])
                self.assertEqual(self.domain(f), before)

    def test_conflicting_structured_and_json_text_payloads_reject(self):
        for variant in ("different_thread", "different_body", "different_turn"):
            with self.subTest(variant=variant):
                f = self.fixture()
                self.dispatch(f)
                raw = self.final_read(f)
                alternate = deepcopy(raw["structuredContent"])
                if variant == "different_thread":
                    alternate["thread"]["id"] = "chat_other"
                elif variant == "different_body":
                    alternate["turns"][0]["items"][1]["text"] = "{}"
                else:
                    alternate["turns"][0]["id"] = "turn_other"
                raw["content"] = [{"type": "text", "text": json.dumps(alternate)}]
                self.reject_read(f, raw)

    def test_direct_callback_after_deadline_is_rejected(self):
        f = self.fixture()
        self.dispatch(f)
        raw = self.final_read(f)
        f.clock.now += 90000
        self.reject_read(f, raw)
        self.assertEqual(len(f.reads), 1)

    def test_uncertain_attempt_blocks_new_claim_generation_after_reopen(self):
        f = self.fixture(lease_ms=50)

        def uncertain(arguments):
            f.sent.append(deepcopy(arguments))
            raise TimeoutError("synthetic uncertain send")

        f.transport = InjectedChatTransport(send=uncertain, read=f.read, fixture=True)
        f.bridge = Bridge(f.store, f.transport, validate_output=lambda output: output == EXPECTED)
        self.assertEqual(f.bridge.dispatch(f.lease, INSTRUCTION)["status"], "uncertain")
        f.clock.now += 50
        self.reopen(f)
        newer = f.store.claim(f.lease.task_id, "worker_new", 1000)
        self.blocked(f.bridge.dispatch(newer, INSTRUCTION))
        self.assertEqual(len(f.sent), 1)
        self.assertEqual(len(f.reads), 1)
        self.assertEqual(f.store.pending_returns(), [])

    def test_contradictory_explicit_message_role_or_status_rejects(self):
        for index, field, value in ((0, "role", "assistant"), (1, "role", "user"),
                                    (1, "status", "running"), (1, "phase", "analysis")):
            with self.subTest(index=index, field=field):
                f = self.fixture()
                self.dispatch(f)
                raw = self.final_read(f)
                raw["structuredContent"]["turns"][0]["items"][index][field] = value
                self.reject_read(f, raw)

    def test_completed_reply_cannot_move_to_another_turn_or_user(self):
        f = self.fixture()
        self.dispatch(f)
        original = self.final_read(f)
        self.assertEqual(f.bridge.accept_read(f.lease, deepcopy(original))["status"], "recorded")
        for field in ("turn", "user"):
            with self.subTest(field=field):
                raw = deepcopy(original)
                turn = raw["structuredContent"]["turns"][0]
                if field == "turn":
                    turn["id"] = "turn_rebound"
                else:
                    turn["items"][0]["id"] = "user_rebound"
                self.reject_read(f, raw)

    def test_message_ids_from_baseline_cannot_reappear_in_a_new_turn(self):
        f = self.fixture()
        f.baseline["structuredContent"]["turns"] = [{
            "id": "turn_prior", "status": "completed", "error": None, "items": [
                {"type": "userMessage", "id": "user_prior", "content": [
                    {"type": "text", "text": "unrelated historical synthetic request"}]},
                {"type": "agentMessage", "id": "assistant_new", "text": "historical synthetic body"}]}]
        self.dispatch(f)
        self.reject_read(f, self.final_read(f))

    def test_transport_binding_rolls_back_with_result_and_outbox_failure(self):
        f = self.fixture()
        self.dispatch(f)
        before = self.domain(f)
        f.store._conn.execute("""CREATE TRIGGER synthetic_outbox_failure BEFORE INSERT ON outbox
            BEGIN SELECT RAISE(ABORT, 'synthetic rollback'); END""")
        try:
            outcome = f.bridge.accept_read(f.lease, self.final_read(f))
            self.blocked(outcome)
        except sqlite3.DatabaseError:
            # Database faults may propagate, but all local protocol state must roll back.
            pass
        self.assertEqual(self.domain(f), before)
        f.store._conn.execute("DROP TRIGGER synthetic_outbox_failure")
        self.reopen(f)
        alternate = self.final_read(f, turn_id="turn_after_rollback")
        alternate["structuredContent"]["turns"][0]["items"][0]["id"] = "user_after_rollback"
        outcome = f.bridge.accept_read(f.lease, alternate)
        self.assertEqual(outcome["status"], "recorded", outcome)
        saved = self.domain(f)
        self.assertEqual((len(saved["results"]), len(saved["outbox"])), (1, 1))

    def test_conflicting_concurrent_callback_sources_cannot_both_bind(self):
        f = self.fixture()
        self.dispatch(f)
        barrier = threading.Barrier(2)
        outcomes = [None, None]
        raws = [self.final_read(f, turn_id="turn_race_A"), self.final_read(f, turn_id="turn_race_B")]
        raws[1]["structuredContent"]["turns"][0]["items"][0]["id"] = "user_race_B"

        def worker(index):
            try:
                with closing(Store(f.path, f.clock)) as store:
                    bridge = Bridge(store, f.transport, validate_output=lambda output: output == EXPECTED)
                    barrier.wait(timeout=5)
                    outcomes[index] = bridge.accept_read(f.lease, raws[index])
            except BaseException as error:
                outcomes[index] = {"status": "unexpected", "error": repr(error)}

        workers = [threading.Thread(target=worker, args=(index,), daemon=True) for index in range(2)]
        for worker_thread in workers:
            worker_thread.start()
        for worker_thread in workers:
            worker_thread.join(timeout=12)
            self.assertFalse(worker_thread.is_alive(), "bounded callback race did not finish")
        self.assertEqual(sorted(outcome["status"] for outcome in outcomes), ["blocked", "recorded"], outcomes)
        saved = self.domain(f)
        self.assertEqual((len(saved["results"]), len(saved["outbox"])), (1, 1))


if __name__ == "__main__":
    unittest.main(verbosity=2)
