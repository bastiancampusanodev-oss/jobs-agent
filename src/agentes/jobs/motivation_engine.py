from __future__ import annotations

import re


def _norm(text: str) -> str:
    return re.sub(
        r"\s+",
        " ",
        str(text or "").casefold(),
    ).strip()


def detect_language(text: str) -> str:
    # Backwards-compatible public entry point. PROFILE, motivation and CV
    # selection must agree on one job/application language.
    from agentes.jobs.job_language_policy import detect_job_language

    return detect_job_language(text)


def company_from_decision(decision) -> str:
    job = getattr(
        decision,
        "job",
        None,
    )

    company = (
        getattr(job, "company", "")
        if job
        else ""
    )

    return str(company or "").strip()


def build_motivation(
    job_text: str,
    decision,
    language_override: str | None = None,
) -> dict:

    language = (
        language_override
        if language_override in {
            "es",
            "en",
        }
        else detect_language(
            job_text
        )
    )

    job = getattr(
        decision,
        "job",
        None,
    )

    title = (
        getattr(job, "title", "")
        if job
        else ""
    )

    company = company_from_decision(
        decision
    )

    role = str(
        title
        or ""
    ).strip()

    company_es = (
        f" en {company}"
        if company
        else ""
    )

    company_en = (
        f" at {company}"
        if company
        else ""
    )

    blob = _norm(
        f"{title} {job_text[:9000]}"
    )

    if any(
        x in blob
        for x in (
            "backend",
            "spring",
            "java",
            "api",
            "apis",
            "integracion",
            "integración",
        )
    ):
        focus_es = (
            "desarrollo backend, integración de sistemas, APIs "
            "y construcción de soluciones mantenibles"
        )

        focus_en = (
            "backend development, systems integration, APIs "
            "and maintainable software solutions"
        )

    elif any(
        x in blob
        for x in (
            "data engineer",
            "ingeniero de datos",
            "pyspark",
            "spark",
            "etl",
        )
    ):
        focus_es = (
            "Python, SQL, procesamiento de datos y sistemas distribuidos"
        )

        focus_en = (
            "Python, SQL, data processing and distributed systems"
        )

    elif any(
        x in blob
        for x in (
            "devops",
            "sre",
            "kubernetes",
            "observability",
            "observabilidad",
        )
    ):
        focus_es = (
            "operación de sistemas, Linux, Kubernetes, monitoreo "
            "y continuidad operacional"
        )

        focus_en = (
            "systems operations, Linux, Kubernetes, monitoring "
            "and operational continuity"
        )

    elif any(
        x in blob
        for x in (
            "inteligencia artificial",
            "artificial intelligence",
            "llm",
            "rag",
            "agentic",
        )
    ):
        focus_es = (
            "Python, inteligencia artificial aplicada, RAG "
            "y automatización de workflows"
        )

        focus_en = (
            "Python, applied AI, RAG and workflow automation"
        )

    else:
        focus_es = (
            "desarrollo de software, análisis técnico y operación de sistemas"
        )

        focus_en = (
            "software development, technical analysis and systems operations"
        )

    if language == "en":

        opportunity = (
            f"the {role} opportunity"
            if role
            else "this opportunity"
        )

        text = (
            f"I am interested in {opportunity}{company_en} because "
            f"it is closely aligned with my background in {focus_en}. "
            "My experience combines software development with hands-on systems "
            "operations, which helps me consider both implementation and real-world "
            "production behavior. I am looking for a role where I can contribute "
            "technically, continue strengthening my engineering skills and take "
            "responsibility for reliable, practical solutions."
        )

    else:

        opportunity = (
            f"la oportunidad de {role}"
            if role
            else "esta oportunidad"
        )

        text = (
            f"Me interesa {opportunity}{company_es} porque se relaciona "
            f"directamente con mi experiencia en {focus_es}. "
            "Mi trayectoria combina desarrollo de software con experiencia práctica "
            "en operación de sistemas, lo que me permite considerar tanto la "
            "implementación como el comportamiento de las soluciones en producción. "
            "Busco un rol donde pueda aportar técnicamente, seguir fortaleciendo mis "
            "habilidades de ingeniería y asumir responsabilidad sobre soluciones "
            "útiles, mantenibles y confiables."
        )

    return {
        "language": language,
        "text": text,
        "chars": len(text),
    }
