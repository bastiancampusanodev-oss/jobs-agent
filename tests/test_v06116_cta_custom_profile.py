from types import SimpleNamespace

import pytest

import agentes.jobs.analyzer as analyzer
import agentes.jobs.job_language_policy as lang_policy
import agentes.jobs.profile_engine as profile_engine

from scripts.jobs_loop import (
    classify_application_entry_failure,
)

from agentes.jobs.application_runner import (
    _extract_secret_phrase,
    _hypothetical_scope_answer,
    _liquid_salary_without_currency,
    _deterministic_custom_answer,
)


class _Body:

    def __init__(self, text):
        self._text = text

    async def inner_text(self):
        return self._text


class _Page:

    def __init__(self, text, url):
        self._text = text
        self.url = url

    def locator(self, selector):
        assert selector == "body"
        return _Body(self._text)


@pytest.mark.asyncio
async def test_explicit_closed_job_is_classified_unavailable():

    page = _Page(
        "Esta oferta ya no está disponible.",
        "https://www.getonbrd.com/jobs/example",
    )

    status, reason = (
        await classify_application_entry_failure(
            page,
            "https://www.getonbrd.com/jobs/example",
        )
    )

    assert status == "JOB_UNAVAILABLE"
    assert "JOB_UNAVAILABLE" in reason


@pytest.mark.asyncio
async def test_plain_missing_cta_is_not_human_review():

    page = _Page(
        "Oferta de empleo sin CTA visible.",
        "https://www.getonbrd.com/jobs/example",
    )

    status, reason = (
        await classify_application_entry_failure(
            page,
            "https://www.getonbrd.com/jobs/example",
        )
    )

    assert status == "APPLICATION_CTA_MISSING"
    assert "APPLICATION_CTA_MISSING" in reason


def test_secret_phrase_is_extracted_only_from_posting():

    text = """
    Requirements:
    Please read carefully.
    The secret phrase is "Blue Pineapple".
    """

    assert (
        _extract_secret_phrase(text)
        == "Blue Pineapple"
    )


def test_missing_secret_phrase_returns_none():

    assert (
        _extract_secret_phrase(
            "There is no explicit phrase here."
        )
        is None
    )


def test_hypothetical_client_scope_is_answered():

    field = {
        "kind": "text",
        "label": (
            'Client says: "We need an AI to handle '
            'inbound leads at night and book appointments." '
            "Before writing any code, how would you scope this, "
            "what would you ask the client, and how would you "
            "phase the build?"
        ),
    }

    answer = _hypothetical_scope_answer(
        field
    )

    assert answer is not None
    assert "business outcome" in answer
    assert "human fallback" in answer


def test_past_project_prompt_is_not_hypothetical():

    field = {
        "kind": "text",
        "label": (
            "Walk me through a project where you had to "
            "integrate multiple third-party APIs."
        ),
    }

    assert (
        _hypothetical_scope_answer(field)
        is None
    )


def test_liquid_salary_without_currency_fails_closed():

    field = {
        "kind": "text",
        "label": (
            "¿Cuáles son tus expectativas salariales "
            "líquidas mensuales para este rol?"
        ),
    }

    assert (
        _liquid_salary_without_currency(
            field
        )
        is True
    )


def test_liquid_salary_with_clp_is_not_blocked():

    field = {
        "kind": "text",
        "label": (
            "Indica tu renta líquida mensual en CLP"
        ),
    }

    assert (
        _liquid_salary_without_currency(
            field
        )
        is False
    )


def test_secret_question_fails_closed_when_phrase_absent():

    field = {
        "field_key": "secret",
        "kind": "text",
        "label": (
            "What is the secret phrase?"
        ),
        "name": "",
        "id": "",
    }

    decision = SimpleNamespace(
        salary_usd_monthly=2000,
        salary_reason="",
    )

    answer = _deterministic_custom_answer(
        field,
        decision,
        "No explicit secret phrase is stated here.",
    )

    assert answer is not None
    assert answer.requires_human is True


def test_profile_family_uses_analyzer_data(
    monkeypatch,
):

    monkeypatch.setattr(
        analyzer,
        "_best_family",
        lambda blob: (
            "data",
            20,
        ),
    )

    monkeypatch.setattr(
        lang_policy,
        "detect_job_language",
        lambda text: "en",
    )

    result = profile_engine.build_profile(
        "example job"
    )

    assert result["family"] == "data"
    assert result["language"] == "en"


def test_profile_ops_maps_to_devops(
    monkeypatch,
):

    monkeypatch.setattr(
        analyzer,
        "_best_family",
        lambda blob: (
            "ops",
            20,
        ),
    )

    monkeypatch.setattr(
        lang_policy,
        "detect_job_language",
        lambda text: "es",
    )

    result = profile_engine.build_profile(
        "example job"
    )

    assert result["family"] == "devops"
    assert result["language"] == "es"
