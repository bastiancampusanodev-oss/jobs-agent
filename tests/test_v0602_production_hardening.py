from agentes.jobs.custom_known_facts import (
    banking_comex_custom_answer,
    data_analysis_custom_answer,
    office_stack_custom_answer,
    process_certification_custom_answer,
    work_mode_custom_answer,
)
from agentes.jobs.evidence_answerer import answer_from_evidence, evidence_is_user_facing


def _field(label: str, kind: str = "text", options=None):
    return {
        "field_key": "q",
        "kind": kind,
        "label": label,
        "required": True,
        "options": options or [],
    }


def _yes_no(label: str):
    return _field(label, "radio", [{"label": "SI"}, {"label": "NO"}])


def test_hybrid_santiago_is_deterministic_yes():
    answer = work_mode_custom_answer(
        _yes_no("¿Te encuentras disponible para trabajar de forma Hibrida en Santiago de chile?"),
        "Cargo híbrido en Santiago, Chile",
    )
    assert answer is not None
    assert answer.selected == ["SI"]


def test_onsite_santiago_is_deterministic_yes_from_job_context():
    answer = work_mode_custom_answer(
        _yes_no("¿Estas dispuesto trabajar presencial?"),
        "Analista Operacional — Santiago, Chile",
    )
    assert answer is not None
    assert answer.selected == ["SI"]


def test_data_analysis_is_grounded_positive():
    answer = data_analysis_custom_answer(_field("¿Tienes experiencia en análisis de datos?"))
    assert answer is not None
    assert "Python" in answer.text
    assert "SQL" in answer.text
    assert "PySpark" in answer.text


def test_comex_is_safe_negative_not_guardrail_text():
    answer = banking_comex_custom_answer(
        _field("¿Tienes experiencia en operaciones bancarias o Comercio Exterior (COMEX)?")
    )
    assert answer is not None
    assert "No tengo experiencia directa" in answer.text
    assert "BancoEstado" in answer.text
    assert "unless new evidence" not in answer.text


def test_excel_access_sql_is_partial_not_overclaimed():
    answer = office_stack_custom_answer(_field("¿Cuál es tu nivel de Excel, Access y SQL?"))
    assert answer is not None
    assert "SQL" in answer.text
    assert "no respalda un nivel específico de Excel" in answer.text


def test_process_certification_is_safe_negative():
    answer = process_certification_custom_answer(
        _field("¿Has realizado pruebas o certificación de procesos?")
    )
    assert answer is not None
    assert "No cuento con experiencia formal" in answer.text


def test_internal_never_claim_lines_can_never_be_extractive_answers():
    knowledge = """
truth_guardrails:
  never_claim:
    - direct Core de Comercio Exterior experience
    - certification/testing of Stand By credits unless new evidence is supplied
experience:
  facts:
    - Production monitoring
    - SQL
"""
    assert not evidence_is_user_facing("direct Core de Comercio Exterior experience")
    assert answer_from_evidence("experiencia Core de Comercio Exterior", knowledge) is None
