"""Bounded synthetic lifecycle/provenance audit; no transport or network calls."""
import unittest

from correlated_result import inspect_correlated_result
from receipt_check import reconcile


class FinalLifecycleGateTests(unittest.TestCase):
    def setUp(self):
        self.dispatch = {
            "task_id": "life_1", "nonce": "nonce_1", "sender": "DOT", "target": "Chat",
            "thread_id": "receiver-1", "transport": "mcp__codex_app__send_message_to_thread",
            "baseline_turn_ids": [], "expected_answer": "42",
            "prompt": "task_id=life_1 nonce=nonce_1 sender=DOT target=Chat",
            "result": {"structuredContent": {"threadId": "receiver-1"}, "isError": False},
        }
        self.read = {"structuredContent": {
            "thread": {"id": "receiver-1", "kind": "chatgpt"},
            "turns": [{"id": "turn-1", "status": "completed", "error": None, "items": [
                {"type": "userMessage", "id": "user-1", "content": [{"type": "text", "text": self.dispatch["prompt"]}]},
                {"type": "agentMessage", "id": "agent-1", "text": "DOT_BRIDGE_RESULT task_id=life_1 nonce=nonce_1 answer=42 receiver=Chat return_target=DOT"},
            ]}],
        }, "isError": False}

    def turn(self):
        return self.read["structuredContent"]["turns"][0]

    def reply(self):
        return self.turn()["items"][1]

    def assert_unverified(self):
        strict = reconcile(self.dispatch, [self.read])["accepted"]
        correlated = inspect_correlated_result(self.dispatch, self.read)["payload_verified"]
        self.assertEqual((strict, correlated), (False, False))

    def test_cancelled_turn_rejects_both_proofs(self):
        self.turn()["status"] = "cancelled"
        self.assert_unverified()

    def test_completed_turn_with_error_rejects_both_proofs(self):
        self.turn()["error"] = "execution failed"
        self.assert_unverified()

    def test_known_baseline_cannot_be_new_round_trip(self):
        self.dispatch["baseline_turn_ids"] = ["turn-1"]
        strict = reconcile(self.dispatch, [self.read])
        historical = inspect_correlated_result(self.dispatch, self.read)
        self.assertFalse(strict["accepted"])
        self.assertEqual(strict["status"], "stale_receiver_turn")
        self.assertTrue(historical["payload_verified"])
        self.assertFalse(historical["accepted"])
        self.assertEqual(historical["scope"], "historical_receiver_payload_correlation")

    def test_provisional_work_id_does_not_become_provider_binding(self):
        self.dispatch.update(target="Work", transport="mcp__codex_app__create_thread",
                             tool_target={"type": "chatgptWorkCloud"})
        self.dispatch["prompt"] = self.dispatch["prompt"].replace("target=Chat", "target=Work")
        self.turn()["items"][0]["content"][0]["text"] = self.dispatch["prompt"]
        self.reply()["text"] = self.reply()["text"].replace("receiver=Chat", "receiver=Work")
        self.dispatch["result"]["structuredContent"] = {"clientThreadId": "local-chatgpt:pending"}
        strict = reconcile(self.dispatch, [self.read])
        historical = inspect_correlated_result(self.dispatch, self.read)
        self.assertFalse(strict["accepted"])
        self.assertTrue(historical["payload_verified"])
        self.assertFalse(historical["provider_id_mapping_verified"])
        self.assertFalse(historical["actual_host_mode_verified"])
        self.assertFalse(historical["accepted"])

    def test_content_reference_cannot_use_correct_preview(self):
        self.read["structuredContent"]["thread"]["preview"] = self.reply()["text"]
        self.reply()["text"] = '::chatgpt-content-reference{source_message_id="agent-1"}'
        self.assert_unverified()

    def test_empty_body_cannot_use_correct_preview(self):
        self.read["structuredContent"]["thread"]["preview"] = self.reply()["text"]
        self.reply()["text"] = ""
        self.assert_unverified()

    def test_missing_body_cannot_use_correct_preview(self):
        self.read["structuredContent"]["thread"]["preview"] = self.reply().pop("text")
        self.assert_unverified()

    def test_missing_assistant_id_rejects_even_matching_body(self):
        self.reply().pop("id")
        self.assert_unverified()

    def test_explicit_item_omission_rejects_matching_text(self):
        self.reply()["content_omitted"] = True
        self.assert_unverified()

    def test_explicit_turn_omission_rejects_matching_text(self):
        self.turn()["content_omitted"] = True
        self.assert_unverified()

    def test_explicit_read_omission_rejects_matching_text(self):
        self.read["structuredContent"]["content_omitted"] = True
        self.assert_unverified()

    def test_explicit_false_omission_is_not_missing_evidence(self):
        self.read["structuredContent"]["content_omitted"] = False
        self.turn()["content_omitted"] = False
        self.reply()["content_omitted"] = False
        self.assertTrue(reconcile(self.dispatch, [self.read])["accepted"])
        self.assertTrue(inspect_correlated_result(self.dispatch, self.read)["payload_verified"])


if __name__ == "__main__":
    unittest.main()
