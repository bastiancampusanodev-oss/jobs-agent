import pytest

import agentes.jobs.application_runner as app_runner

from agentes.jobs.custom_known_facts import (
    professional_summary_custom_answer,
    technology_duration_custom_answer,
)


def test_selection_history_does_not_become_professional_summary():
    field = {
        "field_key": "witi_previous",
        "kind": "text",
        "label": (
            "¿Has participado previamente en procesos de selección "
            "con WiTi? Si es así, cuéntanos brevemente para qué rol "
            "y en qué fecha aproximada"
        ),
        "required": True,
        "options": [],
    }

    answer = (
        professional_summary_custom_answer(
            field
        )
    )

    assert answer is None


def test_real_professional_summary_still_works():
    field = {
        "field_key": "background",
        "kind": "text",
        "label": (
            "Cuéntanos brevemente de tu experiencia profesional"
        ),
        "required": True,
        "options": [],
    }

    answer = (
        professional_summary_custom_answer(
            field
        )
    )

    assert answer is not None
    assert "5 años" in answer.text


@pytest.mark.parametrize(
    "label",
    [
        (
            "¿Cuántos años de experiencia tienes desarrollando "
            "aplicaciones Android con Kotlin?"
        ),
        (
            "¿Cuántos años de experiencia tienes utilizando "
            "GitHub y flujos de control de versiones?"
        ),
        (
            "¿Cuánto tiempo de experiencia tienes con AWS "
            "Lambda, DynamoDB y API Gateway?"
        ),
    ],
)
def test_specific_technology_duration_fails_closed(
    label,
):
    field = {
        "field_key": "years",
        "kind": "text",
        "label": label,
        "required": True,
        "options": [],
    }

    assert (
        technology_duration_custom_answer(
            field
        )
        is None
    )


class _BodyLocator:

    async def inner_text(self):
        return ""


class _FakePage:

    def __init__(self):
        self.url = (
            "https://www.getonbrd.com/jobs/x/"
            "applications/new/edit?step=experience"
        )

    def locator(self, selector):
        assert selector == "body"
        return _BodyLocator()


@pytest.mark.asyncio
async def test_experience_query_without_profile_dom_is_not_profile(
    monkeypatch,
):
    page = _FakePage()

    async def fake_step(_page):
        return "experience"

    async def no_profile(_page):
        return False

    async def no_custom(_page):
        return []

    monkeypatch.setattr(
        app_runner,
        "resolve_gob_step",
        fake_step,
    )

    monkeypatch.setattr(
        app_runner,
        "_profile_editor_dom_present",
        no_profile,
    )

    monkeypatch.setattr(
        app_runner,
        "extract_custom_fields",
        no_custom,
    )

    stage = await app_runner.detect_stage(
        page
    )

    assert stage == "UNKNOWN"


@pytest.mark.asyncio
async def test_experience_query_with_profile_dom_is_profile(
    monkeypatch,
):
    page = _FakePage()

    async def fake_step(_page):
        return "experience"

    async def has_profile(_page):
        return True

    monkeypatch.setattr(
        app_runner,
        "resolve_gob_step",
        fake_step,
    )

    monkeypatch.setattr(
        app_runner,
        "_profile_editor_dom_present",
        has_profile,
    )

    stage = await app_runner.detect_stage(
        page
    )

    assert stage == "PROFILE"


def test_jobs_loop_has_cv_only_legacy_fallback():
    source = (
        __import__("pathlib")
        .Path("scripts/jobs_loop.py")
        .read_text()
    )

    assert (
        "LEGACY PROFILE:"
        in source
    )

    assert (
        "cv_language_repair_required"
        in source
    )

    assert (
        "and not revalidate"
        in source
    )
