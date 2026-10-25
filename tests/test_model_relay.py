"""Protocol tests with a fake upstream; no provider or model is contacted."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from email.message import Message
import io
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace

from runner.model_relay import (FixedUpstream, Limits, MODEL, ProtocolError, Relay,
                                RelayHandler, RelayServer, Rejected, StreamTracker, encoded)


PROVIDER_KEY = "provider-secret-do-not-log-xxxxxxxxxxxxxxxx"
SESSION_TOKEN = "research-temporary-token-xxxxxxxxxxxxxxxxxx"
PROMPT = "private prompt marker must never be in relay evidence"


def frame(kind, **value):
    return b"event: " + kind.encode() + b"\ndata: " + encoded({"type": kind, **value}) + b"\n\n"


def stream(output=3, model=MODEL):
    return (frame("message_start", message={"id": "test", "model": model,
                                          "content": [], "usage": {"input_tokens": 9, "output_tokens": 0}}) +
            frame("content_block_start", index=0, content_block={"type": "text", "text": ""}) +
            frame("content_block_delta", index=0, delta={"type": "text_delta", "text": "ok"}) +
            frame("content_block_stop", index=0) +
            frame("message_delta", delta={"stop_reason": "end_turn"}, usage={"output_tokens": output}) +
            frame("message_stop"))


class FakeResponse:
    def __init__(self, status=200, body=None, headers=None):
        self.status = status
        self.headers = Message()
        for key, value in (headers or {"Content-Type": "text/event-stream", "request-id": "test-request"}).items():
            self.headers[key] = value
        self.body = io.BytesIO(stream() if body is None else body)
        self.closed = False

    def readline(self, size):
        return self.body.readline(size)

    def close(self):
        self.closed = True


class FakeUpstream:
    def __init__(self, response=None):
        self.response = response or FakeResponse()
        self.calls = []

    def __call__(self, body, timeout):
        self.calls.append((json.loads(body), timeout))
        self.last_body = body
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def request(**overrides):
    return {"model": MODEL, "max_tokens": 10, "stream": True,
            "messages": [{"role": "user", "content": PROMPT}], **overrides}


class RelayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.relays = []

    def tearDown(self):
        for relay in self.relays:
            relay.events.close()
        self.tmp.cleanup()

    def relay(self, response=None, limits=None, clock=time.monotonic):
        fake = FakeUpstream(response)
        result = Relay(PROVIDER_KEY, SESSION_TOKEN, self.root / f"events-{len(self.relays)}.jsonl",
                       limits or Limits(request_output_limit=10, session_output_limit=30),
                       upstream=fake, clock=clock)
        self.relays.append(result)
        return result

    def dispatch(self, relay, value=None, emit=None):
        value, temperature = relay.validate(encoded(value or request()))
        item = relay.ledger.reserve(value["max_tokens"], temperature, request_body=value)
        value["max_tokens"] = item.effective
        frames = []
        relay.stream(item, encoded(value), lambda: None, emit or frames.append)
        return b"".join(frames)

    def test_frozen_wire_policy_admits_only_matching_system_and_tools(self):
        value = request(system="frozen system", tools=[{"name": "bash", "input_schema": {"type": "object"}}])
        expected = {"expected_" + field + "_sha256": hashlib.sha256(encoded(value[field])).hexdigest()
                    for field in ("system", "tools")}
        relay = self.relay(limits=Limits(request_output_limit=10, session_output_limit=30, **expected))
        self.dispatch(relay, value)
        self.assertEqual(len(relay.upstream.calls), 1)
        self.assertEqual(relay.ledger.status()["successful_requests"], 1)
        self.assertEqual(relay.ledger.status()["limits"]["expected_system_sha256"], expected["expected_system_sha256"])

    def test_wire_policy_mismatch_is_sticky_before_upstream_or_reservation(self):
        original = request(system="frozen system", tools=[])
        expected = {"expected_" + field + "_sha256": hashlib.sha256(encoded(original[field])).hexdigest()
                    for field in ("system", "tools")}
        for field in ("system", "tools"):
            relay = self.relay(limits=Limits(request_output_limit=10, session_output_limit=30, **expected))
            changed = {**original}
            changed.pop(field)
            with self.assertRaisesRegex(Rejected, "request_policy_mismatch"):
                self.dispatch(relay, changed)
            with self.assertRaisesRegex(Rejected, "relay_failed_closed"):
                self.dispatch(relay, original)
            state = relay.ledger.status()
            self.assertEqual(state["state"], "failed_closed")
            self.assertEqual(state["request_count"], 0)
            self.assertEqual(state["reserved_output_tokens"], 0)
            self.assertEqual(state["charged_output_tokens"], 0)
            self.assertEqual(relay.upstream.calls, [])
            evidence = (self.root / f"events-{len(self.relays)-1}.jsonl").read_text()
            self.assertNotIn(PROMPT, evidence)
            self.assertNotIn("frozen system", evidence)
            self.assertIn("request_policy_rejected", evidence)

    def test_frozen_wire_policy_requires_two_exact_hashes(self):
        for settings in ({"expected_system_sha256": "a" * 64},
                         {"expected_system_sha256": "a" * 64, "expected_tools_sha256": "B" * 64}):
            with self.assertRaises(ValueError):
                Limits(**settings)

    def test_native_compaction_is_exact_and_shares_research_budget(self):
        research = request(system="research", tools=[{"name": "bash", "input_schema": {"type": "object"}}])
        summary = request(system="native summary")
        hashes = {"expected_" + field + "_sha256": hashlib.sha256(encoded(research[field])).hexdigest()
                  for field in ("system", "tools")}
        compaction_sha = hashlib.sha256(encoded(summary["system"])).hexdigest()
        limits = Limits(request_output_limit=6, session_output_limit=6,
                        expected_compaction_system_sha256=compaction_sha, **hashes)
        relay = self.relay(limits=limits)
        self.dispatch(relay, research)
        relay.upstream = FakeUpstream()
        self.dispatch(relay, summary)
        self.assertEqual(relay.ledger.status()["charged_output_tokens"], 6)
        self.assertEqual(relay.ledger.status()["successful_requests"], 2)
        self.assertEqual(relay.ledger.status()["failed_requests"], 0)
        with self.assertRaises(Rejected):
            self.dispatch(relay, research)
        events = [json.loads(line) for line in (self.root / "events-0.jsonl").read_text().splitlines()]
        self.assertEqual([row["request_kind"] for row in events if row["event"] == "request_accepted"],
                         ["research", "native_compaction"])
        for malformed in ({**summary, "tools": []}, {**summary, "tools": None},
                          {**summary, "tools": research["tools"]}, {**summary, "system": "unknown"},
                          request(system="research")):
            broken = self.relay(limits=limits)
            with self.assertRaises(Rejected):
                self.dispatch(broken, malformed)
            self.assertEqual(broken.upstream.calls, [])
        old = self.relay(limits=Limits(**hashes))
        with self.assertRaisesRegex(Rejected, "request_policy_mismatch"):
            self.dispatch(old, summary)
        for kwargs in ({"expected_compaction_system_sha256": compaction_sha},
                       {**hashes, "expected_compaction_system_sha256": hashes["expected_system_sha256"]},
                       {**hashes, "expected_compaction_system_sha256": "BAD"}):
            with self.assertRaises(ValueError):
                Limits(**kwargs)

    def test_200k_budget_is_shared_and_last_request_is_trimmed(self):
        research = request(max_tokens=16384, system="research", tools=[])
        summary = request(max_tokens=16384, system="native summary")
        hashes = {"expected_" + field + "_sha256": hashlib.sha256(encoded(research[field])).hexdigest()
                  for field in ("system", "tools")}
        relay = self.relay(limits=Limits(request_output_limit=4096, session_output_limit=200000,
            max_requests=3125, expected_compaction_system_sha256=hashlib.sha256(encoded(summary["system"])).hexdigest(),
            **hashes))
        effective = []

        def upstream(body, timeout):
            effective.append(json.loads(body)["max_tokens"])
            return FakeResponse(body=stream(output=effective[-1]))

        relay.upstream = upstream
        for index in range(49):
            self.dispatch(relay, research if index % 2 == 0 else summary)
        self.assertEqual(effective, [4096] * 48 + [3392])
        status = relay.ledger.status()
        self.assertEqual(status["charged_output_tokens"], 200000)
        self.assertEqual(status["successful_requests"], 49)
        self.assertEqual(status["failed_requests"], 0)
        with self.assertRaisesRegex(Rejected, "budget_exhausted"):
            self.dispatch(relay, research)

    def test_scaled_request_guard_allows_more_than_512_calls(self):
        relay = self.relay(limits=Limits(session_output_limit=200000, max_requests=3125))
        relay.upstream = lambda body, timeout: FakeResponse(body=stream(output=1))
        for _ in range(513):
            self.dispatch(relay, request(max_tokens=1))
        status = relay.ledger.status()
        self.assertEqual(status["successful_requests"], 513)
        self.assertEqual(status["charged_output_tokens"], 513)
        self.assertFalse(status["budget_exhausted"])

    def test_cli_passes_scaled_limits_to_running_relay(self):
        from runner.model_relay import main
        with patch("runner.model_relay.Relay") as relay, patch("runner.model_relay.RelayServer"):
            main(["--events", str(self.root / "cli.jsonl"), "--session-output-limit", "200000",
                  "--max-requests", "3125"])
        limits = relay.call_args.args[3]
        self.assertEqual(limits.session_output_limit, 200000)
        self.assertEqual(limits.request_output_limit, 4096)
        self.assertEqual(limits.max_requests, 3125)

    @contextmanager
    def server(self, relay):
        # Exercise the actual stdlib HTTP parser without binding a network port.
        yield SimpleNamespace(relay=relay)

    def http(self, address, path="/v1/messages", value=None, headers=None, method="POST"):
        body = encoded(value or request()) if method == "POST" else b""
        supplied = {"Content-Type": "application/json", "x-api-key": SESSION_TOKEN}
        supplied.update(headers or {})
        supplied.setdefault("Content-Length", str(len(body)))
        wire = f"{method} {path} HTTP/1.1\r\nHost: relay\r\n".encode()
        wire += b"".join(f"{key}: {value}\r\n".encode() for key, value in supplied.items())
        wire += b"\r\n" + body

        class Connection:
            def __init__(self):
                self.output = bytearray()

            def makefile(self, *_):
                return io.BytesIO(wire)

            def sendall(self, data):
                self.output.extend(data)

        connection = Connection()
        RelayHandler(connection, ("127.0.0.1", 12345), address)
        head, data = bytes(connection.output).split(b"\r\n\r\n", 1)
        return int(head.split(b" ")[1]), data

    def test_complete_stream_refunds_only_known_usage_and_keeps_evidence_private(self):
        relay = self.relay()
        output = self.dispatch(relay)
        self.assertTrue(output.endswith(frame("message_stop")))
        state = relay.ledger.status()
        self.assertEqual((state["successful_requests"], state["charged_output_tokens"],
                          state["reserved_output_tokens"], state["remaining_output_tokens"]), (1, 3, 0, 27))
        log = (self.root / "events-0.jsonl").read_text()
        for secret in (PROVIDER_KEY, SESSION_TOKEN, PROMPT, "test-request"):
            self.assertNotIn(secret, log)
        self.assertIn("upstream_request_id_sha256", log)
        self.assertEqual((self.root / "events-0.jsonl").stat().st_mode & 0o777, 0o600)

    def test_http_failures_and_redirects_never_refund_or_follow(self):
        for status in (301, 307, 401, 429, 500):
            with self.subTest(status=status):
                relay = self.relay(FakeResponse(status, (PROVIDER_KEY + PROMPT).encode(),
                                               {"Location": "https://attacker.invalid/", "request-id": PROVIDER_KEY}))
                with self.assertRaises(Rejected) as caught:
                    self.dispatch(relay)
                self.assertEqual(caught.exception.status, status if status >= 400 else 502)
                state = relay.ledger.status()
                self.assertEqual(state["last_request_outcome"], "upstream_http_error")
                self.assertEqual(state["last_upstream_status"], status)
                self.assertEqual(state["charged_output_tokens"], 10)
                self.assertEqual(len(relay.upstream.calls), 1)
        for path in self.root.iterdir():
            self.assertNotIn(PROVIDER_KEY, path.read_text())
            self.assertNotIn(PROMPT, path.read_text())

    def test_200_sse_error_is_not_success_and_is_sanitized(self):
        relay = self.relay(FakeResponse(body=frame("error", error={"type": "overloaded_error", "message": PROVIDER_KEY + PROMPT})))
        output = self.dispatch(relay)
        self.assertIn(b"event: error", output)
        self.assertNotIn(PROVIDER_KEY.encode(), output)
        self.assertNotIn(PROMPT.encode(), output)
        state = relay.ledger.status()
        self.assertEqual((state["last_request_outcome"], state["successful_requests"],
                          state["charged_output_tokens"]), ("stream_error", 0, 10))

    def test_missing_terminal_and_initial_usage_only_never_refund(self):
        bodies = [stream().removesuffix(frame("message_stop")),
                  frame("message_start", message={"model": MODEL, "usage": {"output_tokens": 0}}),
                  frame("message_start", message={"model": MODEL, "usage": {"output_tokens": 0}}) + frame("message_stop")]
        for body in bodies:
            relay = self.relay(FakeResponse(body=body))
            self.dispatch(relay)
            state = relay.ledger.status()
            self.assertEqual(state["charged_output_tokens"], 10)
            self.assertTrue(state["protocol_violation"])
            self.assertEqual(state["last_request_outcome"], "protocol_error")

    def test_initial_and_nonterminal_output_usage_cannot_decrease_for_refund(self):
        starts = [
            frame("message_start", message={"model": MODEL, "usage": {"output_tokens": 8}}),
            frame("message_start", message={"model": MODEL, "usage": {"output_tokens": 0}}) +
            frame("message_delta", delta={}, usage={"output_tokens": 9}),
        ]
        for prefix in starts:
            body = prefix + frame("message_delta", delta={"stop_reason": "end_turn"},
                                  usage={"output_tokens": 3}) + frame("message_stop")
            relay = self.relay(FakeResponse(body=body))
            output = self.dispatch(relay)
            state = relay.ledger.status()
            self.assertEqual(state["charged_output_tokens"], 10)
            self.assertEqual(state["successful_requests"], 0)
            self.assertTrue(state["protocol_violation"])
            self.assertEqual(state["last_request_failure_reason"], "usage_decreased")
            self.assertNotIn(b"event: message_stop", output)
            row = json.loads((self.root / f"events-{len(self.relays) - 1}.jsonl").read_text().splitlines()[-1])
            self.assertEqual(row["usage_violation"], {"field": "output_tokens", "previous": 8 if prefix == starts[0] else 9, "observed": 3})

    def test_input_and_cache_revisions_do_not_invalidate_output_accounting(self):
        for field in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"):
            prefix = frame("message_start", message={"model": MODEL, "usage": {field: 9, "output_tokens": 0}})
            body = prefix + frame("message_delta", delta={"stop_reason": "end_turn"},
                                  usage={field: 3, "output_tokens": 3}) + frame("message_stop")
            relay = self.relay(FakeResponse(body=body))
            output = self.dispatch(relay)
            state = relay.ledger.status()
            self.assertIsNone(state["last_request_failure_reason"])
            self.assertEqual(state["charged_output_tokens"], 3)
            self.assertEqual(state["successful_requests"], 1)
            self.assertFalse(state["protocol_violation"])
            self.assertIn(b"event: message_stop", output)
            row = json.loads((self.root / f"events-{len(self.relays) - 1}.jsonl").read_text().splitlines()[-1])
            self.assertTrue(row["output_usage_complete"])
            self.assertIsNone(row["usage_violation"])
            self.assertEqual(row[field], 3)
            self.assertEqual(row["input_usage_revisions"], {
                field: {"count": 1, "first_previous": 9, "last_previous": 9, "last_observed": 3}})

    def test_heat_g3_input_revision_keeps_final_usage_and_shared_budget(self):
        # Reproduce the observed 268 -> 140 input correction; the remaining
        # values are synthetic so this fixture is not a claimed full raw replay.
        initial = {"input_tokens": 268, "cache_read_input_tokens": 1000, "output_tokens": 0}
        final = {"input_tokens": 140, "cache_read_input_tokens": 1128, "output_tokens": 3}
        body = (frame("message_start", message={"model": MODEL, "usage": initial}) +
                frame("message_delta", delta={"stop_reason": "tool_use"}, usage=final) + frame("message_stop"))
        relay = self.relay(FakeResponse(body=body), limits=Limits(request_output_limit=6, session_output_limit=6))
        self.dispatch(relay)
        relay.upstream = FakeUpstream(FakeResponse(body=body))
        self.dispatch(relay)
        with self.assertRaises(Rejected):
            self.dispatch(relay)
        self.assertEqual(relay.ledger.status()["charged_output_tokens"], 6)
        self.assertEqual(relay.ledger.status()["successful_requests"], 2)
        row = json.loads((self.root / "events-0.jsonl").read_text().splitlines()[-1])
        for field, value in final.items():
            self.assertEqual(row[field], value)

    def test_input_revision_does_not_allow_output_decrease_or_incomplete_refund(self):
        for final_output, terminal in ((3, True), (9, False)):
            body = (frame("message_start", message={"model": MODEL, "usage": {"input_tokens": 268, "output_tokens": 8}}) +
                    frame("message_delta", delta={"stop_reason": "end_turn"},
                          usage={"input_tokens": 140, "output_tokens": final_output}))
            if terminal:
                body += frame("message_stop")
            relay = self.relay(FakeResponse(body=body))
            output = self.dispatch(relay)
            state = relay.ledger.status()
            self.assertEqual(state["charged_output_tokens"], 10)
            self.assertTrue(state["protocol_violation"])
            self.assertNotIn(b"event: message_stop", output)
            self.assertEqual(state["last_request_failure_reason"], "usage_decreased" if terminal else "incomplete_stream")

    def test_invalid_revised_input_usage_still_fails_closed(self):
        for field in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"):
            for invalid in (-1, 1.5, True, "140", 2**63):
                body = (frame("message_start", message={"model": MODEL, "usage": {field: 268, "output_tokens": 0}}) +
                        frame("message_delta", delta={"stop_reason": "end_turn"},
                              usage={field: invalid, "output_tokens": 3}) + frame("message_stop"))
                relay = self.relay(FakeResponse(body=body))
                self.dispatch(relay)
                state = relay.ledger.status()
                self.assertEqual(state["last_request_failure_reason"], "invalid_usage")
                self.assertEqual(state["charged_output_tokens"], 10)

    def test_repeated_input_revisions_keep_bounded_audit_and_latest_present_count(self):
        body = frame("message_start", message={"model": MODEL, "usage": {"input_tokens": 268, "output_tokens": 0}})
        for count in (140, 160, 120):
            body += frame("message_delta", delta={}, usage={"input_tokens": count, "output_tokens": 1})
        body += frame("message_delta", delta={"stop_reason": "end_turn"}, usage={"output_tokens": 3}) + frame("message_stop")
        relay = self.relay(FakeResponse(body=body))
        self.dispatch(relay)
        row = json.loads((self.root / "events-0.jsonl").read_text().splitlines()[-1])
        self.assertEqual(row["input_tokens"], 120)
        self.assertEqual(row["input_usage_revisions"], {"input_tokens": {
            "count": 2, "first_previous": 268, "last_previous": 160, "last_observed": 120}})
        self.assertEqual(row["charged_output_tokens"], 3)

    def test_delta_input_and_cache_updates_are_recorded_after_complete_stream(self):
        initial = {"input_tokens": 2, "cache_read_input_tokens": 4, "cache_creation_input_tokens": None, "output_tokens": 0}
        final = {"input_tokens": 9, "cache_read_input_tokens": 8, "cache_creation_input_tokens": 3, "output_tokens": 3}
        body = (frame("message_start", message={"model": MODEL, "usage": initial}) +
                frame("message_delta", delta={}, usage={"input_tokens": 4, "output_tokens": 2}) +
                frame("message_delta", delta={"stop_reason": "end_turn"}, usage=final) + frame("message_stop"))
        relay = self.relay(FakeResponse(body=body))
        self.dispatch(relay)
        row = json.loads((self.root / "events-0.jsonl").read_text().splitlines()[-1])
        for field, value in final.items():
            self.assertEqual(row[field], value)
        self.assertEqual(row["refunded_output_tokens"], 7)
        self.assertTrue(row["output_usage_complete"])
        self.assertIsNone(row["failure_reason"])

    def test_later_usage_cannot_reuse_an_earlier_stop_reason_for_refund(self):
        body = (stream().removesuffix(frame("message_stop")) +
                frame("message_delta", delta={}, usage={"output_tokens": 9}) + frame("message_stop"))
        relay = self.relay(FakeResponse(body=body))
        self.dispatch(relay)
        state = relay.ledger.status()
        self.assertEqual(state["charged_output_tokens"], 10)
        self.assertEqual(state["last_request_failure_reason"], "event_after_terminal")
        self.assertTrue(state["protocol_violation"])

    def test_error_after_terminal_is_not_exposed_as_success(self):
        relay = self.relay(FakeResponse(body=stream() + frame("error", error={"message": PROMPT})))
        output = self.dispatch(relay)
        self.assertNotIn(b"event: message_stop", output)
        self.assertEqual(relay.ledger.status()["charged_output_tokens"], 10)

    def test_thinking_model_change_and_oversized_usage_fail_closed(self):
        thinking = frame("message_start", message={"model": MODEL}) + frame(
            "content_block_start", content_block={"type": "thinking", "thinking": "do not expose"})
        for body in (thinking, stream(11), stream(model="different-model")):
            relay = self.relay(FakeResponse(body=body))
            output = self.dispatch(relay)
            self.assertNotIn(b"do not expose", output)
            self.assertTrue(relay.ledger.status()["protocol_violation"])
            with self.assertRaises(Rejected) as caught:
                relay.ledger.reserve(1, None)
            self.assertEqual(caught.exception.code, "relay_failed_closed")

    def test_missing_invalid_and_unbounded_max_tokens_rejected(self):
        for value in (None, True, 0, -1, 1.2, "10", 2**31):
            relay = self.relay()
            body = request(max_tokens=value)
            if value is None:
                del body["max_tokens"]
            with self.assertRaises(Rejected):
                relay.validate(encoded(body))
            self.assertFalse(relay.upstream.calls)
            self.assertEqual(relay.ledger.status()["request_count"], 0)

    def test_request_over_cap_is_clamped_and_frozen_policy_overrides(self):
        relay = self.relay()
        self.dispatch(relay, request(max_tokens=16384, temperature=1.9,
                                     thinking={"type": "enabled", "budget_tokens": 99},
                                     output_config={"effort": "max"}, top_p=0.1, top_k=1,
                                     service_tier="fast", container="some-container"))
        body = relay.upstream.calls[0][0]
        self.assertEqual(body["max_tokens"], 10)
        self.assertEqual(body["thinking"], {"type": "disabled"})
        self.assertEqual(body["temperature"], 0.0)
        self.assertEqual(body["top_p"], 1.0)
        for field in ("output_config", "top_k", "service_tier", "container"):
            self.assertNotIn(field, body)
        log = (self.root / "events-0.jsonl").read_text()
        self.assertIn('"requested_max_tokens":16384', log)
        self.assertIn('"requested_temperature":1.9', log)

    def test_thinking_max_forces_wire_policy_and_charges_full_stream(self):
        reasoning = (frame("content_block_start", index=1, content_block={"type": "thinking", "thinking": ""}) +
                     frame("content_block_delta", index=1, delta={"type": "thinking_delta", "thinking": PROMPT}) +
                     frame("content_block_delta", index=1, delta={"type": "signature_delta", "signature": "test-signature"}) +
                     frame("content_block_stop", index=1))
        body = stream(10).replace(frame("content_block_start", index=0, content_block={"type": "text", "text": ""}),
                                 reasoning + frame("content_block_start", index=0, content_block={"type": "text", "text": ""}))
        relay = self.relay(FakeResponse(body=body), limits=Limits(request_output_limit=10, session_output_limit=15,
                                                               thinking_effort="max"))
        output = self.dispatch(relay, request(max_tokens=30, temperature=1, thinking={"type": "disabled"},
                                              output_config={"effort": "low"}))
        self.assertIn(PROMPT.encode(), output)
        self.assertIn(b"event: message_stop", output)
        sent = relay.upstream.calls[0][0]
        self.assertEqual(sent["thinking"], {"type": "enabled"})
        self.assertEqual(sent["output_config"], {"effort": "max"})
        self.assertNotIn("temperature", sent)
        self.assertEqual(relay.ledger.status()["charged_output_tokens"], 10)
        relay.upstream.response = FakeResponse(body=stream(5))
        self.dispatch(relay)
        self.assertEqual(relay.upstream.calls[1][0]["max_tokens"], 5)
        with self.assertRaises(Rejected):
            relay.ledger.reserve(1, None)
        log = (self.root / "events-0.jsonl").read_text()
        self.assertNotIn(PROMPT, log)
        self.assertIn('"effective_output_config":{"effort":"max"}', log)

    def test_thinking_max_cannot_relax_usage_or_effort_validation(self):
        relay = self.relay(FakeResponse(body=stream(11)),
                           limits=Limits(request_output_limit=10, session_output_limit=30, thinking_effort="max"))
        self.assertNotIn(b"event: message_stop", self.dispatch(relay))
        self.assertTrue(relay.ledger.status()["protocol_violation"])
        with self.assertRaises(ValueError):
            Limits(thinking_effort="high")

    def test_actual_body_system_and_tools_hashes_and_optional_cache_usage(self):
        body = stream().replace(b'"input_tokens":9', b'"input_tokens":9,"cache_read_input_tokens":30,"cache_creation_input_tokens":4')
        relay = self.relay(FakeResponse(body=body))
        supplied = request(system="private system", tools=[{"name": "exec", "input_schema": {"type": "object"}}])
        self.dispatch(relay, supplied)
        rows = [json.loads(line) for line in (self.root / "events-0.jsonl").read_text().splitlines()]
        accepted, finished = rows[1:]
        self.assertEqual(accepted["body_sha256"], hashlib.sha256(relay.upstream.last_body).hexdigest())
        self.assertEqual(accepted["system_sha256"], hashlib.sha256(encoded(supplied["system"])).hexdigest())
        self.assertEqual(accepted["tools_sha256"], hashlib.sha256(encoded(supplied["tools"])).hexdigest())
        self.assertEqual((finished["input_tokens"], finished["cache_read_input_tokens"],
                          finished["cache_creation_input_tokens"]), (9, 30, 4))
        self.assertNotIn("private system", json.dumps(rows))
        relay = self.relay()
        self.dispatch(relay)
        finished = json.loads((self.root / "events-1.jsonl").read_text().splitlines()[-1])
        self.assertIsNone(finished["cache_read_input_tokens"])
        self.assertIsNone(finished["cache_creation_input_tokens"])

    def test_concurrent_reservations_cannot_exceed_remaining(self):
        relay = self.relay(limits=Limits(request_output_limit=10, session_output_limit=23))
        barrier = threading.Barrier(8)

        def accept(_):
            barrier.wait()
            try:
                return relay.ledger.reserve(16384, None)
            except Rejected:
                return None

        with ThreadPoolExecutor(max_workers=8) as pool:
            items = [item for item in pool.map(accept, range(8)) if item is not None]
        self.assertEqual(sorted(item.effective for item in items), [3, 10, 10])
        self.assertEqual(relay.ledger.status()["reserved_output_tokens"], 23)
        for item in items:
            relay.ledger.finish(item, "upstream_http_error", 429)
        self.assertEqual(relay.ledger.status()["charged_output_tokens"], 23)
        with self.assertRaises(Rejected) as caught:
            relay.ledger.reserve(1, None)
        self.assertEqual(caught.exception.code, "budget_exhausted")

    def test_successful_retry_does_not_retain_failure_as_last_outcome(self):
        relay = self.relay(FakeResponse(429, b"rate limit"))
        with self.assertRaises(Rejected):
            self.dispatch(relay)
        relay.upstream.response = FakeResponse()
        self.dispatch(relay)
        state = relay.ledger.status()
        self.assertEqual((state["failed_requests"], state["successful_requests"],
                          state["last_request_outcome"], state["last_upstream_status"]), (1, 1, "success", 200))

    def test_unknown_transport_usage_reserves_full_and_does_not_log_exception(self):
        for error, outcome in ((OSError(PROVIDER_KEY + PROMPT), "upstream_transport_error"),
                               (TimeoutError(PROVIDER_KEY), "upstream_timeout")):
            relay = self.relay(error)
            with self.assertRaises(Rejected):
                self.dispatch(relay)
            state = relay.ledger.status()
            self.assertEqual((state["charged_output_tokens"], state["last_request_outcome"]), (10, outcome))
        for path in self.root.iterdir():
            self.assertNotIn(PROVIDER_KEY, path.read_text())
            self.assertNotIn(PROMPT, path.read_text())

    def test_truncated_compressed_non_sse_and_large_response_fail_closed(self):
        responses = [FakeResponse(body=b"event: ping\ndata: {}"),
                     FakeResponse(headers={"Content-Type": "application/json"}),
                     FakeResponse(headers={"Content-Type": "text/event-stream", "Content-Encoding": "gzip"}),
                     FakeResponse(body=b"data: " + b"x" * 65536 + b"\n\n")]
        for response in responses:
            relay = self.relay(response)
            try:
                self.dispatch(relay)
            except Rejected as error:
                self.assertEqual(error.status, 502)
            self.assertTrue(relay.ledger.status()["protocol_violation"])
            self.assertTrue(response.closed)

    def test_json_duplicate_nonfinite_unknown_fields_and_model_changes(self):
        relay = self.relay()
        for body in (encoded(request(model="other")), encoded(request(stream=False)),
                     encoded(request(url="https://attacker.invalid")),
                     encoded(request(tools=[{"type": "web_search"}])),
                     b'{"model":"a","model":"b"}', b'{"x":NaN}', b'{"x":1e999}'):
            with self.assertRaises(Rejected):
                relay.validate(body)

    def test_fresh_owner_only_event_file_required(self):
        relay = self.relay()
        with self.assertRaises(FileExistsError):
            Relay(PROVIDER_KEY, SESSION_TOKEN, self.root / "events-0.jsonl", upstream=relay.upstream)
        (self.root / "link.jsonl").symlink_to(self.root / "events-0.jsonl")
        with self.assertRaises(OSError):
            Relay(PROVIDER_KEY, SESSION_TOKEN, self.root / "link.jsonl", upstream=relay.upstream)

    def test_session_expiry_and_request_deadline(self):
        now = [100.0]
        relay = self.relay(clock=lambda: now[0])
        with self.assertRaises(Rejected) as caught:
            relay.ledger.reserve(10, None, deadline=99.0)
        self.assertEqual(caught.exception.code, "request_timeout")
        now[0] += relay.limits.session_seconds
        with self.assertRaises(Rejected) as caught:
            relay.ledger.reserve(10, None)
        self.assertEqual(caught.exception.code, "session_expired")
        self.assertTrue(relay.ledger.status()["expired"])

    def test_evidence_failure_prevents_upstream_and_closes_admission(self):
        relay = self.relay()
        with patch.object(relay.events, "append", side_effect=OSError("disk full")):
            with self.assertRaises(Rejected):
                self.dispatch(relay)
        self.assertFalse(relay.upstream.calls)
        self.assertTrue(relay.ledger.status()["evidence_error"])

    def test_http_health_requires_no_auth_and_status_requires_session_auth(self):
        relay = self.relay()
        with self.server(relay) as address:
            status, data = self.http(address, "/health", headers={"x-api-key": ""}, method="GET")
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(data)["state"], "ready")
            status, _ = self.http(address, "/status", headers={"x-api-key": "wrong"}, method="GET")
            self.assertEqual(status, 401)
            status, data = self.http(address, "/status", method="GET")
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(data)["request_count"], 0)
        self.assertFalse(relay.upstream.calls)
        self.assertNotIn(SESSION_TOKEN.encode(), data)
        self.assertNotIn(PROVIDER_KEY.encode(), data)

    def test_http_request_stream_and_no_header_forwarding(self):
        relay = self.relay()
        with self.server(relay) as address:
            status, data = self.http(address, headers={"anthropic-beta": "attacker", "X-Upstream-URL": "http://attacker"})
            self.assertEqual(status, 200)
            self.assertIn(b"event: message_stop", data)
        # The fake's entire call contract is bytes + numeric timeout, no caller headers.
        self.assertEqual(len(relay.upstream.calls), 1)
        self.assertNotIn("attacker", json.dumps(relay.upstream.calls))

    def test_http_rejects_path_compression_chunking_and_conflicting_auth(self):
        relay = self.relay()
        with self.server(relay) as address:
            for path in ("/v1/messages?url=x", "/anthropic/v1/messages", "https://attacker.invalid/v1/messages"):
                self.assertEqual(self.http(address, path)[0], 404)
            for headers, status in (({"Content-Encoding": "gzip"}, 415),
                                    ({"Transfer-Encoding": "chunked"}, 400),
                                    ({"Authorization": "Bearer wrong"}, 401),
                                    ({"x-api-key": PROVIDER_KEY}, 401),
                                    ({"Content-Length": "1000000000"}, 413)):
                self.assertEqual(self.http(address, headers=headers)[0], status)
        self.assertFalse(relay.upstream.calls)

    def test_fixed_upstream_url_and_headers_no_redirect_or_proxy(self):
        response = FakeResponse(307)

        class Connection:
            sock = None

            def connect(self):
                pass

            def request(self, *args, **kwargs):
                self.args, self.kwargs = args, kwargs

            def getresponse(self):
                return response

            def close(self):
                pass

        connection = Connection()
        with patch("runner.model_relay.http.client.HTTPSConnection", return_value=connection) as factory:
            result = FixedUpstream(PROVIDER_KEY)(b"{}", 1)
            result.close()
        self.assertEqual(factory.call_args.args, ("api.deepseek.com", 443))
        self.assertEqual(connection.args, ("POST", "/anthropic/v1/messages"))
        self.assertEqual(connection.kwargs["headers"]["x-api-key"], PROVIDER_KEY)
        self.assertNotIn(SESSION_TOKEN, repr(connection.kwargs))
        self.assertEqual(result.status, 307)

    def test_deadline_disconnects_response_socket_after_connection_detaches(self):
        held_socket = Mock()
        response = FakeResponse()
        connection = Mock(sock=held_socket)

        def detach():
            connection.sock = None  # HTTPConnection does this for will_close responses.
            return response

        connection.getresponse.side_effect = detach
        callbacks = []

        def timer(_, callback):
            callbacks.append(callback)
            return Mock()

        with patch("runner.model_relay.http.client.HTTPSConnection", return_value=connection), \
             patch("runner.model_relay.threading.Timer", side_effect=timer):
            result = FixedUpstream(PROVIDER_KEY)(b"{}", 1)
            self.assertIsNone(connection.sock)
            callbacks[0]()
            held_socket.shutdown.assert_called_once()
            held_socket.close.assert_called_once()
            result.close()

    def test_server_limits_threads_before_dispatch(self):
        relay = self.relay(limits=Limits(max_concurrency=1))
        server = RelayServer.__new__(RelayServer)
        server.relay = relay
        server.slots = threading.BoundedSemaphore(1)
        server.shutdown_request = Mock()
        with patch("runner.model_relay.ThreadingHTTPServer.process_request") as dispatch:
            server.process_request("first", ("127.0.0.1", 1))
            server.process_request("second", ("127.0.0.1", 2))
        dispatch.assert_called_once()
        server.shutdown_request.assert_called_once_with("second")
        self.assertEqual(relay.ledger.status()["rejected_requests"], 1)

    def test_terminal_is_withheld_until_eof(self):
        tracker = StreamTracker(MODEL, 10)
        for raw in stream().split(b"\n\n")[:-1]:
            output = tracker.consume(raw + b"\n\n")
        self.assertIsNone(output)
        tracker.complete()
        self.assertEqual(tracker.stop_frame, frame("message_stop"))
        with self.assertRaises(ProtocolError):
            tracker.consume(frame("message_delta", delta={"stop_reason": "end_turn"}, usage={"output_tokens": 3}))


if __name__ == "__main__":
    unittest.main()
