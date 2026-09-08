from agentes.jobs.cv_language_policy import resolve_cv_language


def test_ai_spanish_cv_switches_to_english_pair_for_english_job():
    text = (
        "We are looking for a Senior AI Engineer. "
        "Requirements include Python, LLMs and backend APIs."
    )
    result = resolve_cv_language("01_ES", text)
    assert result.job_language == "en"
    assert result.resolved_cv_id == "02_EN"
    assert result.changed is True
    assert result.pair_found is True


def test_backend_english_cv_switches_to_spanish_pair_for_spanish_job():
    text = (
        "Buscamos desarrollador backend con experiencia en Python. "
        "Requisitos y funciones del cargo."
    )
    result = resolve_cv_language("04_EN", text)
    assert result.job_language == "es"
    assert result.resolved_cv_id == "03_ES"
    assert result.changed is True


def test_correct_language_is_preserved():
    text = "We are looking for a backend developer with API experience."
    result = resolve_cv_language("04_EN", text)
    assert result.resolved_cv_id == "04_EN"
    assert result.changed is False


def test_unknown_cv_is_not_silently_rewritten():
    text = "We are looking for an AI engineer."
    result = resolve_cv_language("99_X", text)
    assert result.resolved_cv_id == "99_X"
    assert result.changed is False
    assert result.pair_found is False
