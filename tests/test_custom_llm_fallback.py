from agentes.jobs.custom_llm_fallback import (
    GroundedFallbackAnswer,
    field_blocked_from_llm,
    validate_fallback_answer,
)


def _text(label: str, key: str = "q"):
    return {
        "field_key": key,
        "kind": "text",
        "label": label,
        "required": True,
        "options": [],
    }


def test_ambiguous_si_stays_human():
    blocked, _ = field_blocked_from_llm(_text("SI"))
    assert blocked is True


def test_unresolved_salary_stays_human():
    blocked, _ = field_blocked_from_llm(
        _text("¿Cuál es tu expectativa salarial líquida mensual en CLP?")
    )
    assert blocked is True


def test_grounded_text_requires_verbatim_quote():
    field = _text("Cuéntanos tu experiencia con Python")
    grounding = "skills:\n  - Python\n  - REST APIs"
    answer = GroundedFallbackAnswer(
        field_key="q",
        action="answer",
        basis="grounded",
        text="He trabajado con Python en desarrollo y automatización.",
        evidence_quotes=["Python"],
    )
    assert validate_fallback_answer(field, answer, grounding) is not None


def test_fake_evidence_quote_is_rejected():
    field = _text("Cuéntanos tu experiencia con AWS")
    grounding = "skills:\n  - Python\n  - Linux"
    answer = GroundedFallbackAnswer(
        field_key="q",
        action="answer",
        basis="grounded",
        text="Tengo cinco años administrando AWS.",
        evidence_quotes=["AWS administration"],
    )
    assert validate_fallback_answer(field, answer, grounding) is None


def test_conservative_no_is_allowed_for_experience_question():
    field = _text("¿Qué experiencia tienes con AWS?")
    answer = GroundedFallbackAnswer(
        field_key="q",
        action="answer",
        basis="conservative_no",
        text=(
            "No cuento con experiencia directa respaldada en mi perfil "
            "actual con AWS."
        ),
    )
    assert validate_fallback_answer(field, answer, "Python Linux") is not None


def test_nontechnical_conservative_no_is_rejected():
    field = _text("¿Qué te motiva a postular?")
    answer = GroundedFallbackAnswer(
        field_key="q",
        action="answer",
        basis="conservative_no",
        text="No cuento con experiencia directa respaldada en mi perfil actual.",
    )
    assert validate_fallback_answer(field, answer, "Python") is None


def test_select_must_match_visible_option_exactly_after_normalization():
    field = {
        "field_key": "contract",
        "kind": "select",
        "label": "¿Puedes trabajar con contrato a plazo fijo por 4 meses?",
        "required": True,
        "options": [
            {"label": "Sí", "value": "yes"},
            {"label": "No", "value": "no"},
        ],
    }
    grounding = "fixed_term_contract: true"
    answer = GroundedFallbackAnswer(
        field_key="contract",
        action="answer",
        basis="grounded",
        selected=["si"],
        evidence_quotes=["fixed_term_contract: true"],
    )
    validated = validate_fallback_answer(field, answer, grounding)
    assert validated is not None
    assert validated.selected == ["Sí"]


def test_recover_group_question_strips_option_labels():
    from agentes.jobs.custom_llm_fallback import recover_group_question

    recovered = recover_group_question(
        ["SI", "NO"],
        ["SI", "¿Aceptas trabajar con contrato por 4 meses?\nSI\nNO"],
    )
    assert recovered == "¿Aceptas trabajar con contrato por 4 meses?"
