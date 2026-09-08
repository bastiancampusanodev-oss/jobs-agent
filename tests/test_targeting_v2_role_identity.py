import asyncio
from types import SimpleNamespace

import agentes.jobs.analyzer as analyzer
from scripts.jobs_loop import promote_review_if_safe


def name(decision):
    value = getattr(
        decision,
        "decision",
        "",
    )

    if hasattr(value, "value"):
        value = value.value

    return str(value).upper().split(".")[-1]


def review(score=80, cv_id="05_ES"):
    return SimpleNamespace(
        decision="REVIEW",
        match_score=score,
        cv_id=cv_id,
        why="test",
    )


async def no_llm(**kwargs):
    return None


def test_qa_specialist_title_is_detected():
    assert analyzer._central_qa_role(
        "",
        (
            "https://www.getonbrd.com/jobs/"
            "sysadmin-devops-qa/"
            "especialista-qa-senior-latam-bc-tecnologia-remote"
        ),
    )


def test_qa_lead_is_detected():
    assert analyzer._central_qa_role(
        "",
        (
            "https://www.getonbrd.com/jobs/"
            "sysadmin-devops-qa/"
            "qa-lead-e-commerce-ingles-smith-remote"
        ),
    )


def test_helpdesk_not_false_qa():
    assert analyzer._central_qa_role(
        (
            "QA Automation appears below in a "
            "recommended vacancy."
        ),
        (
            "https://www.getonbrd.com/jobs/"
            "technical-support/"
            "soporte-ti-helpdesk-tcit-santiago"
        ),
    ) is None


def test_mesa_servicio_not_false_qa():
    assert analyzer._central_qa_role(
        "Recommended jobs: QA Automation Engineer",
        (
            "https://www.getonbrd.com/jobs/"
            "technical-support/"
            "coordinador-de-activos-ti-y-mesa-de-servicio-"
            "tcit-santiago"
        ),
    ) is None


def test_practica_is_blocked_by_role_identity():
    identity = analyzer._role_identity(
        "",
        (
            "https://www.getonbrd.com/jobs/"
            "innovation-agile/"
            "practica-analista-de-negocio-ti-bice-vida-santiago"
        ),
    )

    assert analyzer._internship_role(identity)


def test_practicante_is_blocked_by_role_identity():
    identity = analyzer._role_identity(
        "",
        (
            "https://www.getonbrd.com/jobs/"
            "operations-management/"
            "practicante-area-evaluacion-y-contratos-"
            "assetplan-santiago"
        ),
    )

    assert analyzer._internship_role(identity)


def test_remote_location_allowed():
    assert analyzer._strict_location_ok(
        "",
        (
            "https://www.getonbrd.com/jobs/programming/"
            "developer-company-remote"
        ),
    )


def test_santiago_location_allowed():
    assert analyzer._strict_location_ok(
        "",
        (
            "https://www.getonbrd.com/jobs/"
            "technical-support/"
            "soporte-ti-company-santiago"
        ),
    )


def test_iquique_not_allowed_even_if_body_mentions_chile():
    assert not analyzer._strict_location_ok(
        (
            "Empresa con operaciones en Chile. "
            "Cargo presencial."
        ),
        (
            "https://www.getonbrd.com/jobs/"
            "technical-support/"
            "soporte-ti-en-terreno-company-iquique"
        ),
    )


def test_bogota_not_allowed_even_if_body_mentions_chile():
    assert not analyzer._strict_location_ok(
        "Regional company serving Chile and Colombia.",
        (
            "https://www.getonbrd.com/jobs/"
            "data-science-analytics/"
            "data-specialist-company-bogota"
        ),
    )


def test_finance_role_cannot_promote_from_incidental_tech():
    decision = promote_review_if_safe(
        review(90),
        (
            "Uses SQL, APIs, Python and software systems."
        ),
        (
            "https://www.getonbrd.com/jobs/"
            "operations-management/"
            "director-of-finance-company-remote"
        ),
    )

    assert name(decision) == "REVIEW"


def test_customer_success_manager_cannot_promote():
    decision = promote_review_if_safe(
        review(90),
        "SaaS API platform remote.",
        (
            "https://www.getonbrd.com/jobs/"
            "customer-support/"
            "customer-success-manager-company-remote"
        ),
    )

    assert name(decision) == "REVIEW"


def test_technical_support_can_promote():
    decision = promote_review_if_safe(
        review(82),
        (
            "Linux APIs monitoring production incidents."
        ),
        (
            "https://www.getonbrd.com/jobs/"
            "technical-support/"
            "technical-support-engineer-company-remote"
        ),
    )

    assert name(decision) == "APPLY"


def test_support_n2_can_promote_in_santiago():
    decision = promote_review_if_safe(
        review(80),
        (
            "Soporte técnico, APIs, Linux y monitoreo."
        ),
        (
            "https://www.getonbrd.com/jobs/"
            "technical-support/"
            "soporte-tecnico-nivel-2-company-santiago"
        ),
    )

    assert name(decision) == "APPLY"


def test_practice_never_promotes():
    decision = promote_review_if_safe(
        review(95),
        "Python APIs SQL.",
        (
            "https://www.getonbrd.com/jobs/"
            "innovation-agile/"
            "practica-analista-ti-company-santiago"
        ),
    )

    assert name(decision) == "REVIEW"


def test_qa_never_promotes():
    decision = promote_review_if_safe(
        review(95),
        "Python Selenium APIs automation.",
        (
            "https://www.getonbrd.com/jobs/"
            "sysadmin-devops-qa/"
            "ingeniero-qa-company-santiago"
        ),
    )

    assert name(decision) == "REVIEW"


def test_analyzer_skips_practice(monkeypatch):
    monkeypatch.setattr(
        analyzer,
        "_gray_llm",
        no_llm,
    )

    result = asyncio.run(
        analyzer.analyze_job(
            "Python SQL APIs Santiago.",
            (
                "https://www.getonbrd.com/jobs/"
                "innovation-agile/"
                "practica-analista-negocio-ti-company-santiago"
            ),
        )
    )

    assert name(result) == "SKIP"


def test_analyzer_skips_formal_qa(monkeypatch):
    monkeypatch.setattr(
        analyzer,
        "_gray_llm",
        no_llm,
    )

    result = asyncio.run(
        analyzer.analyze_job(
            "Python Selenium APIs automation Santiago.",
            (
                "https://www.getonbrd.com/jobs/"
                "sysadmin-devops-qa/"
                "especialista-qa-senior-company-santiago"
            ),
        )
    )

    assert name(result) == "SKIP"


def test_recommendation_noise_is_cut():
    text = (
        "Technical Support Engineer\n"
        "Linux monitoring production incidents.\n"
        + ("real vacancy " * 80)
        + "\nTrabajos similares\n"
        + ("QA Automation AI Python AWS " * 100)
    )

    cleaned = analyzer._vacancy_text(text)

    assert "Trabajos similares" not in cleaned
    assert "QA Automation" not in cleaned
