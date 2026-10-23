"""One bounded final identity/duplicate review: 12 cases, local fixtures only."""

import copy
import unittest

from correlated_result import inspect_correlated_result
from receipt_check import reconcile
from redteam.test_correlation_independent_20261023 import fixture


class FinalIdentityDuplicateReview(unittest.TestCase):
    def checked(self, dispatch, read):
        original = copy.deepcopy((dispatch, read))
        native = reconcile(dispatch, [read])
        correlation = inspect_correlated_result(dispatch, read)
        self.assertEqual((dispatch, read), original)
        self.assertIs(correlation["accepted"], False)
        self.assertIs(correlation["independent_execution_verified"], False)
        self.assertIs(correlation["push_callback_verified"], False)
        self.assertEqual(correlation["private_bridge_acceptance"], "unmet")
        return native, correlation

    def assert_rejected(self, dispatch, read):
        native, correlation = self.checked(dispatch, read)
        self.assertEqual((native["accepted"], correlation["payload_verified"]), (False, False),
                         f"native={native['status']} correlation={correlation['status']}")

    def test_01_earlier_success_cannot_override_wrong_final_body(self):
        dispatch, read = fixture("Chat", resolved=True)
        reply = copy.deepcopy(read["structuredContent"]["turns"][0]["items"][1])
        reply.update(id="final-agent", text=reply["text"].replace("answer=42", "answer=43"))
        read["structuredContent"]["turns"][0]["items"].append(reply)
        self.assert_rejected(dispatch, read)

    def test_02_earlier_success_cannot_override_unresolved_final_body(self):
        dispatch, read = fixture("Chat", resolved=True)
        read["structuredContent"]["turns"][0]["items"].append({
            "type": "agentMessage", "id": "final-agent", "text": '::chatgpt-content-reference{source_message_id="final-agent"}'
        })
        self.assert_rejected(dispatch, read)

    def test_03_user_and_assistant_cannot_share_identity(self):
        dispatch, read = fixture("Chat", resolved=True)
        user, reply = read["structuredContent"]["turns"][0]["items"]
        reply["id"] = user["id"]
        self.assert_rejected(dispatch, read)

    def test_04_one_assistant_id_cannot_name_conflicting_bodies(self):
        dispatch, read = fixture("Chat", resolved=True)
        earlier = copy.deepcopy(read["structuredContent"]["turns"][0]["items"][1])
        earlier["text"] = earlier["text"].replace("answer=42", "answer=43")
        read["structuredContent"]["turns"][0]["items"].insert(1, earlier)
        self.assert_rejected(dispatch, read)

    def test_05_old_assistant_identity_cannot_be_reused_in_fresh_turn(self):
        dispatch, read = fixture("Chat", resolved=True)
        dispatch["baseline_turn_ids"] = ["observed-turn"]
        fresh = copy.deepcopy(read["structuredContent"]["turns"][0])
        fresh["id"] = "fresh-turn"
        fresh["items"][0]["id"] = "fresh-user"
        # The old assistant id is retained: a new turn must not make it fresh.
        read["structuredContent"]["turns"].append(fresh)
        self.assert_rejected(dispatch, read)

    def test_06_one_turn_identity_cannot_have_conflicting_status(self):
        dispatch, read = fixture("Chat", resolved=True)
        conflict = copy.deepcopy(read["structuredContent"]["turns"][0])
        conflict.update(status="failed", error="failed")
        read["structuredContent"]["turns"].append(conflict)
        self.assert_rejected(dispatch, read)

    def test_07_exact_duplicate_reply_is_static_idempotency_only(self):
        dispatch, read = fixture("Chat", resolved=True)
        expected_native, expected_correlation = self.checked(dispatch, read)
        read["structuredContent"]["turns"][0]["items"].append(
            copy.deepcopy(read["structuredContent"]["turns"][0]["items"][1])
        )
        actual_native, actual_correlation = self.checked(dispatch, read)
        self.assertEqual(actual_native, expected_native)
        self.assertEqual(actual_correlation, expected_correlation)
        self.assertNotIn("exactly_once_verified", actual_correlation)

    def test_08_same_body_distinct_ids_selects_final_assistant(self):
        dispatch, read = fixture("Chat", resolved=True)
        final = copy.deepcopy(read["structuredContent"]["turns"][0]["items"][1])
        final["id"] = "final-agent"
        read["structuredContent"]["turns"][0]["items"].append(final)
        native, correlation = self.checked(dispatch, read)
        self.assertTrue(native["accepted"])
        self.assertTrue(correlation["payload_verified"])
        self.assertEqual((native["return_message_id"], correlation["return_message_id"]), ("final-agent", "final-agent"))

    def test_09_preview_success_does_not_override_wrong_body(self):
        dispatch, read = fixture("Chat", resolved=True)
        reply = read["structuredContent"]["turns"][0]["items"][1]
        read["structuredContent"]["thread"]["preview"] = reply["text"]
        reply["text"] = reply["text"].replace("answer=42", "answer=43")
        self.assert_rejected(dispatch, read)

    def test_10_explicit_native_codex_kind_cannot_claim_chatgpt_source(self):
        dispatch, read = fixture("Work", resolved=True)
        dispatch["result"]["structuredContent"]["kind"] = "codex"
        self.assert_rejected(dispatch, read)

    def test_11_conflicting_task_and_nonce_declarations_are_rejected(self):
        dispatch, read = fixture("Chat", resolved=True)
        dispatch["prompt"] += " task_id=other_task nonce=other_nonce"
        read["structuredContent"]["turns"][0]["items"][0]["content"][0]["text"] = dispatch["prompt"]
        self.assert_rejected(dispatch, read)

    def test_12_repeated_identical_snapshot_has_no_accumulated_state(self):
        dispatch, read = fixture("Chat", resolved=True)
        expected_native, expected_correlation = self.checked(dispatch, read)
        native = reconcile(dispatch, [copy.deepcopy(read), copy.deepcopy(read)])
        self.assertEqual(native, expected_native)
        self.assertEqual(self.checked(dispatch, read), (expected_native, expected_correlation))


if __name__ == "__main__":
    unittest.main()
