"""De-identified local-only preservation of the independent correlation tests.

No browser, messaging, external service, or original evidence writes.
"""

import copy
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import unittest

from correlated_result import inspect_correlated_result
from receipt_check import payload, reconcile


PROBE = Path(__file__).resolve().parents[1]
WORKSPACE = PROBE.parent
EVIDENCE = WORKSPACE / "fixtures"
RESUME = EVIDENCE / "receiver-captures"


def envelope(value):
    return {"structuredContent": value, "isError": False}


def fixture(target="Work", resolved=False):
    prompt = f"task_id=independent_1 nonce=independent_nonce sender=DOT target={target} answer=42"
    dispatch = {
        "task_id": "independent_1", "nonce": "independent_nonce", "sender": "DOT", "target": target,
        "prompt": prompt, "expected_answer": "42", "requested_model": "request-only",
        "model_policy": "inherit_task_default" if target == "Work" else "inherit_conversation",
        "transport": "mcp__codex_app__create_thread" if target == "Work" else "mcp__codex_app__send_message_to_thread",
        "result": envelope({"threadId": "formal-receiver"} if resolved else {"clientThreadId": "local-chatgpt:unmapped"}),
    }
    if target == "Work":
        dispatch["tool_target"] = {"type": "chatgptWorkCloud"}
    else:
        dispatch["baseline_turn_ids"] = []
    read = envelope({
        "thread": {"id": "formal-receiver", "kind": "chatgpt"},
        "turns": [{"id": "observed-turn", "status": "completed", "error": None, "items": [
            {"type": "userMessage", "id": "observed-user", "content": [{"type": "text", "text": prompt}]},
            {"type": "agentMessage", "id": "observed-agent", "text": (
                f"DOT_BRIDGE_RESULT task_id=independent_1 nonce=independent_nonce answer=42 receiver={target} return_target=DOT"
            )},
        ]}],
    })
    return dispatch, read


def saved(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


class IndependentCorrelationReview(unittest.TestCase):
    def assert_no_full_acceptance(self, proof):
        self.assertIs(proof["accepted"], False)
        self.assertIs(proof["actual_host_mode_verified"], False)
        self.assertIsNone(proof["actual_model"])
        self.assertIs(proof["independent_execution_verified"], False)
        self.assertIs(proof["push_callback_verified"], False)
        self.assertEqual(proof["private_bridge_acceptance"], "unmet")
        self.assertEqual(proof["scope"], "historical_receiver_payload_correlation")

    def checked(self, dispatch, read):
        originals = copy.deepcopy((dispatch, read))
        proof = inspect_correlated_result(dispatch, read)
        self.assertEqual((dispatch, read), originals)
        self.assert_no_full_acceptance(proof)
        return proof

    def test_preserved_resume_checker_contains_single_control_flow_fix(self):
        # Pure parser history only; no raw account archive is stored in this repository.
        source = (WORKSPACE / "provenance/history/receipt_check_resume.py").read_bytes()
        updated = b'result["status"] = "stale_receiver_turn"\n            continue'
        previous = b'result["status"] = "stale_receiver_turn"\n            return result'
        self.assertEqual(source.count(updated), 1)
        rolled_back_hash = hashlib.sha256(source.replace(updated, previous)).hexdigest()
        hashes = saved(WORKSPACE / "provenance/history/checker-hashes.json")
        self.assertEqual(rolled_back_hash, hashes["before_baseline_skip_fix_sha256"])

    def test_synthetic_work_fixture_is_only_historical_correlation(self):
        dispatch = saved(EVIDENCE / "work-dispatch.json")
        read = saved(RESUME / "work-receiver-read.json")
        proof = self.checked(dispatch, read)
        self.assertTrue(proof["payload_verified"])
        self.assertTrue(proof["tool_pull_return_verified"])
        self.assertFalse(proof["provider_id_mapping_verified"])
        self.assertTrue(proof["answer_disclosed_in_prompt"])
        self.assertFalse(proof["strict_gate"]["accepted"])
        self.assertEqual(proof["strict_gate"]["status"], "pending_thread_resolution")
        self.assertEqual(proof["receiver_thread_id"], "fixture-work-thread")
        self.assertEqual(proof["receiver_message_id"], "fixture-work-user")
        self.assertEqual(proof["return_message_id"], "fixture-work-reply")
        self.assertNotIn("threadId", payload(dispatch["result"]))

    def test_synthetic_chat_reference_never_becomes_verified_body(self):
        proof = self.checked(saved(EVIDENCE / "chat-dispatch.json"), saved(RESUME / "chat-receiver-read.json"))
        self.assertEqual(proof["status"], "reply_body_unresolved")
        self.assertFalse(proof["payload_verified"])
        self.assertFalse(proof["tool_pull_return_verified"])
        self.assertFalse(proof["strict_gate"]["accepted"])
        self.assertNotIn("return_message_id", proof)

    def test_supplied_thread_id_cannot_resolve_provisional_id(self):
        dispatch, read = fixture()
        dispatch["thread_id"] = "formal-receiver"
        proof = self.checked(dispatch, read)
        self.assertTrue(proof["payload_verified"])
        self.assertFalse(proof["provider_id_mapping_verified"])
        self.assertFalse(proof["strict_gate"]["accepted"])
        self.assertEqual(proof["strict_gate"]["status"], "pending_thread_resolution")

    def test_bound_native_gate_does_not_upgrade_full_acceptance(self):
        for target in ("Chat", "Work"):
            with self.subTest(target=target):
                proof = self.checked(*fixture(target, resolved=True))
                self.assertTrue(proof["payload_verified"])
                self.assertTrue(proof["provider_id_mapping_verified"])
                self.assertTrue(proof["strict_gate"]["accepted"])
                self.assertTrue(proof["answer_disclosed_in_prompt"])

    def test_old_turn_is_correlation_without_fresh_native_acceptance(self):
        dispatch, read = fixture("Chat", resolved=True)
        dispatch["baseline_turn_ids"] = ["observed-turn"]
        proof = self.checked(dispatch, read)
        self.assertTrue(proof["payload_verified"])
        self.assertFalse(proof["strict_gate"]["accepted"])
        self.assertEqual(proof["strict_gate"]["status"], "stale_receiver_turn")

    def test_route_and_prompt_metadata_conflicts_are_rejected(self):
        for key, wrong in (("nonce", "other_nonce"), ("task_id", "other_task"),
                           ("sender", "Chat"), ("target", "Chat"), ("transport", "mock_panel_open")):
            with self.subTest(key=key):
                dispatch, read = fixture()
                dispatch[key] = wrong
                self.assertFalse(self.checked(dispatch, read)["payload_verified"])

    def test_wrong_or_missing_cloud_tool_target_is_rejected(self):
        for target in (None, {"type": "projectless"}, {"type": "project"}):
            with self.subTest(tool_target=target):
                dispatch, read = fixture()
                dispatch["tool_target"] = target
                self.assertFalse(self.checked(dispatch, read)["payload_verified"])

    def test_wrong_result_fields_are_rejected(self):
        for marker, wrong in (("task_id=independent_1", "task_id=other"),
                              ("nonce=independent_nonce", "nonce=other"),
                              ("answer=42", "answer=43"),
                              ("receiver=Work", "receiver=Chat"),
                              ("return_target=DOT", "return_target=Chat")):
            with self.subTest(marker=marker):
                dispatch, read = fixture()
                reply = read["structuredContent"]["turns"][0]["items"][1]
                reply["text"] = reply["text"].replace(marker, wrong)
                self.assertFalse(self.checked(dispatch, read)["payload_verified"])

    def test_cross_turn_and_preceding_reply_are_rejected(self):
        for condition in ("separate_turn", "before_user"):
            with self.subTest(condition=condition):
                dispatch, read = fixture()
                turns = read["structuredContent"]["turns"]
                reply = turns[0]["items"].pop()
                if condition == "separate_turn":
                    turns.append({"id": "other-turn", "status": "completed", "items": [reply]})
                else:
                    turns[0]["items"].insert(0, reply)
                self.assertFalse(self.checked(dispatch, read)["payload_verified"])

    def test_unfinished_errored_or_missing_turn_is_rejected(self):
        for key, value in (("status", "inProgress"), ("status", "failed"), ("status", "cancelled"),
                           ("error", "failed"), ("id", "")):
            with self.subTest(key=key, value=value):
                dispatch, read = fixture()
                read["structuredContent"]["turns"][0][key] = value
                self.assertFalse(self.checked(dispatch, read)["payload_verified"])

    def test_missing_ids_body_reference_and_extra_body_are_rejected(self):
        for condition in ("missing_user_id", "missing_reply_id", "missing_body", "reference", "extra_body"):
            with self.subTest(condition=condition):
                dispatch, read = fixture()
                user, reply = read["structuredContent"]["turns"][0]["items"]
                if condition == "missing_user_id":
                    user.pop("id")
                elif condition == "missing_reply_id":
                    reply.pop("id")
                elif condition == "missing_body":
                    reply.pop("text")
                elif condition == "reference":
                    reply["text"] = '::chatgpt-content-reference{source_message_id="observed-agent"}'
                else:
                    reply["text"] += "\nUnverified extra result"
                self.assertFalse(self.checked(dispatch, read)["payload_verified"])

    def test_wrong_receiver_kind_id_or_bound_target_is_rejected(self):
        for condition in ("codex", "provisional", "different_bound_id"):
            with self.subTest(condition=condition):
                dispatch, read = fixture(resolved=True)
                if condition == "codex":
                    read["structuredContent"]["thread"]["kind"] = "codex"
                elif condition == "provisional":
                    read["structuredContent"]["thread"]["id"] = "local-chatgpt:pending"
                else:
                    dispatch["result"] = envelope({"threadId": "other-formal-id"})
                self.assertFalse(self.checked(dispatch, read)["payload_verified"])

    def test_tool_errors_and_queued_only_cannot_verify_payload(self):
        for condition in ("send_error", "read_error", "queued_no_body"):
            with self.subTest(condition=condition):
                dispatch, read = fixture()
                if condition == "send_error":
                    dispatch["result"]["isError"] = True
                elif condition == "read_error":
                    read["isError"] = True
                else:
                    dispatch["result"] = envelope({"clientThreadId": "local-chatgpt:unmapped", "status": "queued"})
                    read = envelope({"thread": {"id": "formal-receiver", "kind": "chatgpt"}, "turns": []})
                self.assertFalse(self.checked(dispatch, read)["payload_verified"])

    def test_fixture_cli_exit_and_fixture_inputs_are_unchanged(self):
        for kind in ("chat", "work"):
            with self.subTest(kind=kind):
                dispatch_path = EVIDENCE / f"{kind}-dispatch.json"
                read_path = RESUME / f"{kind}-receiver-read.json"
                before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in (dispatch_path, read_path)}
                process = subprocess.run(
                    [sys.executable, str(PROBE / "correlated_result.py"), str(dispatch_path), str(read_path)],
                    capture_output=True, text=True, encoding="utf-8", timeout=30, check=False,
                )
                self.assertEqual(process.returncode, 2, process.stderr)
                self.assert_no_full_acceptance(json.loads(process.stdout))
                for path, expected_hash in before.items():
                    self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), expected_hash)


if __name__ == "__main__":
    unittest.main()
