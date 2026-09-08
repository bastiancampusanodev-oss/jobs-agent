from __future__ import annotations

import os
from functools import lru_cache

from openai import AsyncOpenAI
from agents import (
    OpenAIChatCompletionsModel,
    set_tracing_disabled,
)


@lru_cache(maxsize=8)
def get_agent_model(
    model_name: str | None = None,
):
    """
    Return the configured LLM backend.

    Supported:
      - ollama: local OpenAI-compatible Chat Completions
      - openai: normal Agents SDK model name

    Ollama is deliberately connected through Chat Completions
    because the Job Agent relies heavily on structured Pydantic
    outputs / JSON schema.
    """

    provider = os.getenv(
        "AGENT_LLM_PROVIDER",
        "ollama",
    ).strip().lower()

    model = (
        model_name
        or os.getenv(
            "AGENT_MODEL",
            "llama3.2:3b",
        )
    )

    if provider == "ollama":
        base_url = os.getenv(
            "AGENT_LLM_BASE_URL",
            "http://127.0.0.1:11434/v1",
        )

        # Ollama requires an API-key value in OpenAI-compatible
        # clients, but ignores its contents locally.
        client = AsyncOpenAI(
            base_url=base_url,
            api_key="ollama",
            timeout=float(
                os.getenv(
                    "AGENT_LLM_TIMEOUT",
                    "100",
                )
            ),
            max_retries=0,
        )

        # Never try to export Agents SDK traces to OpenAI.
        set_tracing_disabled(True)

        return OpenAIChatCompletionsModel(
            model=model,
            openai_client=client,
        )

    if provider == "openai":
        return model

    raise RuntimeError(
        f"AGENT_LLM_PROVIDER desconocido: {provider!r}"
    )
