from __future__ import annotations

import asyncio
import json
import os
import urllib.request


OLLAMA_CHAT_URL = os.getenv(
    "OLLAMA_CHAT_URL",
    "http://127.0.0.1:11434/api/chat",
)

OLLAMA_MODEL = os.getenv(
    "AGENT_MODEL",
    "llama3.2:3b",
)


def _chat_sync(
    *,
    system: str,
    user: str,
    schema: dict,
    model: str | None = None,
    num_ctx: int = 2048,
    num_predict: int = 100,
    timeout: int = 120,
) -> dict:

    payload = {
        "model": model or OLLAMA_MODEL,
        "messages": [
            {
                "role": "system",
                "content": system,
            },
            {
                "role": "user",
                "content": user,
            },
        ],
        "format": schema,
        "stream": False,
        "keep_alive": os.getenv(
            "AGENT_OLLAMA_KEEP_ALIVE",
            "5m",
        ),
        "options": {
            "num_ctx": num_ctx,
            "num_predict": num_predict,
            "temperature": 0,
        },
    }

    request = urllib.request.Request(
        OLLAMA_CHAT_URL,
        data=json.dumps(
            payload
        ).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
        },
        method="POST",
    )

    with urllib.request.urlopen(
        request,
        timeout=timeout,
    ) as response:
        raw = json.loads(
            response.read().decode("utf-8")
        )

    content = (
        raw.get("message", {})
        .get("content", "")
        .strip()
    )

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "Ollama devolvió JSON estructurado "
            f"inválido: {content[:500]!r}"
        ) from exc

    return {
        "data": parsed,
        "metrics": {
            "prompt_tokens":
                raw.get("prompt_eval_count"),
            "output_tokens":
                raw.get("eval_count"),
            "prompt_seconds":
                (
                    raw.get(
                        "prompt_eval_duration",
                        0,
                    )
                    / 1e9
                ),
            "generation_seconds":
                (
                    raw.get(
                        "eval_duration",
                        0,
                    )
                    / 1e9
                ),
        },
    }


async def structured_chat(**kwargs) -> dict:
    return await asyncio.to_thread(
        _chat_sync,
        **kwargs,
    )
