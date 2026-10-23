"""Fixture integration tests; no callback here contacts a provider."""

from copy import deepcopy
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from candidate_protocol import Store
from candidate_protocol.transport import Bridge, InjectedChatTransport


def envelope(payload):
    return {"fixture_only": True, "isError": False, "structuredContent": payload}


def receiver(prompt, body=None, turn="turn_new"):
    if body is None:
        body = json.dumps({"task_id": "task_A", "nonce": "nonce_A", "receiver": "Chat",
                           "return_target": "DOT", "output": {"sum": 145, "min": 8, "max": 53}})
    return envelope({"thread": {"id": "conversation_A", "kind": "chatgpt"},
                     "truncated": False, "content_omitted": False,
                     "turns": [{"id": turn, "status": "completed", "error": None,
                                "items": [{"type": "userMessage", "id": "user_A",
                                           "content": [{"type": "text", "text": prompt}]},
                                          {"type": "agentMessage", "id": "assistant_A", "text": body}]}]})


class NativeFixture:
    """Synthetic values in the saved native MCP response shape, never live evidence."""

    def __init__(self):
        self.sent, self.reads = [], []
        self.receipt = envelope({"threadId": "conversation_A", "kind": "chatgpt"})
        self.response = None
        self.send_error = None
        self.read_error = None

    def send(self, arguments):
        self.sent.append(deepcopy(arguments))
        if self.send_error:
            raise self.send_error
        return deepcopy(self.receipt)

    def read(self, arguments):
        self.reads.append(deepcopy(arguments))
        if self.read_error:
            raise self.read_error
        if self.response is not None:
            return deepcopy(self.response)
        if not self.sent:
            return envelope({"thread": {"id": "conversation_A", "kind": "chatgpt"},
                             "turns": [], "truncated": False, "content_omitted": False})
        return receiver(self.sent[-1]["prompt"])


class TransportIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="transport-fixture-")
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "fixture.sqlite"
        self.now = 1000
        self.store = Store(self.path, lambda: self.now)
        self.addCleanup(lambda: self.store.close())
        self.store.create("task_A", "nonce_A", "Chat", "conversation_A", 200000)
        self.lease = self.store.claim("task_A", "worker_A", 150000)
        self.native = NativeFixture()
        self.transport = InjectedChatTransport(send=self.native.send, read=self.native.read, fixture=True)
        self.validator = lambda output: output == {"sum": 145, "min": 8, "max": 53}
        self.bridge = Bridge(self.store, self.transport, validate_output=self.validator)

    def dispatch(self):
        return self.bridge.dispatch(self.lease, "Compute sum, min and max for [17,41,8,26,53].")

    def assert_unrecorded(self):
        self.assertEqual(self.store.snapshot("task_A")["state"], "claimed")
        self.assertEqual(self.store.pending_returns(), [])

    def body(self):
        return receiver(self.native.sent[-1]["prompt"])

    def test_dispatch_receipt_is_not_completion(self):
        result = self.dispatch()
        self.assertEqual(result["status"], "awaiting_result")
        self.assertFalse(result["live_verified"])
        self.assert_unrecorded()
        self.assertEqual(set(self.native.sent[0]), {"threadId", "prompt"})
        self.assertEqual(self.native.reads[0]["maxOutputCharsPerItem"], 20000)

    def test_complete_fixture_chain_records_one_result_and_pending_return(self):
        self.dispatch()
        result = self.bridge.poll(self.lease)
        self.assertEqual(result["status"], "recorded")
        self.assertEqual(result["scope"], "candidate_transport_fixture")
        self.assertFalse(result["live_verified"])
        self.assertEqual(self.store.snapshot("task_A")["state"], "completed")
        self.assertEqual(len(self.store.pending_returns()), 1)
        event = self.store.pending_returns()[0]
        self.assertEqual(event["return_target"], "DOT")
        self.assertEqual(event["receiver"], "Chat")
        self.assertEqual(json.loads(event["body"])["output"], {"sum": 145, "min": 8, "max": 53})
        with closing(sqlite3.connect(self.path)) as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM results").fetchone()[0], 1)

    def test_exact_callback_replay_has_one_stable_event(self):
        self.dispatch()
        raw = self.body()
        first = self.bridge.accept_read(self.lease, raw)
        self.now += 300000
        duplicate = self.bridge.accept_read(self.lease, raw)
        self.assertEqual(duplicate["status"], "duplicate")
        self.assertEqual(duplicate["event_id"], first["event_id"])
        self.assertEqual(len(self.store.pending_returns()), 1)

    def test_changed_callback_after_completion_is_rejected(self):
        self.dispatch()
        self.bridge.accept_read(self.lease, self.body())
        changed = self.body()
        changed["structuredContent"]["turns"][0]["items"][-1]["id"] = "assistant_B"
        self.assertEqual(self.bridge.accept_read(self.lease, changed)["status"], "blocked")
        self.assertEqual(len(self.store.pending_returns()), 1)

    def test_unwired_transport_is_blocked_without_io(self):
        bridge = Bridge(self.store, validate_output=self.validator)
        self.assertEqual(bridge.dispatch(self.lease, "synthetic instruction")["status"], "blocked")
        self.assertEqual(bridge.poll(self.lease)["status"], "blocked")
        self.assertEqual(bridge.accept_read(self.lease, receiver("not sent"))["status"], "blocked")
        self.assertEqual(self.native.sent, [])
        self.assertEqual(self.native.reads, [])
        self.assert_unrecorded()

    def test_missing_output_validator_is_blocked_before_send(self):
        bridge = Bridge(self.store, self.transport)
        self.assertEqual(bridge.dispatch(self.lease, "synthetic instruction")["status"], "blocked")
        self.assertEqual(self.native.sent, [])

    def test_model_request_is_recorded_but_not_routed_or_guessed(self):
        result = self.bridge.dispatch(self.lease, "synthetic instruction", requested_model="requested_fixture_model")
        self.assertEqual(result["requested_model"], "requested_fixture_model")
        self.assertEqual(result["model_policy"], "inherit_conversation")
        self.assertIsNone(result["actual_model"])
        self.assertEqual(set(self.native.sent[0]), {"threadId", "prompt"})

    def test_baseline_failure_cannot_send(self):
        self.native.read_error = TimeoutError()
        self.assertEqual(self.dispatch()["status"], "blocked")
        self.assertEqual(self.native.sent, [])
        self.assert_unrecorded()

    def test_uncertain_send_is_persistent_and_never_retried(self):
        self.native.send_error = TimeoutError()
        self.assertEqual(self.dispatch()["status"], "uncertain")
        self.store.close()
        self.store = Store(self.path, lambda: self.now)
        self.bridge = Bridge(self.store, self.transport, validate_output=self.validator)
        self.native.send_error = None
        self.assertEqual(self.dispatch()["status"], "blocked")
        self.assertEqual(self.bridge.poll(self.lease)["status"], "blocked")
        self.assertEqual(len(self.native.sent), 1)
        self.assert_unrecorded()

    def test_formal_receipt_must_match_bound_conversation(self):
        for receipt in ({"threadId": "other_conversation"}, {"clientThreadId": "client_fixture"},
                        {"threadId": "local-chatgpt:fixture"}, {"threadId": "conversation_A", "kind": "codex"}):
            with self.subTest(receipt=receipt):
                # Each case uses a fresh isolated store and task; never resubmit a prior attempt.
                with tempfile.TemporaryDirectory() as folder:
                    with self.subTest(folder="synthetic"):
                        store = Store(Path(folder) / "case.sqlite", lambda: self.now)
                        try:
                            store.create("task_A", "nonce_A", "Chat", "conversation_A", 200000)
                            lease = store.claim("task_A", "worker_A", 150000)
                            native = NativeFixture()
                            native.receipt = envelope(receipt)
                            bridge = Bridge(store, InjectedChatTransport(send=native.send, read=native.read),
                                            validate_output=self.validator)
                            self.assertEqual(bridge.dispatch(lease, "synthetic")["status"], "uncertain")
                            self.assertEqual(bridge.poll(lease)["status"], "blocked")
                            self.assertEqual(store.pending_returns(), [])
                        finally:
                            store.close()

    def test_omission_at_any_layer_defeats_matching_body_and_snippet(self):
        self.dispatch()
        for layer in ("outer", "payload", "thread", "turn", "assistant"):
            raw = self.body()
            payload = raw["structuredContent"]
            record = {"outer": raw, "payload": payload, "thread": payload["thread"],
                      "turn": payload["turns"][0], "assistant": payload["turns"][0]["items"][-1]}[layer]
            record["content_omitted"] = True
            record["snippet"] = payload["turns"][0]["items"][-1]["text"]
            with self.subTest(layer=layer):
                self.assertEqual(self.bridge.accept_read(self.lease, raw)["status"], "blocked")
                self.assert_unrecorded()

    def test_incomplete_body_variants_fail_closed(self):
        self.dispatch()
        for body in ("", "   ", "::chatgpt-content-reference{source_message_id=fixture}",
                     "not JSON", "```json\n{}\n```", "null", "[]"):
            with self.subTest(body=body):
                self.assertEqual(self.bridge.accept_read(self.lease, receiver(self.native.sent[0]["prompt"], body))["status"], "blocked")
                self.assert_unrecorded()

    def test_identity_and_output_validation_rejects_wrong_results(self):
        self.dispatch()
        original = json.loads(self.body()["structuredContent"]["turns"][0]["items"][-1]["text"])
        for key, value in (("task_id", "task_old"), ("nonce", "nonce_old"), ("receiver", "Work"),
                           ("return_target", "Chat"), ("output", {"sum": 42})):
            data = dict(original, **{key: value})
            with self.subTest(key=key):
                result = self.bridge.accept_read(self.lease, receiver(self.native.sent[0]["prompt"], json.dumps(data)))
                self.assertEqual(result["status"], "blocked")
                self.assert_unrecorded()

    def test_duplicate_json_keys_and_nonfinite_numbers_are_rejected(self):
        self.dispatch()
        body = self.body()["structuredContent"]["turns"][0]["items"][-1]["text"]
        for altered in (body[:-1] + ',"nonce":"nonce_A"}', body.replace('145', 'NaN')):
            with self.subTest(body=altered):
                self.assertEqual(self.bridge.accept_read(self.lease, receiver(self.native.sent[0]["prompt"], altered))["status"], "blocked")
                self.assert_unrecorded()

    def test_source_and_final_turn_binding_are_required(self):
        self.dispatch()
        for change in ("conversation", "kind", "prompt", "status", "role", "phase"):
            raw = self.body()
            payload = raw["structuredContent"]
            turn = payload["turns"][0]
            if change == "conversation": payload["thread"]["id"] = "other_conversation"
            if change == "kind": payload["thread"]["kind"] = "codex"
            if change == "prompt": turn["items"][0]["content"][0]["text"] += " changed"
            if change == "status": turn["status"] = "running"
            if change == "role": turn["items"][-1]["role"] = "user"
            if change == "phase": turn["items"][-1]["phase"] = "analysis"
            with self.subTest(change=change):
                self.assertEqual(self.bridge.accept_read(self.lease, raw)["status"], "blocked")
                self.assert_unrecorded()

    def test_tool_error_or_truncation_cannot_be_success(self):
        self.dispatch()
        for key, value in (("isError", True), ("truncated", True), ("nextCursor", "more")):
            raw = self.body()
            raw[key] = value
            raw["success"] = True
            with self.subTest(key=key):
                self.assertEqual(self.bridge.accept_read(self.lease, raw)["status"], "blocked")
                self.assert_unrecorded()

    def test_post_dispatch_reads_are_bounded_and_timeouts_count(self):
        self.dispatch()
        self.native.read_error = TimeoutError()
        for _ in range(3):
            self.assertEqual(self.bridge.poll(self.lease)["status"], "blocked")
        before = len(self.native.reads)
        self.assertEqual(self.bridge.poll(self.lease)["status"], "blocked")
        self.assertEqual(len(self.native.reads), before)
        self.assertEqual(before, 4)  # one baseline + three post-dispatch attempts
        self.assertEqual(len(self.native.sent), 1)
        self.assert_unrecorded()

    def test_exact_deadline_does_not_read_or_ingest(self):
        self.dispatch()
        self.now += 90000
        before = len(self.native.reads)
        self.assertEqual(self.bridge.poll(self.lease)["status"], "blocked")
        self.assertEqual(len(self.native.reads), before)
        self.assertEqual(self.bridge.accept_read(self.lease, self.body())["status"], "blocked")
        self.assert_unrecorded()

    def test_cancel_and_expired_fence_reject_before_external_send(self):
        self.store.cancel("task_A")
        self.assertEqual(self.dispatch()["status"], "blocked")
        self.assertEqual(self.native.sent, [])

    def test_work_is_explicitly_unwired_in_this_chat_adapter(self):
        self.store.create("task_W", "nonce_W", "Work", "conversation_W", 200000)
        lease = self.store.claim("task_W", "worker_A", 100000)
        self.assertEqual(self.bridge.dispatch(lease, "synthetic")["status"], "blocked")
        self.assertEqual(self.native.sent, [])

    def test_text_json_tool_envelope_is_supported_without_snippet_fallback(self):
        self.dispatch()
        payload = self.body()["structuredContent"]
        raw = {"fixture_only": True, "isError": False,
               "content": [{"type": "text", "text": json.dumps(payload)}]}
        self.assertEqual(self.bridge.accept_read(self.lease, raw)["status"], "recorded")

    def test_restart_keeps_receipt_and_read_budget(self):
        self.dispatch()
        self.store.close()
        self.store = Store(self.path, lambda: self.now)
        self.bridge = Bridge(self.store, self.transport, validate_output=self.validator)
        self.assertEqual(self.dispatch()["status"], "blocked")
        self.assertEqual(len(self.native.sent), 1)
        self.assertEqual(self.bridge.poll(self.lease)["status"], "recorded")

    def test_malformed_native_field_types_are_rejections_not_exceptions(self):
        self.dispatch()
        for field in ("turn_status", "item_type", "thread", "items", "turns"):
            raw = self.body()
            payload = raw["structuredContent"]
            if field == "turn_status": payload["turns"][0]["status"] = {}
            if field == "item_type": payload["turns"][0]["items"][-1]["type"] = {}
            if field == "thread": payload["thread"] = []
            if field == "items": payload["turns"][0]["items"] = None
            if field == "turns": payload["turns"] = {}
            with self.subTest(field=field):
                self.assertEqual(self.bridge.accept_read(self.lease, raw)["status"], "blocked")
                self.assert_unrecorded()

    def test_replay_cannot_move_reply_to_another_turn_or_request_message(self):
        self.dispatch()
        raw = self.body()
        self.assertEqual(self.bridge.accept_read(self.lease, raw)["status"], "recorded")
        for field in ("turn", "user"):
            moved = deepcopy(raw)
            turn = moved["structuredContent"]["turns"][0]
            if field == "turn": turn["id"] = "turn_other"
            if field == "user": turn["items"][0]["id"] = "user_other"
            with self.subTest(field=field):
                self.assertEqual(self.bridge.accept_read(self.lease, moved)["status"], "blocked")
                self.assertEqual(len(self.store.pending_returns()), 1)

    def test_injected_mode_accepts_native_shape_without_claiming_live_verification(self):
        self.transport = InjectedChatTransport(send=self.native.send, read=self.native.read, fixture=False)
        self.bridge = Bridge(self.store, self.transport, validate_output=self.validator)
        self.assertEqual(self.dispatch()["status"], "awaiting_result")
        raw = self.body()
        raw.pop("fixture_only")
        result = self.bridge.accept_read(self.lease, raw)
        self.assertEqual(result["status"], "recorded")
        self.assertEqual(result["scope"], "candidate_transport_injected")
        self.assertFalse(result["live_verified"])


if __name__ == "__main__":
    unittest.main()
