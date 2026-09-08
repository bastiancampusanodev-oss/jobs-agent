import asyncio
import json

import pytest

from agentes.jobs.custom_llm_fallback import (
    GroundedFallbackAnswers,
    _fallback_prompt,
    _native_ollama_call,
    _native_ollama_url,
    answer_with_grounded_ollama,
)


def _field():
    return {
        "field_key": "motivation",
        "kind": "text",
        "label": "¿Qué te motiva a postular?",
        "required": True,
        "options": [],
    }


def test_native_url_uses_local_ollama_api(monkeypatch):
    monkeypatch.setenv("AGENT_LLM_BASE_URL", "http://127.0.0.1:11434/v1")
    assert _native_ollama_url() == "http://127.0.0.1:11434/api/chat"


def test_compact_prompt_has_hard_caps():
    prompt = _fallback_prompt(
        [_field()],
        "J" * 10000,
        "G" * 20000,
        2500,
        "03_ES",
    )
    assert "G" * 9001 not in prompt
    assert "J" * 3501 not in prompt
    assert len(prompt) < 14000


def test_custom_fallback_never_uses_cloud_provider(monkeypatch):
    monkeypatch.setenv("AGENT_LLM_PROVIDER", "openai")
    with pytest.raises(RuntimeError, match="requiere AGENT_LLM_PROVIDER=ollama"):
        asyncio.run(
            answer_with_grounded_ollama(
                [_field()],
                "job",
                "Python",
                None,
                "03_ES",
            )
        )


def test_native_call_parses_structured_output(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            content = {
                "answers": [
                    {
                        "field_key": "motivation",
                        "action": "answer",
                        "basis": "grounded",
                        "text": "Me motiva aplicar mis conocimientos de Python.",
                        "selected": [],
                        "checked": None,
                        "evidence_quotes": ["Python"],
                        "reason": "",
                    }
                ]
            }
            return json.dumps(
                {
                    "message": {"content": json.dumps(content)},
                    "prompt_eval_count": 120,
                    "eval_count": 50,
                }
            ).encode()

    def fake_urlopen(req, timeout):
        assert timeout == 12
        return FakeResponse()

    monkeypatch.setattr(
        "agentes.jobs.custom_llm_fallback.urllib_request.urlopen",
        fake_urlopen,
    )

    parsed, raw = _native_ollama_call(
        model="llama3.2:3b",
        system_prompt="system",
        user_prompt="user",
        timeout_seconds=12,
    )
    assert isinstance(parsed, GroundedFallbackAnswers)
    assert parsed.answers[0].field_key == "motivation"
    assert raw["eval_count"] == 50


def test_native_payload_requests_schema_and_single_nonstream_call(monkeypatch):
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps(
                {"message": {"content": '{"answers": []}'}}
            ).encode()

    def fake_urlopen(req, timeout):
        captured.update(json.loads(req.data.decode()))
        return FakeResponse()

    monkeypatch.setattr(
        "agentes.jobs.custom_llm_fallback.urllib_request.urlopen",
        fake_urlopen,
    )

    _native_ollama_call(
        model="llama3.2:3b",
        system_prompt="system",
        user_prompt="user",
        timeout_seconds=10,
    )
    assert captured["stream"] is False
    assert captured["model"] == "llama3.2:3b"
    assert isinstance(captured["format"], dict)
    assert captured["options"]["temperature"] == 0
    assert captured["options"]["num_predict"] == 360
