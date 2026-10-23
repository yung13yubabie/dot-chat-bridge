"""Independent reader argument/response gates, using synthetic callbacks only.

Run ``python -B -m candidate_protocol.redteam.test_reader_contract``.
Retain synthetic SQLite evidence outside the repository; never call real tools.
"""

from contextlib import closing
from copy import deepcopy
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest

from candidate_protocol import Store
from candidate_protocol.transport import Bridge, InjectedChatTransport


DATA = Path(os.environ.get("OFFLINE_READER_CONTRACT_DATA", str(
    Path(tempfile.gettempdir()) / "dot-reader-contract-synthetic-data")))
DATA.mkdir(parents=True, exist_ok=True)
READER_KEYS = {"threadId", "turnLimit", "includeOutputs", "maxOutputCharsPerItem"}
INSTRUCTION = "Compute sum, min and max for [17,41,8,26,53]. Return one JSON object."
EXPECTED = {"sum": 145, "min": 8, "max": 53}


class ReaderContractError(ValueError):
    """Stable synthetic schema error, with no private input in its message."""

    def __init__(self):
        super().__init__("synthetic_reader_contract_rejected")


def enforce_reader_contract(arguments):
    if not isinstance(arguments, dict) or set(arguments) != READER_KEYS:
        raise ReaderContractError()
    limit = arguments["maxOutputCharsPerItem"]
    if type(limit) is not int or not 1 <= limit <= 20000:
        raise ReaderContractError()
    if (arguments["threadId"] != "reader_chat" or arguments["includeOutputs"] is not True
            or type(arguments["turnLimit"]) is not int or arguments["turnLimit"] < 1):
        raise ReaderContractError()


class ReaderContractTests(unittest.TestCase):
    def fixture(self, *, output=None):
        directory = Path(tempfile.mkdtemp(prefix=self._testMethodName + "-", dir=DATA))
        f = SimpleNamespace(path=directory / "synthetic.sqlite", sent=[], reads=[], rejected=[])
        f.store = Store(f.path, lambda: 1000)
        self.addCleanup(f.store.close)
        f.store.create("reader_task", "reader_nonce", "Chat", "reader_chat", 200000)
        f.lease = f.store.claim("reader_task", "reader_worker", 150000)
        f.output = deepcopy(EXPECTED if output is None else output)
        f.response = lambda: self.full_read(f)
        f.truncate_to_requested_limit = False

        def send(arguments):
            f.sent.append(deepcopy(arguments))
            if set(arguments) != {"threadId", "prompt"} or arguments["threadId"] != "reader_chat":
                raise ValueError("synthetic_send_contract_rejected")
            return {"fixture_only": True, "structuredContent": {"threadId": "reader_chat", "kind": "chatgpt"}}

        def read(arguments):
            f.reads.append(deepcopy(arguments))
            try:
                enforce_reader_contract(arguments)
            except ReaderContractError as error:
                f.rejected.append(str(error))
                raise
            if not f.sent:
                return {"fixture_only": True, "structuredContent": {
                    "thread": {"id": "reader_chat", "kind": "chatgpt"}, "turns": []}}
            raw = f.response()
            if f.truncate_to_requested_limit:
                item = raw["structuredContent"]["turns"][0]["items"][1]
                limit = arguments["maxOutputCharsPerItem"]
                if len(item["text"]) > limit:
                    item["text"] = item["text"][:limit]
                    item["truncated"] = True
            f.last_response = deepcopy(raw)
            return raw

        f.read = read
        f.bridge = Bridge(f.store, InjectedChatTransport(send=send, read=read, fixture=True),
                          validate_output=lambda actual: actual == f.output)
        return f

    def full_read(self, f, *, body=None):
        if body is None:
            body = json.dumps({"task_id": "reader_task", "nonce": "reader_nonce", "receiver": "Chat",
                               "return_target": "DOT", "output": f.output}, ensure_ascii=False)
        return {"fixture_only": True, "structuredContent": {
            "thread": {"id": "reader_chat", "kind": "chatgpt"}, "turns": [
                {"id": "reader_turn", "status": "completed", "error": None, "items": [
                    {"type": "userMessage", "id": "reader_user", "content": [
                        {"type": "text", "text": f.sent[-1]["prompt"]}]},
                    {"type": "agentMessage", "id": "reader_assistant", "text": body}]}]}}

    @staticmethod
    def domain(f):
        with closing(sqlite3.connect(f.path)) as database:
            return {table: database.execute("SELECT * FROM " + table + " ORDER BY 1").fetchall()
                    for table in ("tasks", "results", "outbox")}

    def dispatched(self, f):
        outcome = f.bridge.dispatch(f.lease, INSTRUCTION)
        self.assertEqual(outcome["status"], "awaiting_result", (outcome, f.rejected))
        self.assertEqual(len(f.sent), 1)
        self.assertEqual(len(f.reads), 1, "baseline must happen before exactly one synthetic send")
        self.assertEqual(f.rejected, [])

    def rejected_poll(self, f):
        before = self.domain(f)
        outcome = f.bridge.poll(f.lease)
        self.assertEqual(outcome["status"], "blocked", outcome)
        self.assertTrue(outcome.get("code"))
        self.assertIs(outcome.get("live_verified"), False)
        self.assertEqual(self.domain(f), before)
        self.assertEqual((len(f.sent), len(f.reads)), (1, 2))
        self.assertEqual(f.rejected, [], "valid reader args must not conceal a body rejection")

    def test_baseline_and_poll_enforce_documented_reader_contract(self):
        f = self.fixture()
        self.dispatched(f)
        outcome = f.bridge.poll(f.lease)
        self.assertEqual(outcome["status"], "recorded", outcome)
        self.assertIs(outcome.get("live_verified"), False)
        self.assertEqual((len(f.sent), len(f.reads)), (1, 2))
        self.assertEqual(f.rejected, [])
        for arguments in f.reads:
            enforce_reader_contract(arguments)

    def test_synthetic_reader_actually_rejects_bad_values_and_guessed_keys(self):
        valid = {"threadId": "reader_chat", "turnLimit": 20, "includeOutputs": True,
                 "maxOutputCharsPerItem": 20000}
        variants = []
        for limit in (0, 20001, 40000, 65536, True, None):
            arguments = dict(valid, maxOutputCharsPerItem=limit)
            variants.append(arguments)
        for key in ("raw", "includeTurns", "itemsView"):
            variants.append(dict(valid, **{key: True}))
        missing = dict(valid)
        del missing["maxOutputCharsPerItem"]
        variants.append(missing)
        f = self.fixture()
        before = self.domain(f)
        for arguments in variants:
            with self.subTest(arguments=arguments):
                with self.assertRaisesRegex(ReaderContractError, "^synthetic_reader_contract_rejected$"):
                    f.read(arguments)
        self.assertEqual(len(f.rejected), len(variants))
        self.assertEqual(f.sent, [])
        self.assertEqual(self.domain(f), before)

    def test_legal_reader_limit_does_not_dereference_content_reference(self):
        for body in ("::chatgpt-content-reference synthetic", " \n::chatgpt-content-reference synthetic"):
            with self.subTest(body=body):
                f = self.fixture()
                self.dispatched(f)
                raw = self.full_read(f, body=body)
                raw["snippet"] = self.full_read(f)["structuredContent"]["turns"][0]["items"][1]["text"]
                f.response = lambda raw=raw: deepcopy(raw)
                self.rejected_poll(f)

    def test_omitted_empty_body_without_truncation_or_cursor_cannot_use_snippet(self):
        f = self.fixture()
        self.dispatched(f)
        raw = self.full_read(f, body="")
        raw["content_omitted"] = True
        raw["truncated"] = False
        raw["snippet"] = self.full_read(f)["structuredContent"]["turns"][0]["items"][1]["text"]
        self.assertNotIn("cursor", raw)
        f.response = lambda: deepcopy(raw)
        self.rejected_poll(f)

    def test_truncated_flag_overrides_complete_valid_json_and_snippet(self):
        for layer in ("envelope", "payload", "assistant"):
            with self.subTest(layer=layer):
                f = self.fixture()
                self.dispatched(f)
                raw = self.full_read(f)
                item = raw["structuredContent"]["turns"][0]["items"][1]
                raw["snippet"] = item["text"]
                destination = {"envelope": raw, "payload": raw["structuredContent"], "assistant": item}[layer]
                destination["truncated"] = True
                f.response = lambda raw=raw: deepcopy(raw)
                self.rejected_poll(f)

    def test_pagination_markers_block_complete_json_without_followup_reads(self):
        markers = [("cursor", "synthetic_next"), ("nextCursor", "synthetic_next"),
                   ("next_cursor", "synthetic_next"), ("hasMore", True), ("has_more", True)]
        for key, value in markers:
            for layer in ("envelope", "payload"):
                with self.subTest(key=key, layer=layer):
                    f = self.fixture()
                    self.dispatched(f)
                    raw = self.full_read(f)
                    destination = raw if layer == "envelope" else raw["structuredContent"]
                    destination[key] = value
                    f.response = lambda raw=raw: deepcopy(raw)
                    self.rejected_poll(f)

    def test_size_driven_truncation_rejects_even_when_prefix_is_complete_json(self):
        f = self.fixture()
        self.dispatched(f)
        complete_body = self.full_read(f)["structuredContent"]["turns"][0]["items"][1]["text"]
        oversized = self.full_read(f, body=complete_body + "\n" + " " * 25000)
        oversized["snippet"] = complete_body
        f.response = lambda: deepcopy(oversized)
        f.truncate_to_requested_limit = True
        self.rejected_poll(f)
        received = f.last_response["structuredContent"]["turns"][0]["items"][1]
        self.assertIs(received["truncated"], True)
        self.assertEqual(len(received["text"]), f.reads[-1]["maxOutputCharsPerItem"])
        self.assertEqual(json.loads(received["text"])["output"], EXPECTED)

    def test_reader_character_cap_is_not_a_twenty_thousand_byte_body_cap(self):
        f = self.fixture(output={"text": "界" * 18000})
        self.dispatched(f)
        raw = self.full_read(f)
        body = raw["structuredContent"]["turns"][0]["items"][1]["text"]
        self.assertLess(len(body), 20000)
        self.assertGreater(len(body.encode("utf-8")), 20000)
        self.assertLessEqual(len(body.encode("utf-8")), 65536)
        f.response = lambda: deepcopy(raw)
        f.truncate_to_requested_limit = True
        outcome = f.bridge.poll(f.lease)
        self.assertEqual(outcome["status"], "recorded", outcome)
        self.assertIs(outcome.get("live_verified"), False)
        self.assertEqual(f.rejected, [])
        self.assertEqual((len(f.sent), len(f.reads)), (1, 2))
        self.assertEqual(len(self.domain(f)["results"]), 1)

    def test_local_utf8_byte_ceiling_remains_independent_of_reader_arguments(self):
        f = self.fixture(output={"text": "🌙" * 17000})
        self.dispatched(f)
        raw = self.full_read(f)
        body = raw["structuredContent"]["turns"][0]["items"][1]["text"]
        self.assertGreater(len(body.encode("utf-8")), 65536)
        self.assertNotIn("truncated", raw["structuredContent"]["turns"][0]["items"][1])
        before = self.domain(f)
        outcome = f.bridge.accept_read(f.lease, raw)
        self.assertEqual(outcome["status"], "blocked", outcome)
        self.assertEqual(self.domain(f), before)
        self.assertEqual((len(f.sent), len(f.reads)), (1, 1))
        self.assertEqual(f.rejected, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
