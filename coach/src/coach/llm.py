"""Optional cloud paraphrase. Off unless COACH_LLM=true and a key is set."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from urllib import request

from coach.settings import Settings

_SYSTEM = (
    "Bạn là coach nói tiếng Việt cho người khiếm thị. "
    "Trả lời một câu nói được, không markdown. "
    "Chỉ dùng dữ liệu trong tin nhắn. Không bịa tên nút."
)


class ResponsesLLM:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _request(self, payload: dict, *, stream: bool):
        body = json.dumps(
            {
                "model": self.settings.openai_model,
                "store": False,
                "stream": stream,
                "reasoning": {"effort": "none"},
                "max_output_tokens": 120,
                "instructions": _SYSTEM,
                "input": json.dumps(payload, ensure_ascii=False),
            }
        ).encode("utf-8")
        return request.Request(
            "https://api.openai.com/v1/responses",
            data=body,
            headers={
                "Authorization": f"Bearer {self.settings.openai_api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

    def __call__(self, payload: dict) -> str:
        with request.urlopen(self._request(payload, stream=False), timeout=1.2) as response:
            data = json.loads(response.read().decode("utf-8"))
        text = data.get("output_text")
        if not text:
            for item in data.get("output", []):
                for content in item.get("content", []):
                    if content.get("type") == "output_text" and content.get("text"):
                        text = content["text"]
                        break
                if text:
                    break
        return str(text or "").strip()

    def stream(self, payload: dict) -> Iterator[str]:
        """Yield complete spoken clauses from Responses SSE deltas."""

        buffered = ""
        with request.urlopen(self._request(payload, stream=True), timeout=1.2) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8").strip()
                if not line.startswith("data:"):
                    continue
                data = line.removeprefix("data:").strip()
                if data == "[DONE]":
                    break
                try:
                    event = json.loads(data)
                except json.JSONDecodeError:
                    continue
                if event.get("type") != "response.output_text.delta":
                    continue
                buffered += str(event.get("delta", ""))
                clauses, buffered = _complete_clauses(buffered)
                yield from clauses
        tail = " ".join(buffered.split())
        if tail:
            yield tail


def _complete_clauses(text: str) -> tuple[list[str], str]:
    parts = re.split(r"(?<=[.!?…])\s+", text)
    if len(parts) == 1:
        return [], text
    return [" ".join(part.split()) for part in parts[:-1] if part.strip()], parts[-1]


def maybe_llm(settings: Settings) -> ResponsesLLM | None:
    if not settings.llm_enabled or not settings.openai_api_key:
        return None
    return ResponsesLLM(settings)
