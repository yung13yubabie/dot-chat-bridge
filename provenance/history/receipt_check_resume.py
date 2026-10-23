"""Check saved native tool receipts; this module does not send messages or access APIs."""

import argparse
import json
import re
from pathlib import Path


def payload(result):
    """Read surfaced MCP JSON only. Never reinterpret an error as a receipt."""
    if not isinstance(result, dict) or result.get("isError"):
        return None
    if isinstance(result.get("structuredContent"), dict):
        return result["structuredContent"]
    for item in result.get("content", []):
        if item.get("type") == "text":
            try:
                value = json.loads(item.get("text", ""))
            except (ValueError, TypeError):
                continue
            if isinstance(value, dict):
                return value
    return None


def reconcile(dispatch, reads):
    """Accept a native round trip only with the current receiver's same-turn reply.

    Native tool contract: send_message_to_thread supports existing Chat;
    create_thread(chatgptWorkCloud) supports Work. clientThreadId is provisional.
    Tool descriptions are preserved in ../evidence/channel-contract.md.
    Saved input provenance still depends on the operator recording authentic tools.
    """
    result = {
        "task_id": dispatch.get("task_id"), "sender": dispatch.get("sender"),
        "target": dispatch.get("target"), "accepted": False,
        "status": "pending_receiver_evidence", "verification_scope": "native_tool_round_trip",
        "private_bridge_acceptance": "unmet", "requested_model": dispatch.get("requested_model"),
        "model_policy": dispatch.get("model_policy"), "actual_model": None,
        "receiver_message_id": None, "return_message_id": None,
        "observed_reply_message_id": None,
    }
    if dispatch.get("sender") != "DOT" or dispatch.get("target") not in {"Chat", "Work"}:
        result["status"] = "invalid_route"
        return result
    expected_transport = ("mcp__codex_app__create_thread" if dispatch["target"] == "Work"
                          else "mcp__codex_app__send_message_to_thread")
    if dispatch.get("transport") != expected_transport or (dispatch["target"] == "Work"
            and dispatch.get("tool_target") != {"type": "chatgptWorkCloud"}):
        result["status"] = "invalid_transport"
        return result
    sent = payload(dispatch.get("result"))
    if sent is None:
        result["status"] = "dispatch_error"
        return result
    # The dispatch result must bind the receiver. A caller-supplied thread_id
    # cannot resolve a provisional clientThreadId or relabel an existing Chat.
    thread_id = sent.get("threadId")
    if not isinstance(thread_id, str) or not thread_id or thread_id.startswith("local-chatgpt:"):
        result["status"] = "pending_thread_resolution"
        return result
    result["thread_id"] = thread_id
    if dispatch.get("thread_id") and dispatch["thread_id"] != thread_id:
        result["status"] = "dispatch_target_mismatch"
        return result
    if not reads:
        return result
    current = payload(reads[-1])
    if current is None:
        result["status"] = "receiver_read_error"
        return result
    thread = current.get("thread", {})
    if thread.get("id") != thread_id or thread.get("kind") != "chatgpt":
        result["status"] = "receiver_target_mismatch"
        return result
    task_id, nonce = dispatch.get("task_id"), dispatch.get("nonce")
    expected_answer = dispatch.get("expected_answer")
    if not all(isinstance(v, str) and v for v in (task_id, nonce, expected_answer, dispatch.get("prompt"))):
        result["status"] = "invalid_spec"
        return result
    identities = {"task_id": task_id, "nonce": nonce, "sender": "DOT", "target": dispatch["target"]}
    for key, value in identities.items():
        declared = re.findall(r"(?<![A-Za-z0-9_])" + key + r"=([A-Za-z0-9_-]+)", dispatch["prompt"])
        if not declared or set(declared) != {value}:
            result["status"] = "invalid_prompt_identity"
            return result
    baseline = dispatch.get("baseline_turn_ids")
    if dispatch["target"] == "Chat" and (not isinstance(baseline, list)
            or any(not isinstance(turn_id, str) or not turn_id for turn_id in baseline)):
        result["status"] = "missing_predispatch_baseline"
        return result
    baseline = set(baseline or [])
    expected = (
        f"DOT_BRIDGE_RESULT task_id={task_id} nonce={nonce} answer={expected_answer} "
        f"receiver={dispatch['target']} return_target=DOT"
    )
    for turn in current.get("turns", []):
        items = turn.get("items", [])
        user_item = next((item for item in items if item.get("type") == "userMessage"
                          and item.get("id") and "\n".join(part.get("text", "") for part in item.get("content", [])
                          if part.get("type") == "text") == dispatch["prompt"]), None)
        if user_item is None:
            continue
        if turn.get("id") in baseline:
            result["status"] = "stale_receiver_turn"
            continue
        result.update(status="received_no_verified_return", receiver_message_id=user_item["id"],
                      receiver_turn_id=turn.get("id"))
        if turn.get("status") != "completed" or turn.get("error") or not turn.get("id"):
            return result
        for item in items[items.index(user_item) + 1:]:
            if item.get("type") != "agentMessage" or not item.get("id"):
                continue
            result["observed_reply_message_id"] = item["id"]
            body = item.get("text", "").strip()
            if body.startswith("::chatgpt-content-reference{"):
                result["status"] = "reply_body_unresolved"
            if body == expected:
                result.update(status="verified_round_trip", accepted=True, return_message_id=item["id"])
                return result
        return result
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dispatch", type=Path)
    parser.add_argument("reads", type=Path, nargs="*")
    args = parser.parse_args()
    dispatch = json.loads(args.dispatch.read_text(encoding="utf-8-sig"))
    reads = [json.loads(path.read_text(encoding="utf-8-sig")) for path in args.reads]
    checked = reconcile(dispatch, reads)
    print(json.dumps(checked, ensure_ascii=False, indent=2))
    return 0 if checked["accepted"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
