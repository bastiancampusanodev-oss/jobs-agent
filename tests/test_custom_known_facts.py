from types import SimpleNamespace

from agentes.jobs.custom_known_facts import (
    approximate_liquid_clp,
    liquid_clp_salary_answer,
    motivation_custom_answer,
    role_experience_custom_answer,
    work_authorization_answer,
)


def _decision():
    return SimpleNamespace(job=SimpleNamespace(title="QA Funcional", company="Dynamic Devs"))


def test_work_authorization_rut_radio_selects_yes():
    field = {
        "field_key": "work_auth",
        "kind": "radio",
        "label": "¿Posees RUT chileno y autorización vigente para trabajar en el país?",
        "required": True,
        "options": [{"label": "Sí", "value": "yes"}, {"label": "No", "value": "no"}],
    }
    answer = work_authorization_answer(field)
    assert answer is not None
    assert answer.selected == ["Sí"]


def test_work_authorization_text_is_positive():
    field = {"field_key": "auth", "kind": "text", "label": "¿Tienes permiso para trabajar en Chile?", "options": []}
    answer = work_authorization_answer(field)
    assert answer is not None
    assert "autorización vigente" in answer.text


def test_actual_rut_number_is_not_invented():
    field = {"field_key": "rut", "kind": "text", "label": "Ingresa tu número de RUT", "options": []}
    assert work_authorization_answer(field) is None


def test_liquid_clp_approximation(monkeypatch):
    monkeypatch.setenv("AGENT_USD_CLP_APPROX_RATE", "950")
    monkeypatch.setenv("AGENT_CLP_ROUND_TO", "50000")
    assert approximate_liquid_clp(1550) == 1450000
    field = {
        "field_key": "salary",
        "kind": "text",
        "tag": "input",
        "label": "¿Cuál es tu expectativa salarial líquida mensual en pesos chilenos (CLP)?",
    }
    assert liquid_clp_salary_answer(field, 1550).text == "1450000"


def test_liquid_clp_textarea_is_explicitly_approximate(monkeypatch):
    monkeypatch.setenv("AGENT_USD_CLP_APPROX_RATE", "1000")
    monkeypatch.setenv("AGENT_CLP_ROUND_TO", "50000")
    field = {"field_key": "salary", "kind": "text", "tag": "textarea", "label": "Renta líquida mensual en CLP"}
    text = liquid_clp_salary_answer(field, 1550).text
    assert "$1.550.000 CLP líquidos" in text
    assert "conversable" in text


def test_custom_motivation_reuses_existing_engine():
    field = {"field_key": "mot", "kind": "text", "label": "¿Qué te motiva a postular a este cargo en Dynamic Devs?"}
    answer = motivation_custom_answer(field, "QA Funcional Dynamic Devs Santiago", _decision())
    assert answer is not None
    assert "Me interesa" in answer.text


def test_qa_experience_is_honest_about_no_formal_qa_title():
    field = {"field_key": "exp", "kind": "text", "label": "Cuéntanos tu experiencia en el rol: años, logros y tu mayor desafío."}
    answer = role_experience_custom_answer(field, "QA Funcional, testing, pruebas funcionales")
    assert answer is not None
    assert "4 años como Administrador de Sistemas" in answer.text
    assert "No he ocupado un cargo formal de QA Funcional" in answer.text
    assert "BancoEstado" in answer.text
