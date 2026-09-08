import asyncio
from types import SimpleNamespace

from agentes.jobs.custom_semantic_gate import (
    normalize_custom_answer,
)
from scripts import jobs_loop


class FakePage:
    async def wait_for_timeout(
        self,
        milliseconds,
    ):
        # Test double: no real browser sleep required.
        return None


def answer(
    *,
    text=None,
    selected=None,
    checked=None,
    human=False,
    reason="",
):
    return SimpleNamespace(
        text=text,
        selected=selected or [],
        checked=checked,
        requires_human=human,
        reason=reason,
    )


def test_years_question_rejects_rag_prose():
    field = {
        "field_key": "years",
        "kind": "text",
        "label": (
            "¿Cuántos años de experiencia tienes "
            "automatizando pruebas web con Playwright?"
        ),
    }

    result = normalize_custom_answer(
        field,
        answer(
            text=(
                "Pydantic structured outputs RAG "
                "Playwright Brave CDP"
            )
        ),
        salary_usd=2600,
    )

    assert result["text"] == "0"
    assert result["requires_human"] is False
    assert result["gate_reason"] == "years_numeric"


def test_years_question_keeps_simple_numeric():
    field = {
        "field_key": "years",
        "kind": "text",
        "label": "How many years of experience do you have?",
    }

    result = normalize_custom_answer(
        field,
        answer(text="2 years"),
        salary_usd=2600,
    )

    assert result["text"] == "2"


def test_salary_sueldo_liquido_is_numeric():
    field = {
        "field_key": "salary",
        "kind": "text",
        "label": (
            "¿Cuál es tu expectativa de sueldo "
            "liquido para este empleo?"
        ),
    }

    result = normalize_custom_answer(
        field,
        answer(
            text=(
                "No cuento con experiencia directa "
                "documentada..."
            )
        ),
        salary_usd=2600,
    )

    assert result["text"] == "2600"
    assert result["requires_human"] is False
    assert (
        result["gate_reason"]
        == "expected_salary_numeric"
    )


def test_required_checkbox_uses_explicit_negative():
    field = {
        "field_key": "dataset",
        "kind": "checkbox",
        "required": True,
        "label": "Experiencia con datasets",
        "options": [
            {
                "label": (
                    "He construido datasets de prueba"
                ),
                "value": "1",
            },
            {
                "label": "Ninguna de las anteriores",
                "value": "0",
            },
        ],
    }

    result = normalize_custom_answer(
        field,
        answer(
            human=True,
            reason="sin evidencia",
        ),
        salary_usd=2600,
    )

    assert result["selected"] == [
        "Ninguna de las anteriores"
    ]
    assert result["requires_human"] is False


def test_required_checkbox_without_negative_stays_human():
    field = {
        "field_key": "dataset",
        "kind": "checkbox",
        "required": True,
        "label": "Experiencia con datasets",
        "options": [
            {
                "label": (
                    "He construido datasets de prueba"
                ),
                "value": "1",
            },
        ],
    }

    result = normalize_custom_answer(
        field,
        answer(
            human=True,
            reason="sin evidencia",
        ),
        salary_usd=2600,
    )

    assert result["requires_human"] is True


def test_validation_budget_is_five(monkeypatch):
    monkeypatch.setenv(
        "JOB_MAX_VALIDATION_REPAIRS",
        "5",
    )

    decision = SimpleNamespace(
        form_constraints={
            "repair_step": "custom",
        }
    )

    for _ in range(4):
        result = jobs_loop.validation_reject_result(
            decision,
            "CUSTOM",
        )
        assert result == "REQUEUE_FORM_INVALID"

    result = jobs_loop.validation_reject_result(
        decision,
        "CUSTOM",
    )

    assert result == "HUMAN_REVIEW"

    assert (
        decision.form_constraints[
            "validation_reject_count"
        ]
        == 5
    )


def test_complete_application_repairs_same_session(
    monkeypatch,
):
    stages = iter(
        [
            "REVIEW",
            "CUSTOM",
            "REVIEW",
        ]
    )

    submit_calls = {
        "count": 0,
    }

    async def detect_stage(page):
        return next(stages)

    async def final_audit(page, decision):
        return None

    async def submit_review(page, decision):
        submit_calls["count"] += 1

        if submit_calls["count"] == 1:
            decision.form_constraints = {
                "repair_step": "custom",
                "last_validation_reject_step": "custom",
                "validation_reject_count": 1,
            }
            return "REQUEUE_FORM_INVALID"

        return "SUBMITTED"

    async def enter_repair(
        page,
        repair_step="custom",
        **kwargs,
    ):
        assert repair_step == "custom"
        return "CUSTOM"

    async def extract(page):
        return []

    async def answers(fields, job_text, decision):
        return SimpleNamespace(
            answers=[]
        )

    async def fill(page, fields, answers):
        return []

    async def next_step(page):
        return None

    monkeypatch.setattr(
        jobs_loop,
        "detect_stage",
        detect_stage,
    )

    monkeypatch.setattr(
        jobs_loop,
        "final_audit",
        final_audit,
    )

    monkeypatch.setattr(
        jobs_loop,
        "submit_review",
        submit_review,
    )

    monkeypatch.setattr(
        jobs_loop,
        "enter_form_repair_mode",
        enter_repair,
    )

    monkeypatch.setattr(
        jobs_loop,
        "extract_custom_fields",
        extract,
    )

    monkeypatch.setattr(
        jobs_loop,
        "answer_custom_fields",
        answers,
    )

    monkeypatch.setattr(
        jobs_loop,
        "fill_custom_fields",
        fill,
    )

    monkeypatch.setattr(
        jobs_loop,
        "safe_click_next",
        next_step,
    )

    decision = SimpleNamespace(
        form_constraints={}
    )

    result = asyncio.run(
        jobs_loop.complete_application(
            FakePage(),
            "job",
            decision,
            submit=True,
            repair_mode=False,
        )
    )

    assert result == "SUBMITTED"
    assert submit_calls["count"] == 2
