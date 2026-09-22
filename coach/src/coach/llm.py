"""Optional cloud paraphrase. Off unless COACH_LLM=true and a key is set."""

from __future__ import annotations

import json
from typing import Callable
from urllib import request

from coach.settings import Settings

_SYSTEM = (
    "Bạn là coach nói tiếng Việt cho người khiếm thị. "
    "Trả lời một câu nói được, không markdown. "
    "Chỉ dùng dữ liệu trong tin nhắn. Không bịa tên nút."
)


def maybe_llm(settings: Settings) -> Callable[[dict], str] | None:
    if not settings.llm_enabled or not settings.openai_api_key:
        return None

    def complete(payload: dict) -> str:
        body = json.dumps(
            {
                "model": settings.openai_model,
                "messages": [
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
            }
        ).encode("utf-8")
        call = request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=body,
            headers={
                "Authorization": f"Bearer {settings.openai_api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with request.urlopen(call, timeout=20) as response:
            data = json.loads(response.read().decode("utf-8"))
        return str(data["choices"][0]["message"]["content"]).strip()

    return complete
