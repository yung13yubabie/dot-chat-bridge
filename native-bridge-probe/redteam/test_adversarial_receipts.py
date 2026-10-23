"""Independent synthetic red-team cases. No network, browser, or tool dispatch.

Run from native-bridge-probe: python -m unittest -v redteam.test_adversarial_receipts
The intended rejection tests fail on the initially reviewed implementation.
"""

import copy
import unittest

from receipt_check import reconcile


def envelope(value):
    return {"structuredContent": value, "isError": False}


def fixture(target="Chat"):
    prompt = f"task_id=rt_1 nonce=rt_nonce sender=DOT target={target}"
    dispatch = {
        "task_id": "rt_1", "nonce": "rt_nonce", "sender": "DOT", "target": target,
        "thread_id": "existing-chat-1", "prompt": prompt, "expected_answer": "42",
        "baseline_turn_ids": [],
        "requested_model": "requested-only",
        "model_policy": "inherit_task_default" if target == "Work" else "inherit_conversation",
        "transport": "mcp__codex_app__send_message_to_thread",
        "result": envelope({"threadId": "existing-chat-1"}),
    }
    read = envelope({
        "thread": {"id": "existing-chat-1", "kind": "chatgpt", "status": {"type": "idle"}},
        "turns": [{"id": "old-turn-1", "status": "completed", "error": None, "items": [
            {"type": "userMessage", "id": "old-user-1", "content": [{"type": "text", "text": prompt}]},
            {"type": "agentMessage", "id": "old-agent-1", "text": (
                f"DOT_BRIDGE_RESULT task_id=rt_1 nonce=rt_nonce answer=42 receiver={target} return_target=DOT"
            )},
        ]}],
    })
    return dispatch, read


class AdversarialReceiptTests(unittest.TestCase):
    def test_work_client_id_cannot_borrow_existing_chat_thread(self):
        dispatch, read = fixture("Work")
        dispatch.update(transport="mcp__codex_app__create_thread", tool_target={"type": "chatgptWorkCloud"})
        dispatch["result"] = envelope({"kind": "chatgpt", "clientThreadId": "local-chatgpt:pending"})
        self.assertFalse(reconcile(dispatch, [read])["accepted"])

    def test_existing_chat_send_cannot_claim_work(self):
        dispatch, read = fixture("Work")
        self.assertFalse(reconcile(dispatch, [read])["accepted"])

    def test_work_create_requires_cloud_target(self):
        dispatch, read = fixture("Work")
        dispatch.update(transport="mcp__codex_app__create_thread", tool_target={"type": "projectless"})
        self.assertFalse(reconcile(dispatch, [read])["accepted"])

    def test_unsupported_transport_cannot_claim_native_success(self):
        dispatch, read = fixture()
        dispatch["transport"] = "mock_panel_open"
        self.assertFalse(reconcile(dispatch, [read])["accepted"])

    def test_repeated_baseline_cannot_prove_new_dispatch(self):
        dispatch, baseline = fixture()
        dispatch["baseline_turn_ids"] = ["old-turn-1"]
        # The latest receiver read still contains exactly the already-known old turn.
        self.assertFalse(reconcile(dispatch, [baseline, copy.deepcopy(baseline)])["accepted"])

    def test_queued_dispatch_with_old_turn_cannot_prove_execution(self):
        dispatch, read = fixture()
        dispatch["baseline_turn_ids"] = ["old-turn-1"]
        dispatch["result"] = envelope({"threadId": "existing-chat-1", "status": "queued"})
        self.assertFalse(reconcile(dispatch, [read])["accepted"])

    def test_prompt_direction_must_not_contradict_recorded_route(self):
        dispatch, read = fixture()
        dispatch["prompt"] = "task_id=rt_1 nonce=rt_nonce sender=Chat target=DOT"
        read["structuredContent"]["turns"][0]["items"][0]["content"][0]["text"] = dispatch["prompt"]
        self.assertFalse(reconcile(dispatch, [read])["accepted"])

    def test_queued_alone_remains_unaccepted(self):
        dispatch, _ = fixture()
        dispatch["result"] = envelope({"threadId": "existing-chat-1", "status": "queued"})
        self.assertFalse(reconcile(dispatch, [])["accepted"])

    def test_provisional_id_alone_remains_unaccepted(self):
        dispatch, read = fixture("Work")
        dispatch.pop("thread_id")
        dispatch["result"] = envelope({"clientThreadId": "local-chatgpt:pending"})
        self.assertFalse(reconcile(dispatch, [read])["accepted"])

    def test_different_task_and_nonce_remain_unaccepted(self):
        dispatch, read = fixture()
        dispatch.update(task_id="fresh-task", nonce="fresh-nonce", prompt="fresh task payload")
        self.assertFalse(reconcile(dispatch, [read])["accepted"])

    def test_cross_turn_reply_remains_unaccepted(self):
        dispatch, read = fixture()
        turns = read["structuredContent"]["turns"]
        answer = turns[0]["items"].pop()
        turns.append({"id": "later-turn", "status": "completed", "items": [answer]})
        self.assertFalse(reconcile(dispatch, [read])["accepted"])

    def test_wrong_metadata_route_remains_unaccepted(self):
        dispatch, read = fixture()
        dispatch.update(sender="Chat", target="DOT")
        self.assertFalse(reconcile(dispatch, [read])["accepted"])

    def test_model_request_never_proves_actual_model(self):
        dispatch, read = fixture()
        self.assertIsNone(reconcile(dispatch, [read])["actual_model"])

    def test_fresh_chat_same_turn_positive_control(self):
        dispatch, read = fixture()
        result = reconcile(dispatch, [read])
        self.assertTrue(result["accepted"])
        self.assertEqual(result["receiver_message_id"], "old-user-1")
        self.assertEqual(result["return_message_id"], "old-agent-1")

    def test_resolved_cloud_work_positive_control(self):
        dispatch, read = fixture("Work")
        dispatch.update(transport="mcp__codex_app__create_thread", tool_target={"type": "chatgptWorkCloud"})
        self.assertTrue(reconcile(dispatch, [read])["accepted"])

    def test_new_turn_after_identical_old_task_can_verify(self):
        dispatch, read = fixture()
        dispatch["baseline_turn_ids"] = ["old-turn-1"]
        new_turn = copy.deepcopy(read["structuredContent"]["turns"][0])
        new_turn["id"] = "fresh-turn-2"
        new_turn["items"][0]["id"] = "fresh-user-2"
        new_turn["items"][1]["id"] = "fresh-agent-2"
        read["structuredContent"]["turns"].append(new_turn)
        result = reconcile(dispatch, [read])
        self.assertTrue(result["accepted"])
        self.assertEqual(result["receiver_message_id"], "fresh-user-2")
        self.assertEqual(result["return_message_id"], "fresh-agent-2")

    def test_missing_baseline_fails_closed(self):
        dispatch, read = fixture()
        dispatch.pop("baseline_turn_ids")
        self.assertFalse(reconcile(dispatch, [read])["accepted"])

    def test_malformed_baseline_fails_closed(self):
        for bad_baseline in (None, "old-turn-1", {}, [None], [17], [""]):
            with self.subTest(baseline=bad_baseline):
                dispatch, read = fixture()
                dispatch["baseline_turn_ids"] = bad_baseline
                self.assertFalse(reconcile(dispatch, [read])["accepted"])

    def test_direction_tokens_are_not_prefixes(self):
        dispatch, read = fixture()
        dispatch["prompt"] = "task_id=rt_1 nonce=rt_nonce sender=DOTX target=ChatGPT"
        read["structuredContent"]["turns"][0]["items"][0]["content"][0]["text"] = dispatch["prompt"]
        self.assertFalse(reconcile(dispatch, [read])["accepted"])

    def test_task_nonce_tokens_are_not_prefixes(self):
        dispatch, read = fixture()
        dispatch["prompt"] = "task_id=rt_1_other nonce=rt_nonce_other sender=DOT target=Chat"
        read["structuredContent"]["turns"][0]["items"][0]["content"][0]["text"] = dispatch["prompt"]
        self.assertFalse(reconcile(dispatch, [read])["accepted"])

    def test_conflicting_prompt_routes_fail_closed(self):
        dispatch, read = fixture()
        dispatch["prompt"] += " sender=Chat target=DOT"
        read["structuredContent"]["turns"][0]["items"][0]["content"][0]["text"] = dispatch["prompt"]
        self.assertFalse(reconcile(dispatch, [read])["accepted"])


if __name__ == "__main__":
    unittest.main()
