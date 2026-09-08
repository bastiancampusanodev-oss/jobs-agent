import os

from agentes.jobs.application_runner import (
    _is_professional_profile_field,
    _professional_profile_url,
    _deterministic_custom_answer,
)

from agentes.jobs.schemas import JobDecision


URL = (
    "https://www.linkedin.com/in/"
    "bastian-undefined-46171042a/"
)


def decision():
    return JobDecision.model_validate(
        {
            "decision": "APPLY",
            "match_score": 80,
            "job": {
                "url": "https://example.com/job"
            },
            "cv_id": "09_ES",
            "salary_usd_monthly": 2200,
            "salary_reason": "test",
            "why": "test",
            "hard_gaps": [],
            "unsupported_claims": [],
            "form_answers": [],
            "interview_defensibility": "test",
        }
    )


def test_webpro_portfolio_is_professional_profile():

    assert _is_professional_profile_field(
        "webpro_portfolio webpro[portfolio]"
    )


def test_linkedin_is_professional_profile():

    assert _is_professional_profile_field(
        "LinkedIn profile URL"
    )


def test_professional_website_is_supported():

    assert _is_professional_profile_field(
        "Professional website"
    )


def test_github_is_not_replaced_by_linkedin():

    assert not _is_professional_profile_field(
        "GitHub profile URL"
    )


def test_random_url_is_not_replaced():

    assert not _is_professional_profile_field(
        "Company API endpoint URL"
    )


def test_custom_linkedin_question_uses_known_url(
    monkeypatch,
):

    monkeypatch.setenv(
        "AGENT_PROFESSIONAL_PROFILE_URL",
        URL,
    )

    field = {
        "field_key": "linkedin",
        "kind": "text",
        "label": "LinkedIn profile",
        "name": "linkedin",
        "id": "linkedin",
        "required": True,
    }

    answer = _deterministic_custom_answer(
        field,
        decision(),
        "Technology role.",
    )

    assert answer is not None
    assert answer.requires_human is False
    assert answer.text == URL
