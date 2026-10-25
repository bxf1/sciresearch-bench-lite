"""A bounded, fixed-destination Anthropic streaming relay.

This module has no benchmark/GT dependencies and can run with ``python -I``.
Only the host may choose its environment, limits, event path and bind address.
Local fake-upstream tests establish protocol behavior, not network isolation.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
import hashlib
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
import secrets
import socket
import ssl
import threading
import time
import uuid


MODEL = "deepseek-flash"
UPSTREAM_URL = "https://api.deepseek.com/anthropic/v1/messages"
MAX_EVENT_BYTES = 65_536
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
REQUEST_FIELDS = frozenset({
    "model", "max_tokens", "stream", "messages", "system", "tools",
    "tool_choice", "stop_sequences", "temperature", "top_p", "top_k",
    "thinking", "output_config", "metadata", "service_tier", "container",
})


class Rejected(Exception):
    def __init__(self, status: int, code: str):
        self.status, self.code = status, code
        super().__init__(code)


class ProtocolError(Exception):
    REASONS = frozenset({
        "duplicate_event", "unknown_sse_field", "invalid_sse_json", "invalid_sse_type",
        "event_type_mismatch", "event_after_terminal", "invalid_message_start",
        "unexpected_initial_content", "invalid_initial_usage", "usage_exceeds_reservation",
        "usage_decreased", "invalid_message_delta", "terminal_without_final_usage",
        "unexpected_content_block", "unexpected_content_delta", "content_before_message",
        "unknown_event", "invalid_usage", "incomplete_stream", "compressed_upstream",
        "expected_sse", "unterminated_event", "stream_size_limit", "invalid_sse_encoding",
    })

    def __init__(self, reason):
        self.reason = reason if reason in self.REASONS else "invalid_stream"
        super().__init__(self.reason)


class StreamError(Exception):
    pass


class ClientDisconnected(Exception):
    pass


def strict_json(raw: bytes):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate_key")
            result[key] = value
        return result

    def constant(_):
        raise ValueError("nonfinite_number")

    def number(raw):
        value = float(raw)
        if not math.isfinite(value):
            raise ValueError("nonfinite_number")
        return value

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant, parse_float=number)


def encoded(value) -> bytes:
    return json.dumps(value, ensure_ascii=True, allow_nan=False,
                      separators=(",", ":")).encode("ascii")


@dataclass(frozen=True)
class Limits:
    model: str = MODEL
    request_output_limit: int = 4096
    session_output_limit: int = 32768
    session_seconds: float | None = 1500
    request_seconds: float = 120
    max_body_bytes: int = 1024 * 1024
    max_concurrency: int = 4
    max_requests: int | None = 512
    expected_system_sha256: str | None = None
    expected_tools_sha256: str | None = None
    expected_compaction_system_sha256: str | None = None
    thinking_effort: str | None = None

    def __post_init__(self):
        if self.model != MODEL:
            raise ValueError("only the frozen model is supported")
        if self.thinking_effort not in (None, "max"):
            raise ValueError("thinking effort must be absent or max")
        hashes = (self.expected_system_sha256, self.expected_tools_sha256)
        if any(value is not None for value in hashes) and not all(
            isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)
            for value in hashes
        ):
            raise ValueError("expected system/tools hashes must both be lowercase SHA256 values")
        compaction = self.expected_compaction_system_sha256
        if compaction is not None and (self.expected_system_sha256 is None
                or not isinstance(compaction, str) or len(compaction) != 64
                or any(c not in "0123456789abcdef" for c in compaction)
                or compaction == self.expected_system_sha256):
            raise ValueError("compaction requires a distinct frozen SHA256 and the research policy")
        for field in ("request_output_limit", "session_output_limit", "max_body_bytes",
                      "max_concurrency", "max_requests"):
            value = getattr(self, field)
            if field == "max_requests" and value is None:
                continue
            if type(value) is not int or value <= 0:
                raise ValueError(f"{field} must be a positive integer")
        if self.request_output_limit > self.session_output_limit:
            raise ValueError("request limit exceeds session limit")
        if self.max_body_bytes > 4 * 1024 * 1024 or self.max_concurrency > 16 or (self.max_requests is not None and self.max_requests > 4096):
            raise ValueError("relay safety bound exceeded")
        for field in ("session_seconds", "request_seconds"):
            value = getattr(self, field)
            if field == "session_seconds" and value is None:
                continue
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"{field} must be positive and finite")

    def public(self) -> dict:
        values = {k: v for k, v in self.__dict__.items() if k != "thinking_effort"}
        return {**values, "stream_required": True,
                "thinking": {"type": "enabled" if self.thinking_effort else "disabled"},
                "temperature": None if self.thinking_effort else 0.0, "top_p": 1.0,
                **({"output_config": {"effort": self.thinking_effort}} if self.thinking_effort else {}),
                "dropped_fields": ["top_k", "service_tier", "container", "temperature"] if self.thinking_effort else
                                  ["top_k", "output_config", "service_tier", "container"],
                "max_response_bytes": MAX_RESPONSE_BYTES,
                "max_event_bytes": MAX_EVENT_BYTES}


class EventLog:
    """Fresh owner-only append log. Reusing a path cannot reset a quota."""
    def __init__(self, path: Path):
        self.fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                          getattr(os, "O_NOFOLLOW", 0), 0o600)
        self.lock = threading.Lock()

    def append(self, record: dict):
        line = encoded({"schema_version": 1, "timestamp": time.time(), **record}) + b"\n"
        if len(line) > 4096:
            raise ValueError("event exceeds its fixed bound")
        with self.lock:
            view = memoryview(line)
            while view:
                count = os.write(self.fd, view)
                if not count:
                    raise OSError("event write failed")
                view = view[count:]
            os.fsync(self.fd)

    def close(self):
        os.close(self.fd)


@dataclass(frozen=True)
class Reservation:
    request_id: str
    requested: int
    effective: int
    deadline: float


class Ledger:
    def __init__(self, limits: Limits, events: EventLog, clock=time.monotonic):
        self.limits, self.events, self.clock = limits, events, clock
        self.started = clock()
        self.deadline = math.inf if limits.session_seconds is None else self.started + limits.session_seconds
        self.lock = threading.Lock()
        self.active: dict[str, Reservation] = {}
        self.request_count = self.successful = self.failed = self.rejected = 0
        self.charged = self.reserved = 0
        self.protocol_violation = self.evidence_error = False
        self.last_status = self.last_outcome = self.last_failure_reason = None
        self.failure_counts = Counter()
        events.append({"event": "session_started", "model": limits.model,
                       "upstream_url": UPSTREAM_URL, "limits": limits.public()})

    def reject(self):
        with self.lock:
            self.rejected += 1

    def reserve(self, requested: int, temperature, deadline=None, request_body=None) -> Reservation:
        with self.lock:
            now = self.clock()
            available = self.limits.session_output_limit - self.charged - self.reserved
            if self.evidence_error or self.protocol_violation:
                raise Rejected(503, "relay_failed_closed")
            if now >= self.deadline:
                raise Rejected(410, "session_expired")
            if deadline is not None and now >= deadline:
                raise Rejected(408, "request_timeout")
            if available <= 0 or (self.limits.max_requests is not None and self.request_count >= self.limits.max_requests):
                raise Rejected(429, "budget_exhausted")
            effective = min(requested, self.limits.request_output_limit, available)
            item = Reservation(uuid.uuid4().hex, requested, effective,
                               min(now + self.limits.request_seconds,
                                   self.deadline,
                                   deadline if deadline is not None else math.inf))
            hashes = {}
            if request_body is not None:
                wire = {**request_body, "max_tokens": effective}
                hashes = {"body_sha256": hashlib.sha256(encoded(wire)).hexdigest(),
                          **{field + "_sha256": hashlib.sha256(encoded(wire[field])).hexdigest()
                             if field in wire else None for field in ("system", "tools")}}
            mismatches = [field for field in ("system", "tools")
                          if getattr(self.limits, "expected_" + field + "_sha256") is not None
                          and hashes.get(field + "_sha256") != getattr(self.limits, "expected_" + field + "_sha256")]
            compaction = (self.limits.expected_compaction_system_sha256 is not None
                          and hashes.get("system_sha256") == self.limits.expected_compaction_system_sha256
                          and request_body is not None and "tools" not in request_body)
            if mismatches and not compaction:
                self.protocol_violation = True
                self.last_outcome = self.last_failure_reason = "request_policy_mismatch"
                self.failure_counts["request_policy_mismatch"] += 1
                try:
                    self.events.append({"event": "request_policy_rejected", "reason": "request_policy_mismatch",
                                        "fields": mismatches,
                                        **{field + "_sha256": hashes.get(field + "_sha256") for field in ("system", "tools")}})
                except Exception:
                    self.evidence_error = True
                raise Rejected(503, "request_policy_mismatch")
            # Evidence precedes upstream dispatch; a failed append closes admission.
            try:
                self.events.append({"event": "request_accepted", "request_id": item.request_id,
                                    "requested_max_tokens": requested, "effective_max_tokens": effective,
                                    "requested_temperature": temperature,
                                    "effective_temperature": None if self.limits.thinking_effort else 0.0,
                                    **({"effective_thinking": {"type": "enabled"},
                                        "effective_output_config": {"effort": self.limits.thinking_effort}}
                                       if self.limits.thinking_effort else {}),
                                    "request_kind": "native_compaction" if compaction else "research",
                                    **hashes})
            except Exception:
                self.evidence_error = True
                raise Rejected(503, "evidence_error") from None
            self.active[item.request_id] = item
            self.request_count += 1
            self.reserved += effective
            return item

    def finish(self, item: Reservation, outcome: str, status=None, request_id_hash=None,
               output_tokens=None, input_tokens=None, violation=False,
               cache_read_input_tokens=None, cache_creation_input_tokens=None,
               failure_reason=None, usage_violation=None):
        with self.lock:
            if item.request_id not in self.active:
                raise RuntimeError("reservation already finished")
            success = outcome == "success"
            charge = output_tokens if success else item.effective
            if success and (type(charge) is not int or not 0 <= charge <= item.effective):
                raise RuntimeError("invalid success usage")
            self.active.pop(item.request_id)
            self.reserved -= item.effective
            self.charged += charge
            self.successful += int(success)
            self.failed += int(not success)
            self.protocol_violation |= violation
            self.last_status, self.last_outcome = status, outcome
            self.last_failure_reason = failure_reason
            if not success:
                self.failure_counts[outcome] += 1
            try:
                self.events.append({"event": "request_finished", "request_id": item.request_id,
                                    "upstream_request_id_sha256": request_id_hash,
                                    "upstream_status": status, "outcome": outcome,
                                    "failure_reason": failure_reason,
                                    "usage_violation": usage_violation,
                                    "requested_max_tokens": item.requested, "effective_max_tokens": item.effective,
                                    "output_tokens": output_tokens, "input_tokens": input_tokens,
                                    "output_usage_complete": success,
                                    "cache_read_input_tokens": cache_read_input_tokens,
                                    "cache_creation_input_tokens": cache_creation_input_tokens,
                                    "charged_output_tokens": charge,
                                    "refunded_output_tokens": item.effective - charge,
                                    "protocol_violation": violation})
            except Exception:
                self.evidence_error = True
                self.last_outcome = "evidence_error"

    def status(self) -> dict:
        with self.lock:
            remaining = self.limits.session_output_limit - self.charged - self.reserved
            expired = self.clock() >= self.deadline
            exhausted = remaining <= 0 or (self.limits.max_requests is not None and self.request_count >= self.limits.max_requests)
            state = ("failed_closed" if self.protocol_violation or self.evidence_error else
                     "expired" if expired else "budget_exhausted" if exhausted else "ready")
            return {"schema_version": 1, "state": state, "model": self.limits.model,
                    "limits": self.limits.public(), "request_count": self.request_count,
                    "successful_requests": self.successful, "failed_requests": self.failed,
                    "rejected_requests": self.rejected, "inflight": len(self.active),
                    "reserved_output_tokens": self.reserved, "charged_output_tokens": self.charged,
                    "remaining_output_tokens": remaining,
                    "protocol_violation": self.protocol_violation, "evidence_error": self.evidence_error,
                    "last_upstream_status": self.last_status, "last_request_outcome": self.last_outcome,
                    "last_request_failure_reason": self.last_failure_reason,
                    "failure_counts": dict(self.failure_counts),
                    "budget_exhausted": exhausted, "expired": expired}


def disconnect(sock):
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    try:
        sock.close()
    except OSError:
        pass


class UpstreamResponse:
    def __init__(self, connection, response, timer):
        self.connection, self.response, self.timer = connection, response, timer
        self.status = response.status
        self.headers = response.headers

    def readline(self, size):
        return self.response.readline(size)

    def close(self):
        self.timer.cancel()
        self.response.close()
        self.connection.close()


class FixedUpstream:
    """No URL/header input from R, no redirects, no proxy environment lookup."""
    def __init__(self, provider_key: str):
        self.key = provider_key

    def __call__(self, body: bytes, timeout: float):
        connection = http.client.HTTPSConnection("api.deepseek.com", 443,
                                                 timeout=timeout, context=ssl.create_default_context())
        expired = threading.Event()
        connected_socket = []

        def abort():
            expired.set()
            # getresponse() may detach connection.sock for Connection: close;
            # retain the socket so its blocking response reader is still aborted.
            if connected_socket:
                disconnect(connected_socket[0])
            elif connection.sock is not None:
                disconnect(connection.sock)
            connection.close()

        timer = threading.Timer(timeout, abort)
        timer.daemon = True
        timer.start()
        try:
            connection.connect()
            if connection.sock is not None:
                connected_socket.append(connection.sock)
            if expired.is_set():
                raise TimeoutError("upstream deadline")
            connection.request("POST", "/anthropic/v1/messages", body=body, headers={
                "Content-Type": "application/json", "Accept": "text/event-stream",
                "Accept-Encoding": "identity", "anthropic-version": "2023-06-01",
                "x-api-key": self.key,
            })
            response = connection.getresponse()
            if expired.is_set():
                raise TimeoutError("upstream deadline")
            return UpstreamResponse(connection, response, timer)
        except BaseException:
            timer.cancel()
            connection.close()
            raise


class StreamTracker:
    def __init__(self, model: str, limit: int, *, allow_thinking=False):
        self.model, self.limit = model, limit
        self.allow_thinking = allow_thinking
        self.started = self.stopped = False
        self.final_usage = self.input_tokens = None
        self.observed_output_tokens = None
        self.cache_read_input_tokens = self.cache_creation_input_tokens = None
        self.stop_frame = None

    def consume(self, raw: bytes) -> bytes | None:
        name, data = None, []
        for line in raw.splitlines():
            if line.startswith(b":"):
                continue
            key, _, value = line.partition(b":")
            if value.startswith(b" "):
                value = value[1:]
            if key == b"event":
                if name is not None:
                    raise ProtocolError("duplicate_event")
                name = value.decode("ascii")
            elif key == b"data":
                data.append(value)
            elif key not in {b"id", b"retry", b""}:
                raise ProtocolError("unknown_sse_field")
        if not data:
            return b": keepalive\n\n"
        try:
            value = strict_json(b"\n".join(data))
        except (ValueError, UnicodeError, RecursionError):
            raise ProtocolError("invalid_sse_json") from None
        if not isinstance(value, dict) or not isinstance(value.get("type"), str):
            raise ProtocolError("invalid_sse_type")
        kind = value["type"]
        if name is not None and kind != name:
            raise ProtocolError("event_type_mismatch")
        if kind == "error":
            raise StreamError("upstream_stream_error")
        if self.stopped and kind != "ping":
            raise ProtocolError("event_after_terminal")
        if self.final_usage is not None and kind not in {"message_stop", "ping"}:
            raise ProtocolError("event_after_terminal")
        if kind == "message_start":
            message = value.get("message")
            if self.started or not isinstance(message, dict) or message.get("model") != self.model:
                raise ProtocolError("invalid_message_start")
            if message.get("content") not in (None, []):
                raise ProtocolError("unexpected_initial_content")
            self.started = True
            usage = message.get("usage", {})
            if not isinstance(usage, dict):
                raise ProtocolError("invalid_initial_usage")
            self.observe_usage(usage)
        elif kind == "message_delta":
            delta, usage = value.get("delta"), value.get("usage")
            if not self.started or not isinstance(delta, dict) or not isinstance(usage, dict):
                raise ProtocolError("invalid_message_delta")
            self.observe_usage(usage, require_output=True)
            count = self.observed_output_tokens
            if delta.get("stop_reason") in {"end_turn", "max_tokens", "stop_sequence", "tool_use"}:
                self.final_usage = count
        elif kind == "message_stop":
            if not self.started or self.final_usage is None:
                raise ProtocolError("terminal_without_final_usage")
            self.stopped = True
        elif kind == "content_block_start":
            block = value.get("content_block")
            allowed = {"text", "tool_use"} | ({"thinking"} if self.allow_thinking else set())
            if not self.started or not isinstance(block, dict) or block.get("type") not in allowed:
                raise ProtocolError("unexpected_content_block")
        elif kind == "content_block_delta":
            delta = value.get("delta")
            allowed = {"text_delta", "input_json_delta"} | ({"thinking_delta", "signature_delta"} if self.allow_thinking else set())
            if not self.started or not isinstance(delta, dict) or delta.get("type") not in allowed:
                raise ProtocolError("unexpected_content_delta")
        elif kind == "content_block_stop":
            if not self.started:
                raise ProtocolError("content_before_message")
        elif kind != "ping":
            raise ProtocolError("unknown_event")
        frame = b"event: " + kind.encode("ascii") + b"\ndata: " + encoded(value) + b"\n\n"
        if kind == "message_stop":
            self.stop_frame = frame
            return None  # A terminal cannot reach R before EOF verifies the complete stream.
        return frame

    @staticmethod
    def usage(value, required):
        if value is None and not required:
            return None
        if type(value) is not int or not 0 <= value <= 2**63 - 1:
            raise ProtocolError("invalid_usage")
        return value

    def observe_usage(self, usage, require_output=False):
        # All usage values are cumulative. Initial/nonterminal observations count
        # too: a smaller terminal value must never unlock a refund.
        updates = {}
        for field in ("output_tokens", "input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"):
            value = self.usage(usage.get(field), required=require_output and field == "output_tokens")
            if value is None:
                continue
            attribute = "observed_output_tokens" if field == "output_tokens" else field
            previous = getattr(self, attribute)
            if previous is not None and value < previous:
                self.usage_violation = {"field": field, "previous": previous, "observed": value}
                raise ProtocolError("usage_decreased")
            if field == "output_tokens" and value > self.limit:
                raise ProtocolError("usage_exceeds_reservation")
            updates[attribute] = value
        for attribute, value in updates.items():
            setattr(self, attribute, value)

    def complete(self):
        if not self.stopped or self.final_usage is None:
            raise ProtocolError("incomplete_stream")


class Relay:
    def __init__(self, provider_key: str, session_token: str, events: Path,
                 limits: Limits | None = None, *, upstream=None, clock=time.monotonic):
        if not provider_key or "\r" in provider_key or "\n" in provider_key:
            raise ValueError("provider key is required and must be a single line")
        if not isinstance(session_token, str) or len(session_token) < 32 or not session_token.isascii() or any(c.isspace() for c in session_token):
            raise ValueError("session token must contain at least 32 ASCII non-space characters")
        if secrets.compare_digest(provider_key, session_token):
            raise ValueError("provider key cannot be the session token")
        self.token, self.limits, self.clock = session_token, limits or Limits(), clock
        self.events = EventLog(events)
        self.ledger = Ledger(self.limits, self.events, clock)
        self.upstream = upstream if upstream is not None else FixedUpstream(provider_key)

    def authorize(self, headers):
        api_keys, authorization = headers.get_all("x-api-key", []), headers.get_all("Authorization", [])
        if len(api_keys) > 1 or len(authorization) > 1:
            raise Rejected(401, "unauthorized")
        supplied = []
        if api_keys:
            supplied.append(api_keys[0])
        if authorization:
            if not authorization[0].startswith("Bearer "):
                raise Rejected(401, "unauthorized")
            supplied.append(authorization[0][7:])
        if not supplied or any(not s.isascii() or not secrets.compare_digest(s, self.token) for s in supplied):
            raise Rejected(401, "unauthorized")

    def validate(self, raw: bytes) -> tuple[dict, object]:
        if len(raw) > self.limits.max_body_bytes:
            raise Rejected(413, "body_too_large")
        try:
            value = strict_json(raw)
        except (ValueError, UnicodeError, RecursionError):
            raise Rejected(400, "invalid_json") from None
        if not isinstance(value, dict) or value.keys() - REQUEST_FIELDS:
            raise Rejected(400, "unsupported_request_fields")
        if value.get("model") != self.limits.model:
            raise Rejected(400, "model_locked")
        if value.get("stream") is not True:
            raise Rejected(400, "stream_required")
        requested = value.get("max_tokens")
        if type(requested) is not int or not 0 < requested <= 2**31 - 1:
            raise Rejected(400, "invalid_max_tokens")
        if not isinstance(value.get("messages"), list) or not value["messages"]:
            raise Rejected(400, "messages_required")
        if "tools" in value:
            tools = value["tools"]
            if not isinstance(tools, list) or any(
                not isinstance(tool, dict) or "type" in tool or
                not isinstance(tool.get("name"), str) or
                not isinstance(tool.get("input_schema"), dict) for tool in tools
            ):
                raise Rejected(400, "only_client_tools_allowed")
        temperature = value.get("temperature")
        # Do not echo arbitrary client text into evidence.
        if temperature is not None and (type(temperature) not in {int, float} or not -2 <= temperature <= 2):
            temperature = "non_numeric"
        policy = self.limits.public()
        value["thinking"] = policy["thinking"]
        if self.limits.thinking_effort:
            value["output_config"] = policy["output_config"]
        else:
            value["temperature"] = 0.0
        value["top_p"] = 1.0
        for field in policy["dropped_fields"]:
            value.pop(field, None)
        try:
            if len(encoded(value)) > self.limits.max_body_bytes:
                raise Rejected(413, "normalized_body_too_large")
        except (ValueError, RecursionError):
            raise Rejected(400, "invalid_json") from None
        return value, temperature

    def stream(self, item: Reservation, body: bytes, begin, emit):
        response = None
        status = request_id_hash = None
        outcome, violation, failure_reason = "upstream_transport_error", False, None
        tracker = StreamTracker(self.limits.model, item.effective, allow_thinking=bool(self.limits.thinking_effort))
        begun = False
        try:
            remaining = item.deadline - self.clock()
            if remaining <= 0:
                raise TimeoutError()
            response = self.upstream(body, remaining)
            status = response.status
            request_id = response.headers.get("request-id") or response.headers.get("x-request-id")
            if request_id:
                request_id_hash = hashlib.sha256(str(request_id).encode("utf-8")).hexdigest()
            if status != 200:
                outcome = "upstream_http_error"
                raise Rejected(status if 400 <= status <= 599 else 502, "upstream_http_error")
            if response.headers.get("Content-Encoding", "identity").lower() not in {"identity", ""}:
                raise ProtocolError("compressed_upstream")
            if response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "text/event-stream":
                raise ProtocolError("expected_sse")
            begin()
            begun = True
            total, event_size, lines = 0, 0, []
            while True:
                if self.clock() >= item.deadline:
                    raise TimeoutError()
                line = response.readline(MAX_EVENT_BYTES + 1)
                if not line:
                    if lines:
                        raise ProtocolError("unterminated_event")
                    break
                total += len(line)
                event_size += len(line)
                if total > MAX_RESPONSE_BYTES or event_size > MAX_EVENT_BYTES:
                    raise ProtocolError("stream_size_limit")
                if line in {b"\n", b"\r\n"}:
                    try:
                        frame = tracker.consume(b"".join(lines))
                    except (UnicodeError, ValueError, RecursionError):
                        raise ProtocolError("invalid_sse_encoding") from None
                    if frame is not None:
                        emit(frame)
                    event_size, lines = 0, []
                else:
                    lines.append(line)
            tracker.complete()
            emit(tracker.stop_frame)
            outcome = "success"
        except Rejected:
            raise
        except ProtocolError as error:
            outcome, violation = "protocol_error", True
            failure_reason = error.reason
            if not begun:
                raise Rejected(502, "upstream_protocol_error") from None
            self._emit_error(emit, "upstream_protocol_error")
        except StreamError:
            outcome = "stream_error"
            self._emit_error(emit, "upstream_stream_error")
        except (TimeoutError, socket.timeout):
            outcome = "upstream_timeout"
            if not begun:
                raise Rejected(504, "upstream_timeout") from None
            self._emit_error(emit, "upstream_timeout")
        except ClientDisconnected:
            outcome = "client_disconnected"
        except Exception:
            outcome = "upstream_transport_error"
            if not begun:
                raise Rejected(502, "upstream_transport_error") from None
            self._emit_error(emit, "upstream_transport_error")
        finally:
            if response is not None:
                try:
                    response.close()
                except Exception:
                    pass
            self.ledger.finish(item, outcome, status, request_id_hash,
                               tracker.final_usage if outcome == "success" else None,
                               tracker.input_tokens if not violation else None, violation,
                               tracker.cache_read_input_tokens if not violation else None,
                               tracker.cache_creation_input_tokens if not violation else None,
                               failure_reason, getattr(tracker, "usage_violation", None))

    @staticmethod
    def _emit_error(emit, code):
        try:
            emit(b"event: error\ndata: " + encoded({"type": "error", "error": {
                "type": "api_error", "message": code}}) + b"\n\n")
        except (OSError, TimeoutError, ClientDisconnected):
            pass


class RelayHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def setup(self):
        self.deadline = min(self.server.relay.clock() + self.server.relay.limits.request_seconds,
                            self.server.relay.ledger.deadline)
        super().setup()

    def log_message(self, *_):
        pass  # Neither URLs, credentials, prompts nor provider errors are loggable.

    def send_error(self, code, message=None, explain=None):
        self.reply(code, {"error": "http_request_rejected"})

    @property
    def relay(self):
        return self.server.relay

    def reply(self, status, value):
        data = encoded(value)
        self.close_connection = True
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        try:
            if self.path == "/health":
                state = self.relay.ledger.status()
                self.reply(200, {key: state[key] for key in
                                ("schema_version", "state", "limits", "request_count")})
            elif self.path == "/status":
                self.relay.authorize(self.headers)
                self.reply(200, self.relay.ledger.status())
            else:
                raise Rejected(404, "path_not_allowed")
        except Rejected as error:
            self.relay.ledger.reject()
            self.reply(error.status, {"error": error.code})

    def do_POST(self):
        self.close_connection = True
        item = None
        try:
            if self.path != "/v1/messages":
                raise Rejected(404, "path_not_allowed")
            self.relay.authorize(self.headers)
            if self.headers.get_all("Transfer-Encoding"):
                raise Rejected(400, "transfer_encoding_not_allowed")
            encodings = self.headers.get_all("Content-Encoding", [])
            if len(encodings) > 1 or (encodings and encodings[0].lower() != "identity"):
                raise Rejected(415, "content_encoding_not_allowed")
            lengths = self.headers.get_all("Content-Length", [])
            if len(lengths) != 1 or not lengths[0].isascii() or not lengths[0].isdigit():
                raise Rejected(411, "content_length_required")
            length = int(lengths[0])
            if not 0 < length <= self.relay.limits.max_body_bytes:
                raise Rejected(413, "body_too_large")
            if self.headers.get_content_type() != "application/json":
                raise Rejected(415, "json_required")
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise Rejected(400, "truncated_body")
            value, temperature = self.relay.validate(raw)
            item = self.relay.ledger.reserve(value["max_tokens"], temperature, self.deadline, value)
            value["max_tokens"] = item.effective

            def begin():
                try:
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Connection", "close")
                    self.end_headers()
                except OSError:
                    raise ClientDisconnected() from None

            def emit(frame):
                try:
                    self.wfile.write(frame)
                    self.wfile.flush()
                except OSError:
                    raise ClientDisconnected() from None

            self.relay.stream(item, encoded(value), begin, emit)
        except Rejected as error:
            if item is None:
                self.relay.ledger.reject()
            self.reply(error.status, {"type": "error", "error": {
                "type": "api_error", "message": error.code}})
        except (OSError, ValueError, RecursionError):
            # A disconnected or malformed client never gains an upstream fallback.
            self.relay.ledger.reject()


class RelayServer(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False
    request_queue_size = 16

    def __init__(self, address, relay):
        self.relay = relay
        self.slots = threading.BoundedSemaphore(relay.limits.max_concurrency)
        super().__init__(address, RelayHandler)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.relay.ledger.reject()
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        # Covers parsing, slow bodies, streaming and client backpressure.
        remaining = self.relay.ledger.deadline - self.relay.clock()
        timeout = max(1, min(self.relay.limits.request_seconds, remaining))
        request.settimeout(timeout)
        timer = threading.Timer(timeout, disconnect, (request,))
        timer.daemon = True
        timer.start()
        try:
            super().process_request_thread(request, client_address)
        finally:
            timer.cancel()
            self.slots.release()

    def handle_error(self, *_):
        pass  # Default tracebacks can include caller-controlled request contents.


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--events", required=True, type=Path)
    parser.add_argument("--model", choices=[MODEL], default=MODEL)
    parser.add_argument("--session-output-limit", type=int, default=32768)
    parser.add_argument("--request-output-limit", type=int, default=4096)
    parser.add_argument("--session-seconds", type=lambda value: None if value == "none" else float(value), default=1500)
    parser.add_argument("--request-seconds", type=float, default=120)
    parser.add_argument("--max-requests", type=lambda value: None if value == "none" else int(value), default=512)
    parser.add_argument("--expected-system-sha256")
    parser.add_argument("--expected-tools-sha256")
    parser.add_argument("--expected-compaction-system-sha256")
    parser.add_argument("--thinking-effort", choices=["max"])
    args = parser.parse_args(argv)
    relay = Relay(os.environ.get("BENCH_RELAY_PROVIDER_KEY", ""),
                  os.environ.get("BENCH_RELAY_SESSION_TOKEN", ""), args.events,
                  Limits(model=args.model, session_output_limit=args.session_output_limit,
                         request_output_limit=args.request_output_limit,
                         session_seconds=args.session_seconds, request_seconds=args.request_seconds,
                         max_requests=args.max_requests,
                         thinking_effort=args.thinking_effort,
                         expected_system_sha256=args.expected_system_sha256,
                         expected_tools_sha256=args.expected_tools_sha256,
                         expected_compaction_system_sha256=args.expected_compaction_system_sha256))
    server = RelayServer((args.bind, args.port), relay)
    try:
        server.serve_forever(poll_interval=0.2)
    finally:
        server.server_close()
        relay.events.close()


if __name__ == "__main__":
    main()
