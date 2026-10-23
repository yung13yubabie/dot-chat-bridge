import copy
import unittest

from receipt_check import reconcile


def envelope(value):
    return {"structuredContent": value, "isError": False}


class ReceiptCheckTests(unittest.TestCase):
    def setUp(self):
        self.dispatch = {
            "task_id": "t_1", "nonce": "n_1", "target": "Chat",
            "thread_id": "receiver-1", "sender": "DOT",
            "expected_answer": "42", "prompt": "task_id=t_1 nonce=n_1 sender=DOT target=Chat",
            "requested_model": "requested-only", "model_policy": "inherit_conversation",
            "transport": "mcp__codex_app__send_message_to_thread",
            "baseline_turn_ids": [],
            "result": envelope({"threadId": "receiver-1"}),
        }
        self.read = envelope({
            "thread": {"id": "receiver-1", "kind": "chatgpt", "status": {"type": "idle"}},
            "turns": [{"id": "turn-1", "status": "completed", "error": None, "items": [
                {"type": "userMessage", "id": "u-1", "content": [{"type": "text", "text": self.dispatch["prompt"]}]},
                {"type": "agentMessage", "id": "a-1", "text": "DOT_BRIDGE_RESULT task_id=t_1 nonce=n_1 answer=42 receiver=Chat return_target=DOT"},
            ]}],
        })

    def test_matching_receiver_and_same_turn_return(self):
        result = reconcile(self.dispatch, [self.read])
        self.assertEqual(result["status"], "verified_round_trip")
        self.assertEqual(result["receiver_message_id"], "u-1")
        self.assertEqual(result["return_message_id"], "a-1")

    def test_requested_model_never_becomes_actual_model(self):
        result = reconcile(self.dispatch, [self.read])
        self.assertEqual(result["requested_model"], "requested-only")
        self.assertIsNone(result["actual_model"])

    def test_retry_cannot_accept_same_task_old_turn(self):
        self.dispatch["baseline_turn_ids"] = ["turn-1"]
        self.assertEqual(reconcile(self.dispatch, [self.read])["status"], "stale_receiver_turn")

    def test_existing_chat_requires_predispatch_baseline(self):
        self.dispatch.pop("baseline_turn_ids")
        self.assertEqual(reconcile(self.dispatch, [self.read])["status"], "missing_predispatch_baseline")

    def test_prompt_direction_cannot_contradict_metadata(self):
        self.dispatch["prompt"] = "task_id=t_1 nonce=n_1 sender=Chat target=DOT"
        self.read["structuredContent"]["turns"][0]["items"][0]["content"][0]["text"] = self.dispatch["prompt"]
        self.assertEqual(reconcile(self.dispatch, [self.read])["status"], "invalid_prompt_identity")

    def test_prompt_requires_task_and_nonce_identity(self):
        self.dispatch["prompt"] = "task_id=other nonce=n_1 sender=DOT target=Chat"
        self.read["structuredContent"]["turns"][0]["items"][0]["content"][0]["text"] = self.dispatch["prompt"]
        self.assertEqual(reconcile(self.dispatch, [self.read])["status"], "invalid_prompt_identity")

    def test_dispatch_success_alone_is_pending(self):
        self.assertEqual(reconcile(self.dispatch, [])["status"], "pending_receiver_evidence")

    def test_provisional_work_id_is_not_a_thread_id(self):
        self.dispatch.pop("thread_id")
        self.dispatch["target"] = "Work"
        self.dispatch["transport"] = "mcp__codex_app__create_thread"
        self.dispatch["tool_target"] = {"type": "chatgptWorkCloud"}
        self.dispatch["result"] = envelope({"kind": "chatgpt", "clientThreadId": "local-chatgpt:pending"})
        self.assertEqual(reconcile(self.dispatch, [self.read])["status"], "pending_thread_resolution")

    def test_work_client_id_cannot_reuse_existing_chat_thread(self):
        self.dispatch.update(target="Work", transport="mcp__codex_app__create_thread",
                             tool_target={"type": "chatgptWorkCloud"})
        self.dispatch["result"] = envelope({"kind": "chatgpt", "clientThreadId": "local-chatgpt:pending"})
        self.read["structuredContent"]["turns"][0]["items"][1]["text"] = "DOT_BRIDGE_RESULT task_id=t_1 nonce=n_1 answer=42 receiver=Work return_target=DOT"
        self.assertFalse(reconcile(self.dispatch, [self.read])["accepted"])

    def test_work_requires_native_work_creation_target(self):
        self.dispatch["target"] = "Work"
        self.read["structuredContent"]["turns"][0]["items"][1]["text"] = "DOT_BRIDGE_RESULT task_id=t_1 nonce=n_1 answer=42 receiver=Work return_target=DOT"
        self.assertEqual(reconcile(self.dispatch, [self.read])["status"], "invalid_transport")

    def test_resolved_native_work_task_can_verify(self):
        self.dispatch.update(target="Work", transport="mcp__codex_app__create_thread",
                             tool_target={"type": "chatgptWorkCloud"})
        self.dispatch["prompt"] = self.dispatch["prompt"].replace("target=Chat", "target=Work")
        self.read["structuredContent"]["turns"][0]["items"][0]["content"][0]["text"] = self.dispatch["prompt"]
        self.read["structuredContent"]["turns"][0]["items"][1]["text"] = "DOT_BRIDGE_RESULT task_id=t_1 nonce=n_1 answer=42 receiver=Work return_target=DOT"
        self.assertTrue(reconcile(self.dispatch, [self.read])["accepted"])

    def test_reply_content_reference_is_explicitly_unresolved(self):
        self.read["structuredContent"]["turns"][0]["items"][1]["text"] = '::chatgpt-content-reference{index="0" source_message_id="a-1"}'
        result = reconcile(self.dispatch, [self.read])
        self.assertEqual(result["status"], "reply_body_unresolved")
        self.assertEqual(result["observed_reply_message_id"], "a-1")
        self.assertFalse(result["accepted"])

    def test_wrong_thread_cannot_verify(self):
        self.read["structuredContent"]["thread"]["id"] = "different"
        self.assertFalse(reconcile(self.dispatch, [self.read])["accepted"])

    def test_codex_is_not_work_or_chat(self):
        self.read["structuredContent"]["thread"]["kind"] = "codex"
        self.assertFalse(reconcile(self.dispatch, [self.read])["accepted"])

    def test_old_task_cannot_verify(self):
        self.read["structuredContent"]["turns"][0]["items"][0]["content"][0]["text"] = "task_id=old nonce=n_1"
        self.assertFalse(reconcile(self.dispatch, [self.read])["accepted"])

    def test_cross_turn_return_cannot_verify(self):
        turns = self.read["structuredContent"]["turns"]
        answer = turns[0]["items"].pop()
        turns.append({"id": "turn-2", "status": "completed", "items": [answer]})
        self.assertEqual(reconcile(self.dispatch, [self.read])["status"], "received_no_verified_return")

    def test_wrong_nonce_cannot_verify(self):
        self.read["structuredContent"]["turns"][0]["items"][1]["text"] = "DOT_BRIDGE_RESULT task_id=t_1 nonce=wrong answer=42 receiver=Chat return_target=DOT"
        self.assertFalse(reconcile(self.dispatch, [self.read])["accepted"])

    def test_failed_or_incomplete_turn_cannot_verify(self):
        for status in ("failed", "inProgress", "cancelled"):
            changed = copy.deepcopy(self.read)
            changed["structuredContent"]["turns"][0]["status"] = status
            self.assertFalse(reconcile(self.dispatch, [changed])["accepted"])

    def test_error_after_previous_success_is_not_accepted(self):
        failed = {"isError": True, "content": [{"type": "text", "text": "receiver unavailable"}]}
        self.assertFalse(reconcile(self.dispatch, [self.read, failed])["accepted"])

    def test_reversed_direction_cannot_verify(self):
        self.dispatch["sender"] = "Chat"
        self.dispatch["target"] = "DOT"
        self.assertEqual(reconcile(self.dispatch, [self.read])["status"], "invalid_route")

    def test_receiver_error_cannot_verify(self):
        self.read["structuredContent"]["turns"][0]["error"] = "failed"
        self.assertFalse(reconcile(self.dispatch, [self.read])["accepted"])

    def test_missing_message_ids_cannot_verify(self):
        self.read["structuredContent"]["turns"][0]["items"][1].pop("id")
        self.assertFalse(reconcile(self.dispatch, [self.read])["accepted"])


if __name__ == "__main__":
    unittest.main()
