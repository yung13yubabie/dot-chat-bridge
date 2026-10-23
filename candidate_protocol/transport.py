"""Injected native Chat tool boundary. No endpoint, auth, worker or live wiring.

Only explicit caller-owned callbacks perform I/O. Synthetic fixtures are not
provider evidence; injected callbacks remain the source-authentication boundary.
"""

from dataclasses import dataclass
import json

from .store import Lease, ProtocolError, Reply, Source, _identifier


# Known accepted native request profile, not a full-content/reference resolver.
_READ_THREAD_REQUEST_CHARS = 20000
# Local validation uses UTF-8 bytes, independently of reader character requests.
_RESULT_BODY_UTF8_BYTES = 65536


def _object_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _constant(value):
    raise ValueError("nonfinite number")


def _json(text):
    try:
        return json.loads(text, object_pairs_hook=_object_pairs, parse_constant=_constant)
    except (ValueError, TypeError, RecursionError):
        raise ProtocolError("invalid_json") from None


def _check_flags(value, depth=0):
    if depth > 64:
        raise ProtocolError("invalid_payload")
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"isError", "content_omitted", "truncated", "hasMore", "has_more"} and child is not False:
                raise ProtocolError("incomplete_payload")
            if key == "success" and child is not True:
                raise ProtocolError("tool_reported_failure")
            if key in {"cursor", "nextCursor", "next_cursor"} and child not in (None, ""):
                raise ProtocolError("incomplete_payload")
            _check_flags(child, depth + 1)
    elif isinstance(value, list):
        for child in value:
            _check_flags(child, depth + 1)


def _payload(raw, fixture):
    if not isinstance(raw, dict) or (fixture and raw.get("fixture_only") is not True):
        raise ProtocolError("invalid_tool_envelope")
    try:
        if len(json.dumps(raw, ensure_ascii=False, allow_nan=False).encode("utf-8")) > 1048576:
            raise ProtocolError("invalid_payload")
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise ProtocolError("invalid_payload") from None
    _check_flags(raw)
    candidates = []
    if "structuredContent" in raw:
        if not isinstance(raw["structuredContent"], dict):
            raise ProtocolError("invalid_tool_envelope")
        candidates.append(raw["structuredContent"])
    content = raw.get("content", [])
    if not isinstance(content, list):
        raise ProtocolError("invalid_tool_envelope")
    if len(content) > 1:
        raise ProtocolError("ambiguous_tool_payload")
    for item in content:
        if not isinstance(item, dict):
            raise ProtocolError("invalid_tool_envelope")
        if item.get("type") == "text":
            candidate = _json(item.get("text"))
            if not isinstance(candidate, dict):
                raise ProtocolError("invalid_tool_envelope")
            candidates.append(candidate)
        else:
            raise ProtocolError("invalid_tool_envelope")
    if not candidates or any(candidate != candidates[0] for candidate in candidates[1:]):
        raise ProtocolError("ambiguous_tool_payload")
    _check_flags(candidates[0])
    return candidates[0]


def _turns(raw, fixture, conversation_id):
    payload = _payload(raw, fixture)
    thread = payload.get("thread")
    if not isinstance(thread, dict) or thread.get("id") != conversation_id or thread.get("kind") != "chatgpt":
        raise ProtocolError("source_mismatch")
    turns = payload.get("turns")
    if not isinstance(turns, list) or len(turns) > 1000:
        raise ProtocolError("invalid_turns")
    seen_turns, seen_messages = set(), set()
    for turn in turns:
        if not isinstance(turn, dict):
            raise ProtocolError("invalid_turns")
        _identifier(turn.get("id"))
        if not isinstance(turn.get("status"), str):
            raise ProtocolError("invalid_turn_status")
        if turn["id"] in seen_turns:
            raise ProtocolError("ambiguous_turn_identity")
        seen_turns.add(turn["id"])
        items = turn.get("items")
        if not isinstance(items, list):
            raise ProtocolError("invalid_turns")
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get("type"), str):
                raise ProtocolError("invalid_turns")
            if item.get("type") in {"userMessage", "agentMessage"}:
                _identifier(item.get("id"))
                if item["id"] in seen_messages:
                    raise ProtocolError("ambiguous_message_identity")
                seen_messages.add(item["id"])
    return turns


def _user_text(item):
    content = item.get("content")
    if not isinstance(content, list) or not content:
        raise ProtocolError("invalid_prompt_evidence")
    if any(not isinstance(part, dict) or part.get("type") != "text" or not isinstance(part.get("text"), str)
           for part in content):
        raise ProtocolError("invalid_prompt_evidence")
    return "\n".join(part["text"] for part in content)


@dataclass(frozen=True)
class InjectedChatTransport:
    """Callbacks accept the documented native tool argument dict, not an endpoint.

    The host must authorize and deadline-bound callbacks before any future live
    use. Synchronous callbacks cannot be safely preempted by this local module.
    """
    send: object
    read: object
    fixture: bool = True


class Bridge:
    def __init__(self, store, transport=None, *, validate_output=None):
        self.store = store
        self.transport = transport
        self.validate_output = validate_output

    def _ready(self):
        if (not isinstance(self.transport, InjectedChatTransport)
                or not callable(self.transport.send) or not callable(self.transport.read)
                or type(self.transport.fixture) is not bool):
            raise ProtocolError("channel_unwired")
        if not callable(self.validate_output):
            raise ProtocolError("validator_unwired")

    def _outcome(self, status, code=None, attempt=None, **fields):
        fixture = isinstance(self.transport, InjectedChatTransport) and self.transport.fixture is True
        result = {"scope": "candidate_transport_fixture" if fixture else "candidate_transport_injected",
                  "status": status, "live_verified": False, "model_policy": "inherit_conversation",
                  "requested_model": attempt.get("requested_model") if attempt else None,
                  "actual_model": None}
        if code:
            result["code"] = code
        result.update(fields)
        return result

    @staticmethod
    def _read_arguments(conversation_id):
        return {"threadId": conversation_id, "turnLimit": 20,
                "includeOutputs": True, "maxOutputCharsPerItem": _READ_THREAD_REQUEST_CHARS}

    def dispatch(self, lease, instruction, requested_model=None):
        attempt = None
        try:
            self._ready()
            if not isinstance(lease, Lease) or not isinstance(instruction, str) or not instruction.strip():
                raise ProtocolError("invalid_input")
            task = self.store.snapshot(lease.task_id)
            if task["target"] != "Chat":
                raise ProtocolError("channel_unwired")
            try:
                self.store.dispatch_snapshot(lease)
            except ProtocolError as error:
                if error.code != "dispatch_not_found":
                    raise
            else:
                raise ProtocolError("dispatch_already_attempted")
            # Fail before any send on a bad/cancelled/expired claim. Reservation
            # repeats the authoritative checks after the baseline read.
            if (task["state"], task["nonce"], task["worker"], task["generation"]) != (
                    "claimed", lease.nonce, lease.worker, lease.generation):
                raise ProtocolError("lease_mismatch")
            request = {"task_id": lease.task_id, "nonce": lease.nonce, "sender": "DOT",
                       "target": "Chat", "return_target": "DOT", "instruction": instruction}
            prompt = ("DOT_BRIDGE_REQUEST\n" + json.dumps(request, ensure_ascii=False, sort_keys=True) +
                      '\nReturn exactly one JSON object with keys task_id, nonce, receiver, return_target, output. '
                      'Copy the request identities, set receiver to Chat and return_target to DOT; '
                      'output must be a JSON object containing the computed result.')
            try:
                baseline = self.transport.read(self._read_arguments(task["conversation_id"]))
            except Exception:
                raise ProtocolError("baseline_unavailable") from None
            turns = _turns(baseline, self.transport.fixture, task["conversation_id"])
            if any(turn.get("status") in {"running", "in_progress", "pending"} for turn in turns):
                raise ProtocolError("receiver_busy")
            baseline_messages = [item["id"] for turn in turns for item in turn["items"]
                                 if item.get("type") in {"userMessage", "agentMessage"}]
            attempt = self.store.reserve_dispatch(lease, prompt, [turn["id"] for turn in turns], requested_model,
                                                  baseline_message_ids=baseline_messages)
        except ProtocolError as error:
            return self._outcome("blocked", error.code, attempt)
        try:
            raw = self.transport.send({"threadId": attempt["conversation_id"], "prompt": attempt["prompt"]})
            receipt = _payload(raw, self.transport.fixture)
            if (receipt.get("threadId") != attempt["conversation_id"] or receipt.get("clientThreadId")
                    or receipt.get("kind") not in (None, "chatgpt")):
                raise ProtocolError("dispatch_unresolved")
            _identifier(receipt.get("threadId"))
            attempt = self.store.bind_dispatch(lease, receipt["threadId"])
        except Exception:
            # Sending may have executed. The durable uncertain entry forbids retry.
            return self._outcome("uncertain", "dispatch_unresolved", attempt)
        return self._outcome("awaiting_result", attempt=attempt)

    def poll(self, lease):
        attempt = None
        try:
            self._ready()
            attempt = self.store.prepare_dispatch_read(lease, consume=True)
            try:
                raw = self.transport.read(self._read_arguments(attempt["conversation_id"]))
            except Exception:
                raise ProtocolError("read_unavailable") from None
        except ProtocolError as error:
            return self._outcome("blocked", error.code, attempt)
        return self.accept_read(lease, raw)

    def accept_read(self, lease, raw):
        """Trusted-host ingress, not a network callback/authentication endpoint."""
        attempt = None
        try:
            self._ready()
            attempt = self.store.prepare_dispatch_read(lease)
            turns = _turns(raw, self.transport.fixture, attempt["conversation_id"])
            candidates = []
            for turn in turns:
                users = [item for item in turn["items"] if item.get("type") == "userMessage"]
                matches = [item for item in users if _user_text(item) == attempt["prompt"]]
                if matches:
                    if (turn["id"] in attempt["baseline_turn_ids"] or len(users) != 1 or len(matches) != 1):
                        raise ProtocolError("stale_or_ambiguous_turn")
                    candidates.append((turn, matches[0]))
            if len(candidates) != 1:
                raise ProtocolError("receiver_turn_unresolved")
            turn, user = candidates[0]
            if turn.get("status") != "completed" or turn.get("error"):
                raise ProtocolError("incomplete_turn")
            if user.get("role", "user") != "user" or user.get("status", "completed") != "completed":
                raise ProtocolError("invalid_user_message")
            user_index = turn["items"].index(user)
            assistants = [item for item in turn["items"][user_index + 1:] if item.get("type") == "agentMessage"]
            if not assistants:
                raise ProtocolError("body_unavailable")
            finals = [item for item in assistants if item.get("phase", "final") == "final"]
            if len(finals) != 1 or assistants[-1] is not finals[0]:
                raise ProtocolError("ambiguous_final_assistant")
            reply = finals[0]
            if user["id"] in attempt["baseline_message_ids"] or reply["id"] in attempt["baseline_message_ids"]:
                raise ProtocolError("stale_message_identity")
            if (reply.get("role", "assistant") != "assistant" or reply.get("phase", "final") != "final"
                    or reply.get("status", "completed") != "completed"):
                raise ProtocolError("not_final_assistant")
            body = reply.get("text")
            if not isinstance(body, str) or not body.strip():
                raise ProtocolError("body_unavailable")
            try:
                if len(body.encode("utf-8")) > _RESULT_BODY_UTF8_BYTES:
                    raise ProtocolError("invalid_body")
            except UnicodeEncodeError:
                raise ProtocolError("invalid_body") from None
            result = _json(body)
            if (not isinstance(result, dict) or set(result) != {"task_id", "nonce", "receiver", "return_target", "output"}
                    or (result["task_id"], result["nonce"], result["receiver"], result["return_target"]) != (
                        lease.task_id, lease.nonce, "Chat", "DOT") or not isinstance(result["output"], dict)):
                raise ProtocolError("result_mismatch")
            try:
                valid = self.validate_output(result["output"])
            except Exception:
                valid = False
            if valid is not True:
                raise ProtocolError("output_invalid")
            outcome = self.store.ingest_transport(lease, Source("Chat", attempt["conversation_id"]),
                Reply(lease.task_id, lease.nonce, lease.generation, lease.worker, reply["id"], body, "Chat"),
                turn["id"], user["id"])
            return self._outcome(outcome["status"], attempt=attempt,
                                 task_id=outcome["task_id"], event_id=outcome["event_id"])
        except ProtocolError as error:
            return self._outcome("blocked", error.code, attempt)
