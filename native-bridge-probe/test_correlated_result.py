import copy
import unittest

from correlated_result import inspect_correlated_result
from test_receipt_check import envelope


class CorrelatedResultTests(unittest.TestCase):
    def setUp(self):
        self.dispatch = {
            "task_id": "w1", "nonce": "n1", "sender": "DOT", "target": "Work",
            "prompt": "task_id=w1 nonce=n1 sender=DOT target=Work answer=42",
            "expected_answer": "42", "requested_model": None,
            "model_policy": "inherit_task_default",
            "transport": "mcp__codex_app__create_thread",
            "tool_target": {"type": "chatgptWorkCloud"},
            "result": envelope({"clientThreadId": "local-chatgpt:pending"}),
        }
        self.read = envelope({"thread": {"id": "formal-id", "kind": "chatgpt"}, "turns": [
            {"id": "turn", "status": "completed", "error": None, "items": [
                {"type": "userMessage", "id": "user", "content": [{"type": "text", "text": self.dispatch["prompt"]}]},
                {"type": "agentMessage", "id": "assistant", "text": "DOT_BRIDGE_RESULT task_id=w1 nonce=n1 answer=42 receiver=Work return_target=DOT"},
            ]}
        ]})

    def test_payload_is_verified_without_forging_dispatch_binding(self):
        original = copy.deepcopy(self.dispatch)
        proof = inspect_correlated_result(self.dispatch, self.read)
        self.assertTrue(proof["payload_verified"])
        self.assertFalse(proof["accepted"])
        self.assertFalse(proof["provider_id_mapping_verified"])
        self.assertFalse(proof["actual_host_mode_verified"])
        self.assertIsNone(proof["actual_model"])
        self.assertEqual(proof["return_message_id"], "assistant")
        self.assertEqual(self.dispatch, original)

    def test_answer_disclosed_does_not_prove_execution(self):
        proof = inspect_correlated_result(self.dispatch, self.read)
        self.assertTrue(proof["answer_disclosed_in_prompt"])
        self.assertFalse(proof["independent_execution_verified"])

    def test_omitted_body_is_not_payload(self):
        self.read["structuredContent"]["turns"][0]["items"][1]["text"] = '::chatgpt-content-reference{source_message_id="assistant"}'
        self.assertFalse(inspect_correlated_result(self.dispatch, self.read)["payload_verified"])

    def test_wrong_nonce_or_direction_is_rejected(self):
        for old, new in (("nonce=n1", "nonce=wrong"), ("return_target=DOT", "return_target=Chat")):
            read = copy.deepcopy(self.read)
            read["structuredContent"]["turns"][0]["items"][1]["text"] = read["structuredContent"]["turns"][0]["items"][1]["text"].replace(old, new)
            self.assertFalse(inspect_correlated_result(self.dispatch, read)["payload_verified"])

    def test_no_cross_turn_combination(self):
        turn = self.read["structuredContent"]["turns"][0]
        reply = turn["items"].pop()
        self.read["structuredContent"]["turns"].append({"id": "other", "status": "completed", "items": [reply]})
        self.assertFalse(inspect_correlated_result(self.dispatch, self.read)["payload_verified"])

    def test_prompt_identity_must_match_metadata(self):
        self.dispatch["nonce"] = "other"
        self.assertFalse(inspect_correlated_result(self.dispatch, self.read)["payload_verified"])

    def test_error_read_and_incomplete_turn_are_rejected(self):
        self.assertFalse(inspect_correlated_result(self.dispatch, {"isError": True})["payload_verified"])
        self.read["structuredContent"]["turns"][0]["status"] = "inProgress"
        self.assertFalse(inspect_correlated_result(self.dispatch, self.read)["payload_verified"])

    def test_wrong_bound_receiver_is_rejected(self):
        self.dispatch["result"] = envelope({"threadId": "different"})
        self.assertFalse(inspect_correlated_result(self.dispatch, self.read)["payload_verified"])


if __name__ == "__main__":
    unittest.main()
