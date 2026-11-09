"""Recorded-shape fakes: real SDK clients talking to an in-memory HTTP transport."""

import json
from collections.abc import Callable
from typing import Any

import anthropic
import httpx2
import openai


class Recorder:
    """An httpx2 transport that records requests and replays a canned response."""

    def __init__(self, respond: Callable[[httpx2.Request], httpx2.Response]) -> None:
        self.requests: list[httpx2.Request] = []
        self._respond = respond

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        return self._respond(request)

    @property
    def body(self) -> dict[str, Any]:
        return json.loads(self.requests[-1].content)


def json_response(
    payload: dict[str, Any], status: int = 200
) -> Callable[[httpx2.Request], httpx2.Response]:
    return lambda _: httpx2.Response(status, json=payload)


def anthropic_client(recorder: Recorder) -> anthropic.AsyncAnthropic:
    return anthropic.AsyncAnthropic(
        api_key="test-key",
        max_retries=0,
        http_client=anthropic.DefaultAsyncHttpxClient(
            transport=httpx2.MockTransport(recorder.handler)
        ),
    )


def openai_client(recorder: Recorder) -> openai.AsyncOpenAI:
    return openai.AsyncOpenAI(
        api_key="test-key",
        max_retries=0,
        http_client=openai.DefaultAsyncHttpxClient(
            transport=httpx2.MockTransport(recorder.handler)
        ),
    )


def claude_message(
    data: dict[str, Any] | None,
    *,
    model: str = "claude-opus-5-5",
    stop_reason: str = "end_turn",
    fallback_block: bool = False,
) -> dict[str, Any]:
    """A Messages API response whose text block holds the structured output JSON."""
    content: list[dict[str, Any]] = []
    if fallback_block:
        content.append(
            {
                "type": "fallback",
                "from": {"model": model},
                "to": {"model": "claude-opus-5"},
                "trigger": {"type": "refusal", "category": None},
            }
        )
    content.append({"type": "thinking", "thinking": "", "signature": "sig"})
    if data is not None:
        content.append({"type": "text", "text": json.dumps(data)})
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": content,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": 1800, "output_tokens": 400},
    }


def openai_response(
    data: dict[str, Any] | None, *, refusal: str | None = None, status: str = "completed"
) -> dict[str, Any]:
    if refusal is not None:
        content = [{"type": "refusal", "refusal": refusal}]
    else:
        content = [{"type": "output_text", "text": json.dumps(data), "annotations": []}]
    return {
        "id": "resp_test",
        "object": "response",
        "created_at": 0,
        "status": status,
        "model": "test-model",
        "output": [
            {
                "type": "message",
                "id": "msg_1",
                "status": "completed",
                "role": "assistant",
                "content": content,
            }
        ],
        "parallel_tool_calls": False,
        "tool_choice": "auto",
        "tools": [],
        "usage": {
            "input_tokens": 100,
            "output_tokens": 50,
            "total_tokens": 150,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": 0},
        },
    }


def api_error(status: int, error_type: str) -> Callable[[httpx2.Request], httpx2.Response]:
    return lambda _: httpx2.Response(
        status, json={"type": "error", "error": {"type": error_type, "message": "x"}}
    )
