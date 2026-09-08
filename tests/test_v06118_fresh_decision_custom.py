from agentes.jobs.schemas import (
    JobDecision,
)

from agentes.jobs.application_runner import (
    _deterministic_custom_answer,
)


def fresh_decision(
    salary=2200,
):
    return JobDecision.model_validate(
        {
            "decision": "APPLY",
            "match_score": 73,
            "job": {
                "url": "https://example.com/job",
            },
            "cv_id": "09_ES",
            "salary_usd_monthly": salary,
            "salary_reason": "test",
            "why": "test",
            "hard_gaps": [],
            "unsupported_claims": [],
            "form_answers": [],
            "interview_defensibility": "test",
        }
    )


def test_fresh_jobdecision_accepts_form_constraints():

    decision = fresh_decision()

    decision.form_constraints = {
        "repair_step": "custom",
        "repair_step_source": "human_blocker",
        "validation_reject_count": 1,
    }

    assert (
        decision.form_constraints[
            "repair_step"
        ]
        == "custom"
    )


def test_form_constraints_survive_model_roundtrip():

    decision = fresh_decision()

    decision.form_constraints = {
        "repair_step": "custom",
        "human_review_reason": "CUSTOM_BLOCKER",
        "validation_reject_count": 1,
    }

    payload = decision.model_dump()

    restored = JobDecision.model_validate(
        payload
    )

    assert (
        restored.form_constraints
        == decision.form_constraints
    )


def test_fresh_decision_can_store_human_blocker():

    decision = fresh_decision()

    constraints = dict(
        decision.form_constraints
    )

    constraints[
        "repair_step"
    ] = "custom"

    constraints[
        "repair_step_source"
    ] = "human_blocker"

    constraints[
        "human_review_reason"
    ] = (
        "CUSTOM_BLOCKER: evidencia requerida"
    )

    decision.form_constraints = constraints

    assert (
        decision.form_constraints[
            "human_review_reason"
        ].startswith(
            "CUSTOM_BLOCKER:"
        )
    )


def test_salary_aspiration_in_dollars_is_deterministic():

    field = {
        "field_key": "salary",
        "kind": "text",
        "label": (
            "¿Cuéntanos cual es tu aspiración "
            "Salarial Mensual en Dólares?"
        ),
        "name": "",
        "id": "",
        "required": True,
    }

    answer = _deterministic_custom_answer(
        field,
        fresh_decision(
            salary=2200
        ),
        "Oferta tecnológica en Santiago.",
    )

    assert answer is not None
    assert answer.requires_human is False
    assert answer.text


def test_native_spanish_question_is_deterministic():

    field = {
        "field_key": "spanish",
        "kind": "text",
        "label": (
            "¿Cuéntanos tienes nivel avanzado de "
            "español a nivel técnico y conversacional?"
        ),
        "name": "",
        "id": "",
        "required": True,
    }

    answer = _deterministic_custom_answer(
        field,
        fresh_decision(),
        "Oferta tecnológica.",
    )

    assert answer is not None
    assert answer.requires_human is False
    assert "nativo" in answer.text.casefold()


def test_english_question_about_spanish_returns_english():

    field = {
        "field_key": "spanish",
        "kind": "text",
        "label": (
            "What is your Spanish proficiency level "
            "for technical and conversational work?"
        ),
        "name": "",
        "id": "",
        "required": True,
    }

    answer = _deterministic_custom_answer(
        field,
        fresh_decision(),
        "Technology role.",
    )

    assert answer is not None
    assert answer.requires_human is False
    assert "native spanish" in answer.text.casefold()
