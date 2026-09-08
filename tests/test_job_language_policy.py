from agentes.jobs.cv_language_policy import resolve_cv_language
from agentes.jobs.job_language_policy import detect_job_language
from agentes.jobs.motivation_engine import detect_language as motivation_language
from agentes.jobs.profile_engine import detect_language as profile_language


def test_explicit_apply_in_english_overrides_spanish_site_chrome():
    text = """
    Empleos Profesionales Trabajo remoto Empresa Equipo Experiencia
    Freelance Full-Stack AI Automation
    Requires applying in English
    We will work with you to build and ship an AI-powered workflow.
    What we're looking for
    Experience building AI-powered automation and third-party APIs.
    """
    assert detect_job_language(text) == "en"


def test_spanish_localized_apply_instruction_still_means_english():
    text = """
    Trabajo remoto Empresa Equipo Requisitos Experiencia
    Requiere postular en inglés
    Senior AI Engineer. We are looking for Python and API experience.
    """
    assert detect_job_language(text) == "en"


def test_all_artifact_detectors_share_same_language_policy():
    text = """
    Trabajo remoto Empresa Equipo Experiencia
    Requires applying in English
    We are looking for a freelance backend developer with API experience.
    """
    assert profile_language(text) == "en"
    assert motivation_language(text) == "en"
    result = resolve_cv_language("03_ES", text)
    assert result.job_language == "en"
    assert result.resolved_cv_id == "04_EN"


def test_regular_spanish_job_remains_spanish():
    text = (
        "Buscamos desarrollador backend con experiencia en Python. "
        "Requisitos, funciones y habilidades para el cargo."
    )
    assert detect_job_language(text) == "es"
