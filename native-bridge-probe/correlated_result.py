"""Inspect authentic receiver text without upgrading an unresolved dispatch receipt."""
import argparse
import json
from pathlib import Path
import re

from receipt_check import content_is_omitted, final_agent_reply, payload, receiver_identity_problem, reconcile


def inspect_correlated_result(dispatch, receiver_read):
    proof = {
        "scope": "historical_receiver_payload_correlation",
        "task_id": dispatch.get("task_id"), "nonce": dispatch.get("nonce"),
        "sender": dispatch.get("sender"), "requested_target": dispatch.get("target"),
        "accepted": False, "status": "payload_unverified", "payload_verified": False,
        "tool_pull_return_verified": False, "provider_id_mapping_verified": False,
        "actual_host_mode_verified": False, "actual_model": None,
        "independent_execution_verified": False, "push_callback_verified": False,
        "private_bridge_acceptance": "unmet", "answer_disclosed_in_prompt": False,
        "requested_model": dispatch.get("requested_model"), "model_policy": dispatch.get("model_policy"),
        "strict_gate": reconcile(dispatch, [receiver_read]),
    }
    target = dispatch.get("target")
    expected_transport = "mcp__codex_app__create_thread" if target == "Work" else "mcp__codex_app__send_message_to_thread"
    if dispatch.get("sender") != "DOT" or target not in {"Chat", "Work"} or dispatch.get("transport") != expected_transport:
        proof["status"] = "invalid_route"
        return proof
    if target == "Work" and dispatch.get("tool_target") != {"type": "chatgptWorkCloud"}:
        proof["status"] = "invalid_transport"
        return proof
    sent, current = payload(dispatch.get("result")), payload(receiver_read)
    if sent is None or current is None:
        proof["status"] = "tool_error"
        return proof
    if sent.get("kind") not in {None, "chatgpt"}:
        proof["status"] = "invalid_receiver"
        return proof
    prompt = dispatch.get("prompt")
    answer = dispatch.get("expected_answer")
    if not isinstance(prompt, str) or not isinstance(answer, str) or not answer:
        return proof
    for key, value in {"task_id": dispatch.get("task_id"), "nonce": dispatch.get("nonce"), "sender": "DOT", "target": target}.items():
        declared = re.findall(r"(?<![A-Za-z0-9_])" + key + r"=([A-Za-z0-9_-]+)", prompt)
        if not declared or set(declared) != {value}:
            proof["status"] = "invalid_prompt_identity"
            return proof
    proof["answer_disclosed_in_prompt"] = bool(re.search(r"(?<![A-Za-z0-9_])answer=" + re.escape(answer) + r"(?![A-Za-z0-9_-])", prompt))
    thread = current.get("thread", {})
    thread_id = thread.get("id")
    if thread.get("kind") != "chatgpt" or not isinstance(thread_id, str) or not thread_id or thread_id.startswith("local-chatgpt:"):
        proof["status"] = "invalid_receiver"
        return proof
    if sent.get("threadId") and sent["threadId"] != thread_id:
        proof["status"] = "receiver_target_mismatch"
        return proof
    identity_problem = receiver_identity_problem(current)
    if identity_problem:
        proof["status"] = identity_problem
        return proof
    if content_is_omitted(current, thread):
        proof["status"] = "reply_body_unresolved"
        return proof
    proof["provider_id_mapping_verified"] = sent.get("threadId") == thread_id
    proof["receiver_thread_id"] = thread_id
    expected = (f"DOT_BRIDGE_RESULT task_id={dispatch['task_id']} nonce={dispatch['nonce']} "
                f"answer={answer} receiver={target} return_target=DOT")
    for turn in current.get("turns", []):
        if turn.get("status") != "completed" or turn.get("error") or not turn.get("id"):
            continue
        items = turn.get("items", [])
        for index, item in enumerate(items):
            if item.get("type") != "userMessage" or not item.get("id"):
                continue
            user_text = "\n".join(part.get("text", "") for part in item.get("content", []) if part.get("type") == "text")
            if user_text != prompt:
                continue
            proof.update(receiver_turn_id=turn["id"], receiver_message_id=item["id"])
            reply = final_agent_reply(items, index)
            if reply is None:
                continue
            if content_is_omitted(turn, item, reply):
                proof["status"] = "reply_body_unresolved"
                continue
            body = reply.get("text", "")
            body = body.strip() if isinstance(body, str) else ""
            if body.startswith("::chatgpt-content-reference{"):
                proof["status"] = "reply_body_unresolved"
            if body == expected:
                proof.update(status="correlated_payload_verified", payload_verified=True,
                             tool_pull_return_verified=True, return_message_id=reply["id"], returned_payload=body,
                             correlation_basis="exact original prompt, task, nonce, completed same turn, and complete final assistant body")
                return proof
    return proof


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dispatch", type=Path)
    parser.add_argument("receiver_read", type=Path)
    args = parser.parse_args()
    dispatch = json.loads(args.dispatch.read_text(encoding="utf-8-sig"))
    read = json.loads(args.receiver_read.read_text(encoding="utf-8-sig"))
    proof = inspect_correlated_result(dispatch, read)
    print(json.dumps(proof, ensure_ascii=False, indent=2))
    # Correlation is explicitly not full bridge acceptance, even when the body matches.
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
