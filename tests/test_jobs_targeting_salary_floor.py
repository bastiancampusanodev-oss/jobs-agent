import asyncio
from types import SimpleNamespace

from agentes.jobs.analyzer import (
    _best_family,
    analyze_job,
)
from agentes.jobs.salary_engine import (
    quote_salary,
)


def decision_name(decision):
    value = getattr(
        decision,
        "decision",
        "",
    )

    if hasattr(value, "value"):
        value = value.value

    return str(value).upper().split(".")[-1]


def dummy_decision():
    return SimpleNamespace(
        job=SimpleNamespace(
            title="Software Engineer",
            seniority="mid",
            location="Remote",
            modality="remote",
            contract="full time",
        ),
        why="",
    )


def test_published_usd_range_uses_floor():
    quote = quote_salary(
        dummy_decision(),
        (
            "Salary range: "
            "USD 1000 - USD 1500 per month"
        ),
    )

    assert quote.source == "published_range"
    assert quote.amount_usd_monthly == 1000
    assert quote.published_min_usd_monthly == 1000
    assert quote.published_max_usd_monthly == 1500
    assert quote.negotiable is False


def test_published_annual_usd_range_uses_monthly_floor():
    quote = quote_salary(
        dummy_decision(),
        (
            "Compensation: "
            "USD 60000 - USD 90000 annually"
        ),
    )

    assert quote.source == "published_range"
    assert quote.amount_usd_monthly == 5000


def test_fixed_salary_is_preserved():
    quote = quote_salary(
        dummy_decision(),
        "Salary: USD 2000 monthly",
    )

    assert quote.source == "published_fixed"
    assert quote.amount_usd_monthly == 2000


def test_zero_signal_family_does_not_fall_into_ai():
    family, score = _best_family(
        "customer success relationship management"
    )

    assert family == "software"
    assert score == 0


def test_formal_qa_role_is_skipped():
    decision = asyncio.run(
        analyze_job(
            (
                "QA Automation Engineer\\n"
                "Buscamos QA Automation para diseñar "
                "y mantener pruebas automatizadas. "
                "Python Selenium API testing. "
                "Santiago Chile."
            ),
            (
                "https://www.getonbrd.com/jobs/"
                "sysadmin-devops-qa/"
                "qa-automation-engineer-acme-santiago"
            ),
        )
    )

    assert decision_name(decision) == "SKIP"
    assert decision.match_score == 0


def test_devops_inside_mixed_category_is_not_qa_skipped():
    decision = asyncio.run(
        analyze_job(
            (
                "DevOps Engineer\\n"
                "Linux Docker Kubernetes AWS Terraform "
                "monitoring and production systems. "
                "Santiago Chile."
            ),
            (
                "https://www.getonbrd.com/jobs/"
                "sysadmin-devops-qa/"
                "devops-engineer-acme-santiago"
            ),
        )
    )

    assert decision_name(decision) != "SKIP"


def test_technical_support_is_targetable():
    decision = asyncio.run(
        analyze_job(
            (
                "Technical Support Engineer\\n"
                "Application support, Linux, APIs, "
                "monitoring and production incidents. "
                "Remote LATAM."
            ),
            (
                "https://www.getonbrd.com/jobs/"
                "technical-support/"
                "technical-support-engineer-acme-remote"
            ),
        )
    )

    assert decision_name(decision) != "SKIP"
