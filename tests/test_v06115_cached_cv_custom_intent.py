from types import SimpleNamespace

import pytest

from scripts.jobs_loop import (
    _resolve_cached_cv_policy,
)

import agentes.jobs.custom_known_facts as facts

from agentes.jobs.application_runner import (
    _deterministic_custom_answer,
)


def _decision(
    *,
    why="",
    salary=3450,
):
    return SimpleNamespace(
        why=why,
        cv_id="",
        salary_usd_monthly=salary,
        salary_reason=(
            "Ajustado por validación del rango "
            "de Get on Board."
        ),
    )


def test_cached_ops_policy_resolves_current_english_cv():

    decision = _decision(
        why=(
            "Deterministic clear technology match; "
            "family=ops, score=88."
        )
    )

    expected, family, language = (
        _resolve_cached_cv_policy(
            decision,
            (
                "This role requires applying in English. "
                "We are looking for an infrastructure engineer. "
                "Requirements include Linux and Kubernetes."
            ),
        )
    )

    assert family == "ops"
    assert language == "en"
    assert expected == "06_EN"


def test_cached_data_policy_resolves_current_spanish_cv():

    decision = _decision(
        why=(
            "Deterministic clear technology match; "
            "family=data, score=82."
        )
    )

    expected, family, language = (
        _resolve_cached_cv_policy(
            decision,
            (
                "Buscamos un ingeniero de datos. "
                "Requisitos: Python, SQL y PySpark."
            ),
        )
    )

    assert family == "data"
    assert language == "es"
    assert expected == "07_ES"


def test_cached_software_family_is_not_migrated():

    decision = _decision(
        why=(
            "Deterministic clear technology match; "
            "family=software, score=88."
        )
    )

    expected, family, language = (
        _resolve_cached_cv_policy(
            decision,
            "We are looking for a software engineer.",
        )
    )

    assert expected is None
    assert family is None
    assert language is None


def test_office_days_question_maps_to_work_mode(
    monkeypatch,
):

    monkeypatch.setattr(
        facts,
        "_load_rules",
        lambda: {
            "work": {
                "hybrid_santiago": True,
                "onsite_santiago": True,
                "remote": True,
                "international_relocation": False,
            }
        },
    )

    field = {
        "kind": "text",
        "label": (
            "¿Cuentas con disponibilidad para asistir "
            "a nuestras oficinas de Santiago "
            "3 dias por semana?"
        ),
    }

    answer = facts.work_mode_custom_answer(
        field,
        "Cargo ubicado en Santiago, Chile.",
    )

    assert answer is not None
    assert answer.text is not None
    assert "Santiago" in answer.text
    assert "oficinas" in answer.text


def test_professional_summary_rejects_specific_tech_breakdown():

    field = {
        "kind": "text",
        "label": (
            "Indica cual ha sido tu experiencia profesional "
            "trabajando con Ruby on Rails, Java o Python "
            "(indica tipos de proyectos y tiempo de trabajo "
            "asociado a las tecnologias mencionadas)"
        ),
    }

    answer = (
        facts.professional_summary_custom_answer(
            field
        )
    )

    assert answer is None


def test_join_availability_plus_salary_answers_both_parts():

    field = {
        "field_key": "join_and_salary",
        "kind": "text",
        "label": (
            "Indica tu disponibilidad para unirte "
            "a nuestro equipo y expectativas "
            "salariales actuales"
        ),
        "name": "",
        "id": "",
    }

    answer = _deterministic_custom_answer(
        field,
        _decision(
            salary=3450
        ),
        "",
    )

    assert answer is not None
    assert answer.requires_human is False
    assert "Disponibilidad inmediata" in answer.text
    assert "expectativa salarial" in answer.text
    assert "3,450" in answer.text


def test_multitech_project_duration_fails_closed():

    field = {
        "field_key": "tech_duration",
        "kind": "text",
        "label": (
            "Indica cual ha sido tu experiencia profesional "
            "trabajando con Ruby on Rails, Java o Python "
            "(indica tipos de proyectos y tiempo de trabajo "
            "asociado a las tecnologias mencionadas)"
        ),
        "name": "",
        "id": "",
    }

    answer = _deterministic_custom_answer(
        field,
        _decision(),
        "",
    )

    assert answer is not None
    assert answer.requires_human is True
    assert answer.text is None
    assert "tecnología/proyecto/duración" in answer.reason
