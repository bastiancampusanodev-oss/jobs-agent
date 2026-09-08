from __future__ import annotations

import os
import re
from dataclasses import dataclass, field as dc_field
from pathlib import Path
from typing import Optional

import yaml

from agentes.jobs.motivation_engine import build_motivation


ROOT = Path(__file__).resolve().parents[3]


@dataclass
class KnownCustomAnswer:
    text: Optional[str] = None
    selected: list[str] = dc_field(default_factory=list)
    checked: Optional[bool] = None


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


def _options(field: dict) -> list[str]:
    out: list[str] = []
    for option in field.get("options") or []:
        if isinstance(option, dict):
            visible = str(option.get("label") or option.get("value") or "").strip()
        else:
            visible = str(option or "").strip()
        if visible:
            out.append(visible)
    return out


def _positive_option(field: dict) -> str | None:
    for visible in _options(field):
        norm = _norm(visible)
        if (
            norm in {"si", "sí", "yes", "true"}
            or norm.startswith("si ")
            or norm.startswith("sí ")
            or norm.startswith("yes ")
        ):
            return visible
    return None


def _negative_option(field: dict) -> str | None:
    for visible in _options(field):
        norm = _norm(visible)
        if (
            norm in {"no", "false"}
            or norm.startswith("no ")
        ):
            return visible
    return None


def _choice_or_text(
    field: dict,
    *,
    yes: bool,
    text_es: str,
    text_en: str,
) -> KnownCustomAnswer | None:
    kind = str(field.get("kind") or "")
    blob = _blob(field)
    english = any(
        token in blob
        for token in (
            " are you ",
            " do you ",
            " have you ",
            "hybrid",
            "onsite",
            "on-site",
            "remote",
            "data analysis",
            "experience with",
        )
    )

    if kind == "text":
        return KnownCustomAnswer(text=text_en if english else text_es)

    option = _positive_option(field) if yes else _negative_option(field)
    if option:
        return KnownCustomAnswer(selected=[option])

    return None


def _load_rules() -> dict:
    try:
        with (ROOT / "config" / "application_rules.yaml").open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _blob(field: dict) -> str:
    return _norm(
        " ".join(
            str(field.get(key) or "")
            for key in ("field_key", "label", "name", "id")
        )
    )


def _asks_for_actual_rut(blob: str) -> bool:
    return any(
        term in blob
        for term in (
            "numero de rut",
            "número de rut",
            "ingresa tu rut",
            "indica tu rut",
            "escribe tu rut",
            "rut number",
            "enter your rut",
        )
    )


def work_authorization_answer(field: dict) -> KnownCustomAnswer | None:
    """
    v0.6.11.11 PROFILE FACTS ROUTER.

    Resuelve de forma separada:
      - existencia de RUT chileno;
      - autorización para trabajar en Chile.

    Nunca entrega ni inventa el número de RUT.
    """

    blob = _blob(field)

    # Nunca responder el número real/documento identificador.
    if _asks_for_actual_rut(blob):
        return None

    authorization_terms = (
        "autorizacion vigente para trabajar",
        "autorización vigente para trabajar",
        "autorizado para trabajar en chile",
        "autorizada para trabajar en chile",
        "autorizacion para trabajar en chile",
        "autorización para trabajar en chile",
        "permiso para trabajar en chile",
        "puedes trabajar legalmente en chile",
        "puede trabajar legalmente en chile",
        "legally authorized to work in chile",
        "authorized to work in chile",
        "work authorization in chile",
        "eligible to work in chile",
        "rut chileno y autorizacion",
        "rut chileno y autorización",
    )

    rut_presence_terms = (
        "posees rut chileno",
        "tienes rut chileno",
        "cuentas con rut chileno",
        "cuento con rut chileno",
        "chilean rut",
        "have a rut",
        "have chilean rut",
        "have a chilean rut",
    )

    asks_authorization = any(
        term in blob
        for term in authorization_terms
    )

    asks_rut_presence = any(
        term in blob
        for term in rut_presence_terms
    )

    if not (
        asks_authorization
        or asks_rut_presence
    ):
        return None

    location = (
        _load_rules()
        .get("location")
        or {}
    )

    has_rut = bool(
        location.get("has_chilean_rut")
    )

    authorized = bool(
        location.get(
            "work_authorization_chile"
        )
    )

    if asks_authorization:
        if not (
            has_rut
            and authorized
        ):
            return None
    elif asks_rut_presence:
        if not has_rut:
            return None

    kind = str(
        field.get("kind")
        or ""
    )

    english = any(
        term in blob
        for term in (
            "authorized to work",
            "work authorization",
            "eligible to work",
            "chilean rut",
            "have a rut",
        )
    )

    if kind == "text":

        if asks_authorization:
            return KnownCustomAnswer(
                text=(
                    "Yes, I have a Chilean RUT and current "
                    "authorization to work in Chile."
                    if english
                    else
                    "Sí, cuento con RUT chileno y "
                    "autorización vigente para trabajar "
                    "en Chile."
                )
            )

        return KnownCustomAnswer(
            text=(
                "Yes, I have a Chilean RUT."
                if english
                else
                "Sí, cuento con RUT chileno."
            )
        )

    if kind in {
        "select",
        "radio",
    }:
        positive = _positive_option(
            field
        )

        if positive:
            return KnownCustomAnswer(
                selected=[positive]
            )

    if kind == "checkbox":
        return KnownCustomAnswer(
            checked=True
        )

    return None


def _clp_policy() -> tuple[float, int]:
    salary = (_load_rules().get("salary") or {})
    try:
        rate = float(os.getenv("AGENT_USD_CLP_APPROX_RATE", salary.get("usd_to_clp_approx_rate", 950)))
    except Exception:
        rate = 950.0
    try:
        rounding = int(os.getenv("AGENT_CLP_ROUND_TO", salary.get("clp_round_to", 50000)))
    except Exception:
        rounding = 50000
    return (rate if rate > 0 else 950.0, rounding if rounding > 0 else 50000)


def approximate_liquid_clp(usd_monthly: int | float) -> int:
    rate, step = _clp_policy()
    raw = float(usd_monthly) * rate
    return int((raw + step / 2) // step * step)


def _format_clp(value: int) -> str:
    return f"{int(value):,}".replace(",", ".")


def liquid_clp_salary_answer(field: dict, usd_monthly: int | float) -> KnownCustomAnswer | None:
    blob = _blob(field)
    clp_terms = ("clp", "peso chileno", "pesos chilenos")
    liquid_terms = ("liquida", "líquida", "liquido", "líquido", "net salary", "net monthly", "take home")
    if not (
        any(term in blob for term in clp_terms)
        and any(term in blob for term in liquid_terms)
    ):
        return None

    if str(field.get("kind") or "") != "text":
        return None

    clp = approximate_liquid_clp(usd_monthly)
    tag = str(field.get("tag") or "").casefold()
    if tag in {"textarea", "trix-editor"}:
        return KnownCustomAnswer(
            text=(
                f"Aproximadamente ${_format_clp(clp)} CLP líquidos mensuales, "
                "conversable según responsabilidades y beneficios."
            )
        )
    return KnownCustomAnswer(text=str(clp))


def motivation_custom_answer(field: dict, job_text: str, decision) -> KnownCustomAnswer | None:
    """v0.6.11.11 — grounded motivation phrasing router."""

    label = _norm(
        field.get("label")
        or ""
    )

    terms = (
        "que te motiva",
        "qué te motiva",
        "motivacion para postular",
        "motivación para postular",

        "por que quieres trabajar",
        "por qué quieres trabajar",

        "por que te interesa trabajar",
        "por qué te interesa trabajar",

        "por que te interesa este cargo",
        "por qué te interesa este cargo",

        "por que te interesa esta posicion",
        "por qué te interesa esta posición",

        "por que te interesa la empresa",
        "por qué te interesa la empresa",

        "why do you want to work",
        "why are you interested",
        "why are you interested in this role",
        "why are you interested in this position",
        "what motivates you to apply",
        "motivation for applying",
    )

    if (
        str(
            field.get("kind")
            or ""
        ) != "text"
        or not any(
            term in label
            for term in terms
        )
    ):
        return None

    built = build_motivation(
        job_text,
        decision,
    )

    text = str(
        built.get("text")
        or ""
    ).strip()

    return (
        KnownCustomAnswer(
            text=text
        )
        if text
        else None
    )


def work_mode_custom_answer(field: dict, job_text: str) -> KnownCustomAnswer | None:
    """Resolve recurring work-mode questions from application_rules.yaml.

    Hybrid/on-site willingness is only auto-affirmed when the job context is
    Santiago/Chile, matching the user's standing application policy. Remote is
    globally allowed. International relocation remains explicitly false.
    """
    blob = _blob(field)
    context = _norm(job_text[:5000])
    work = (_load_rules().get("work") or {})

    location_is_santiago = (
        "santiago" in blob
        or "santiago" in context
    )

    # v0.6.11.5:
    # Questions such as "¿puedes asistir a nuestras oficinas
    # 3 días por semana?" describe an on-site/hybrid work mode
    # even when they never use the word "híbrido".
    office_attendance = (
        any(
            term in blob
            for term in (
                "oficina",
                "oficinas",
                "office",
                "offices",
            )
        )
        and any(
            term in blob
            for term in (
                "asistir",
                "asistencia",
                "dias por semana",
                "días por semana",
                "veces por semana",
                "attend",
                "days per week",
                "times per week",
            )
        )
    )

    if office_attendance:

        if (
            location_is_santiago
            and (
                bool(
                    work.get(
                        "hybrid_santiago"
                    )
                )
                or bool(
                    work.get(
                        "onsite_santiago"
                    )
                )
            )
        ):
            return _choice_or_text(
                field,
                yes=True,
                text_es=(
                    "Sí, estoy disponible para asistir "
                    "a oficinas en Santiago según la "
                    "modalidad presencial/híbrida requerida."
                ),
                text_en=(
                    "Yes, I am available to attend the "
                    "Santiago office according to the "
                    "required on-site/hybrid schedule."
                ),
            )

        return None

    if any(
        term in blob
        for term in (
            "hibrid",
            "híbrido",
            "híbrida",
            "híbridos",
            "híbridas",
            "hybrid",
            "3x2",
        )
    ):
        if bool(work.get("hybrid_santiago")) and location_is_santiago:
            return _choice_or_text(
                field,
                yes=True,
                text_es="Sí, estoy disponible para trabajar de forma híbrida en Santiago.",
                text_en="Yes, I am available to work in a hybrid setup in Santiago.",
            )
        return None

    if any(term in blob for term in ("presencial", "onsite", "on-site", "on site")):
        if bool(work.get("onsite_santiago")) and location_is_santiago:
            return _choice_or_text(
                field,
                yes=True,
                text_es="Sí, estoy disponible para trabajar presencialmente en Santiago.",
                text_en="Yes, I am available to work on-site in Santiago.",
            )
        return None

    if any(term in blob for term in ("remoto", "remote")):
        if bool(work.get("remote")):
            return _choice_or_text(
                field,
                yes=True,
                text_es="Sí, estoy disponible para trabajar de forma remota.",
                text_en="Yes, I am available to work remotely.",
            )

    relocation_terms = (
        "reubicacion internacional",
        "reubicación internacional",
        "relocation abroad",
        "international relocation",
        "relocate internationally",
        "relocate to another country",
    )
    if any(term in blob for term in relocation_terms):
        if work.get("international_relocation") is False:
            return _choice_or_text(
                field,
                yes=False,
                text_es="No estoy buscando reubicación internacional en este momento.",
                text_en="I am not seeking international relocation at this time.",
            )

    return None


def data_analysis_custom_answer(field: dict) -> KnownCustomAnswer | None:
    blob = _blob(field)
    asks_data_analysis = any(
        term in blob
        for term in (
            "experiencia en analisis de datos",
            "experiencia en análisis de datos",
            "experiencia con analisis de datos",
            "experiencia con análisis de datos",
            "data analysis experience",
            "experience in data analysis",
            "experience with data analysis",
        )
    )
    if not asks_data_analysis:
        return None

    return _choice_or_text(
        field,
        yes=True,
        text_es=(
            "Sí. Tengo experiencia relacionada con análisis de datos mediante "
            "Python, SQL, PySpark/data engineering y analytics/experimentación "
            "en proyectos técnicos."
        ),
        text_en=(
            "Yes. I have data-analysis experience through Python, SQL, PySpark/data "
            "engineering, and analytics/experimentation in technical projects."
        ),
    )


def office_stack_custom_answer(field: dict) -> KnownCustomAnswer | None:
    blob = _blob(field)
    if not ("sql" in blob and "excel" in blob and "access" in blob):
        return None
    if str(field.get("kind") or "") != "text":
        return None

    english = "level" in blob or "proficiency" in blob
    return KnownCustomAnswer(
        text=(
            "I have practical, professionally defensible experience with SQL. "
            "My current profile does not document a specific proficiency level "
            "for Excel or Microsoft Access, so I prefer not to overstate them."
            if english
            else
            "Tengo experiencia práctica y defendible con SQL. Mi perfil actual no "
            "respalda un nivel específico de Excel o Microsoft Access, por lo que "
            "prefiero no sobredeclararlos."
        )
    )


def banking_comex_custom_answer(field: dict) -> KnownCustomAnswer | None:
    blob = _blob(field)
    if not any(term in blob for term in ("comex", "comercio exterior", "core de comercio exterior")):
        return None

    return _choice_or_text(
        field,
        yes=False,
        text_es=(
            "No tengo experiencia directa en operaciones bancarias de COMEX/Core de "
            "Comercio Exterior. Sí tengo experiencia tecnológica en BancoEstado en "
            "monitoreo de producción, análisis de logs, incidentes y continuidad "
            "operacional, sin atribuirme experiencia funcional de COMEX."
        ),
        text_en=(
            "I do not have direct experience in banking COMEX/Foreign Trade Core "
            "operations. I do have technology-production experience at BancoEstado "
            "covering monitoring, log analysis, incidents and operational continuity, "
            "without claiming functional COMEX experience."
        ),
    )


def process_certification_custom_answer(field: dict) -> KnownCustomAnswer | None:
    blob = _blob(field)
    process_terms = (
        "pruebas o certificacion de procesos",
        "pruebas o certificación de procesos",
        "pruebas y certificacion de procesos",
        "pruebas y certificación de procesos",
        "testing or process certification",
        "process testing or certification",
    )
    if not any(term in blob for term in process_terms):
        return None

    return _choice_or_text(
        field,
        yes=False,
        text_es=(
            "No cuento con experiencia formal específicamente en certificación de "
            "procesos de negocio. Mi experiencia relacionada está en operación de "
            "sistemas, análisis técnico, resolución de incidentes y documentación."
        ),
        text_en=(
            "I do not have formal experience specifically in business-process "
            "certification. My related experience is in systems operations, technical "
            "analysis, incident resolution and documentation."
        ),
    )


def role_experience_custom_answer(field: dict, job_text: str) -> KnownCustomAnswer | None:
    label = _norm(field.get("label") or "")
    patterns = (
        "experiencia en el rol",
        "experiencia para el rol",
        "anos, logros",
        "años, logros",
        "mayor desafio",
        "mayor desafío",
        "experience in the role",
        "years, achievements",
        "biggest challenge",
    )
    if str(field.get("kind") or "") != "text" or not any(term in label for term in patterns):
        return None

    # v0.6.11.11b — QA ROLE SEMANTIC GUARD
    #
    # "testing" anywhere in a job description does NOT make
    # the vacancy a QA role. DevOps/backend/data roles commonly
    # mention testing as part of normal engineering practice.
    #
    # Restrict the classifier to strong QA-role markers near
    # the beginning of the posting, where title/category/context
    # normally live.
    role_context = _norm(
        job_text[:1500]
    )

    strong_qa_role_markers = (
        "qa funcional",
        "qa engineer",
        "qa analyst",
        "analista qa",
        "qa junior",
        "qa senior",
        "qa automation",
        "qa automatizador",
        "quality assurance engineer",
        "quality assurance analyst",
        "software tester",
        "manual tester",
        "automation tester",
    )

    qa_role = any(
        term in role_context
        for term in strong_qa_role_markers
    )

    # --------------------------------------------------------
    # v0.6.11.11c — DEVOPS / SRE / CLOUD ROLE NARRATIVE
    #
    # This is explicitly "related experience": it must never
    # convert systems/production experience into invented years
    # under a formal DevOps title.
    # --------------------------------------------------------

    strong_devops_role_markers = (
        "devops engineer",
        "devops",
        "site reliability engineer",
        "site reliability",
        "sre engineer",
        "cloud engineer",
        "cloud devops",
        "platform engineer",
        "infrastructure engineer",
        "observability engineer",
    )

    devops_role = any(
        marker in role_context
        for marker in strong_devops_role_markers
    )

    if devops_role:
        return KnownCustomAnswer(
            text=(
                "Mi experiencia relacionada con este rol combina "
                "aproximadamente 4 años como Administrador de Sistemas "
                "(2020–2024), desarrollo de software y trabajo en "
                "producción tecnológica en BancoEstado durante 2026. "
                "He trabajado con Linux, Docker, Kubernetes, entornos "
                "cloud, monitoreo y observabilidad con Grafana, Splunk "
                "e Instana, análisis de logs y trazabilidad, respuesta "
                "a incidentes, continuidad operacional, Python, Git y "
                "automatización. Entre los desafíos más relevantes ha "
                "estado diagnosticar problemas en entornos productivos "
                "y resolverlos manteniendo la continuidad del servicio. "
                "Presento estos antecedentes como experiencia "
                "directamente relacionada con DevOps, sin atribuirme "
                "años bajo un cargo formal que no esté documentado."
            )
        )

    if not qa_role:
        return None

    return KnownCustomAnswer(
        text=(
            "Mi experiencia relacionada combina aproximadamente 4 años como "
            "Administrador de Sistemas (2020–2024), desarrollo con Python, Java, "
            "APIs REST y SQL, y trabajo en producción tecnológica en BancoEstado "
            "durante 2026. No he ocupado un cargo formal de QA Funcional, por lo "
            "que no presento esos años como experiencia QA directa. Sí he trabajado "
            "con análisis de logs y trazabilidad, resolución de incidentes, "
            "continuidad operacional y documentación técnica. Uno de mis mayores "
            "desafíos ha sido diagnosticar problemas en entornos productivos y "
            "resolverlos manteniendo la continuidad del servicio."
        )
    )


def qa_custom_answer(field: dict, job_text: str) -> KnownCustomAnswer | None:
    """Answer recurring QA custom questions from defensible candidate facts.

    This policy is deliberately conservative: it does not upgrade related
    software/operations experience into formal QA experience, and it does not
    claim QA-specific tools that are not present in CandidateTruth.
    """
    if str(field.get("kind") or "") != "text":
        return None

    label = _norm(field.get("label") or "")
    context = _norm(job_text[:6000])
    qa_context = any(
        term in context
        for term in (
            "qa funcional",
            "qa junior",
            "quality assurance",
            "qa engineer",
            "tester",
            "testing",
            "pruebas funcionales",
            "automatizacion de pruebas",
            "automatización de pruebas",
        )
    )
    if not qa_context:
        return None

    # QA tool inventory. The question often lists many tools; mentioning one
    # product name (e.g. Azure DevOps) must not be interpreted as cloud/Azure
    # experience.
    if (
        "herramientas de qa" in label
        or "qa tools" in label
        or (
            "selenium" in label
            and any(term in label for term in ("playwright", "cypress", "postman"))
        )
    ):
        return KnownCustomAnswer(
            text=(
                "No he desempeñado un rol formal de QA y no tengo experiencia "
                "laboral respaldada en mi perfil actual con Selenium, Cypress, "
                "UiPath, Postman, Jira, Azure DevOps, Confluence, TestRail o Xray. "
                "Mi experiencia transferible y confirmada incluye Python, APIs REST, "
                "SQL/PostgreSQL, Git/GitHub, análisis de logs y trazabilidad, y "
                "trabajo técnico en entornos productivos."
            )
        )

    # Agile / Jira / Azure DevOps collaboration question.
    if (
        any(term in label for term in ("metodologias agiles", "metodologías ágiles", "scrum"))
        and any(term in label for term in ("jira", "azure devops", "product owner"))
    ):
        return KnownCustomAnswer(
            text=(
                "No tengo experiencia específica respaldada en mi perfil actual "
                "con Jira o Azure DevOps ni un rol formal de Scrum/Product Owner. "
                "Mi experiencia confirmada se centra en desarrollo y operación de "
                "sistemas, resolución de incidentes, documentación técnica y trabajo "
                "en entornos productivos; prefiero no sobredeclarar herramientas o "
                "metodologías que no pueda defender en entrevista."
            )
        )

    # Automation + test management + DB + API validation composite.
    if (
        "automat" in label
        and any(term in label for term in ("gestion de pruebas", "gestión de pruebas", "test management"))
        and any(term in label for term in ("base de datos", "bases de datos", "database"))
        and "api" in label
    ):
        return KnownCustomAnswer(
            text=(
                "Mi experiencia confirmada incluye Python para desarrollo, SQL y "
                "PostgreSQL para trabajo con datos, APIs REST para integración y "
                "Git/GitHub. No he desempeñado un rol formal de QA ni tengo "
                "experiencia respaldada con herramientas específicas de gestión de "
                "pruebas, por lo que no atribuyo ese alcance a mi perfil."
            )
        )

    # Formal QA duration. Never convert adjacent engineering/operations years
    # into QA years.
    if (
        any(term in label for term in ("cuantos anos", "cuántos años", "how many years"))
        and any(term in label for term in ("analista qa", "qa analyst", "qa manual", "qa automation"))
    ):
        return KnownCustomAnswer(
            text=(
                "0 años de experiencia formal desempeñándome como Analista QA. "
                "Cuento con experiencia relacionada en desarrollo de software, APIs "
                "REST, SQL, operación de sistemas, análisis de logs y resolución de "
                "incidentes, pero no la presento como experiencia QA directa."
            )
        )

    return None



# === v0.6.9 REQUIRED QUESTIONS POLICY ===

def _v069_norm(value: str) -> str:
    import unicodedata

    raw = unicodedata.normalize(
        "NFKD",
        str(value or "").casefold(),
    )
    raw = "".join(
        ch
        for ch in raw
        if not unicodedata.combining(ch)
    )
    return re.sub(r"\s+", " ", raw).strip()


def _v069_yes_option(field: dict) -> str | None:
    positive = {
        "si",
        "yes",
        "true",
        "acepto",
        "de acuerdo",
    }

    for option in _options(field):
        if _v069_norm(option) in positive:
            return option

    return None


def residence_country_custom_answer(
    field: dict,
) -> KnownCustomAnswer | None:
    """
    v0.6.11.11 PROFILE FACTS ROUTER.

    Resuelve tanto:
      "¿Resides en Chile?"
    como:
      "¿En qué país y ciudad resides actualmente?"

    El valor sale de config/candidate.yaml.
    """

    label = _v069_norm(
        field.get("label")
        or ""
    )

    kind = str(
        field.get("kind")
        or ""
    )

    chile_specific_terms = (
        "resides en",
        "resido en",
        "reside en",
        "do you reside",
        "are you based in",
        "currently reside",
    )

    generic_current_location_terms = (
        "en que pais y ciudad resides",
        "en que ciudad y pais resides",
        "en que pais resides actualmente",
        "en que ciudad resides actualmente",
        "donde resides actualmente",
        "donde vives actualmente",
        "pais y ciudad de residencia",
        "ciudad y pais de residencia",
        "pais de residencia",
        "ciudad de residencia",
        "residencia actual",
        "current country and city",
        "country and city of residence",
        "country of residence",
        "city of residence",
        "current country",
        "current city",
        "current location",
        "where do you currently live",
        "where are you currently based",
    )

    chile_specific = (
        "chile" in label
        and any(
            term in label
            for term in chile_specific_terms
        )
    )

    generic_location = any(
        term in label
        for term in generic_current_location_terms
    )

    if not (
        chile_specific
        or generic_location
    ):
        return None

    # Fuente factual autoritativa.
    try:
        with (
            ROOT
            / "config"
            / "candidate.yaml"
        ).open(
            "r",
            encoding="utf-8",
        ) as fh:
            candidate = (
                yaml.safe_load(fh)
                or {}
            )

        location_fact = str(
            (
                candidate.get("identity")
                or {}
            ).get(
                "location"
            )
            or ""
        ).strip()

    except Exception:
        location_fact = ""

    if not location_fact:
        return None

    location_rules = (
        _load_rules()
        .get("location")
        or {}
    )

    if not bool(
        location_rules.get(
            "legal_residency_chile"
        )
    ):
        return None

    english = any(
        token in label
        for token in (
            "country",
            "city",
            "current location",
            "where do you",
            "where are you",
            "currently based",
        )
    )

    if kind == "text":
        return KnownCustomAnswer(
            text=(
                f"I currently reside in {location_fact}."
                if english
                else
                f"Resido actualmente en {location_fact}."
            )
        )

    if kind in {
        "select",
        "radio",
    }:

        location_norm = _v069_norm(
            location_fact
        )

        parts = [
            _v069_norm(part)
            for part in location_fact.split(",")
            if part.strip()
        ]

        city_norm = (
            parts[0]
            if parts
            else ""
        )

        country_norm = (
            parts[-1]
            if parts
            else ""
        )

        # Prefer explicit place options.
        for option in _options(field):
            norm = _v069_norm(option)

            if norm in {
                location_norm,
                country_norm,
                city_norm,
            }:
                return KnownCustomAnswer(
                    selected=[option]
                )

        # "¿Resides en Chile?" → Sí.
        if chile_specific:
            positive = _v069_yes_option(
                field
            )

            if positive:
                return KnownCustomAnswer(
                    selected=[positive]
                )

    # A factual checkbox such as "Resido en Chile".
    if (
        kind == "checkbox"
        and "chile" in label
    ):
        return KnownCustomAnswer(
            checked=True
        )

    return None


def english_level_custom_answer(
    field: dict,
) -> KnownCustomAnswer | None:
    """Answer oral/written English level without overstating fluency."""

    label = _v069_norm(field.get("label") or "")
    kind = str(field.get("kind") or "")

    english_question = (
        "ingles" in label
        or "english" in label
    )

    level_question = any(
        token in label
        for token in (
            "nivel",
            "level",
            "oral",
            "escrito",
            "written",
            "speaking",
            "writing",
            "proficiency",
        )
    )

    if not (english_question and level_question):
        return None

    if kind == "text":
        spanish = "ingles" in label

        return KnownCustomAnswer(
            text=(
                "Intermedio-avanzado (upper-intermediate), "
                "con capacidad conversacional y lectura/escritura "
                "técnica y profesional."
                if spanish
                else
                "Upper-intermediate, with conversational ability "
                "and professional/technical reading and writing."
            )
        )

    if kind in {"select", "radio"}:
        options = _options(field)

        # Never upgrade upper-intermediate to "advanced" merely
        # because that is the closest higher visible option.
        preferences = (
            "upper intermediate",
            "intermedio avanzado",
            "b2",
            "intermedio",
            "intermediate",
        )

        for preference in preferences:
            for option in options:
                if preference in _v069_norm(option):
                    return KnownCustomAnswer(
                        selected=[option]
                    )

    return None



def professional_summary_custom_answer(
    field: dict,
) -> KnownCustomAnswer | None:
    """
    v0.6.11.3.

    Answer only genuine professional-background prompts.

    "Cuéntanos brevemente" alone is NOT sufficient because that
    phrase also appears in recruiting/history questions.
    """

    label = _v069_norm(
        field.get("label")
        or ""
    )

    if str(
        field.get("kind")
        or ""
    ) != "text":
        return None

    # --------------------------------------------------
    # Selection/recruiting provenance is personal event
    # history, not professional-background evidence.
    # --------------------------------------------------

    selection_history = any(
        token in label
        for token in (
            "proceso de seleccion",
            "participado previamente",
            "participaste previamente",
            "postulado previamente",
            "reclutadora",
            "reclutador",
            "linkedin",
            "como llegaste",
            "invitado por",
            "invitada por",
            "referido",
            "referencia",
            "selection process",
            "hiring process",
            "recruiter",
            "previously applied",
            "previous application",
            "linkedin",
            "how did you hear",
            "referral",
            "referred",
        )
    )

    if selection_history:
        return None

    # v0.6.11.5:
    # A technology/project/duration breakdown is NOT a
    # generic professional-summary question.
    specific_breakdown = (
        any(
            token in label
            for token in (
                "tipos de proyectos",
                "tipo de proyectos",
                "proyectos y tiempo",
                "tiempo de trabajo",
                "tiempo asociado",
                "trabajando con",
                "working with",
                "technologies mentioned",
                "tecnologias mencionadas",
                "tecnologías mencionadas",
            )
        )
        and any(
            token in label
            for token in (
                "ruby",
                "rails",
                "java",
                "python",
                "kotlin",
                "javascript",
                "typescript",
                "node",
                "angular",
                "react",
                "spring",
                "aws",
                "sql",
            )
        )
    )

    if specific_breakdown:
        return None

    spanish = any(
        token in label
        for token in (
            "experiencia profesional",
            "experiencia laboral",
            "resume tu experiencia",
            "trayectoria profesional",
            "perfil profesional",
        )
    )

    english = any(
        token in label
        for token in (
            "professional experience",
            "professional background",
            "work experience",
            "summarize your experience",
        )
    )

    if not (
        spanish
        or english
    ):
        return None

    if (
        english
        and not spanish
    ):
        return KnownCustomAnswer(
            text=(
                "I have 5+ years of professional experience across "
                "software development, systems administration, automation "
                "and production support. My hands-on background includes "
                "Python, Java, SQL, REST APIs, Git, Linux, Docker, "
                "Kubernetes, cloud environments, data engineering and "
                "applied AI/LLM workflows. I also currently teach applied "
                "AI and data-engineering topics at USACH."
            )
        )

    return KnownCustomAnswer(
        text=(
            "Cuento con más de 5 años de experiencia profesional en "
            "desarrollo de software, administración de sistemas, "
            "automatización y soporte de plataformas productivas. "
            "He trabajado con Python, Java, SQL, APIs REST, Git, Linux, "
            "Docker, Kubernetes, entornos cloud, ingeniería de datos e "
            "IA/LLM aplicada. Actualmente también realizo docencia técnica "
            "en IA y datos en USACH."
        )
    )




def technology_duration_custom_answer(
    field: dict,
) -> KnownCustomAnswer | None:
    """
    v0.6.11.3 TECHNOLOGY-DURATION GUARD.

    Never answer a technology-specific "how many years?" question
    with the candidate's general 5+ years of professional history.

    Exact role-duration engines or explicit CandidateTruth may answer
    elsewhere.  This generic helper intentionally fails closed.
    """

    if str(
        field.get("kind")
        or ""
    ) != "text":
        return None

    label = _v069_norm(
        field.get("label")
        or ""
    )

    duration_terms = (
        "cuantos anos",
        "cuanto tiempo",
        "anos de experiencia",
        "how many years",
        "years of experience",
        "how long have you",
    )

    if not any(
        term in label
        for term in duration_terms
    ):
        return None

    # v0.6.11.3:
    # No generic duration inference.
    #
    # Returning None allows the guarded CandidateTruth routing to
    # demand HUMAN_REVIEW when an exact duration is unavailable.
    return None



# === v0.6.11.2 CAREER TRUTH ENGINE ===

_CAREER_TRUTH_CACHE = None


def _career_truth() -> dict:

    global _CAREER_TRUTH_CACHE

    if _CAREER_TRUTH_CACHE is None:

        try:

            with (
                ROOT
                / "config"
                / "career_truth.yaml"
            ).open(
                "r",
                encoding="utf-8",
            ) as fh:

                data = (
                    yaml.safe_load(fh)
                    or {}
                )

        except Exception:

            data = {}

        _CAREER_TRUTH_CACHE = (
            data
            if isinstance(
                data,
                dict,
            )
            else {}
        )

    return _CAREER_TRUTH_CACHE


def financial_sector_custom_answer(
    field: dict,
) -> KnownCustomAnswer | None:
    """
    Generic financial-sector experience.

    BancoEstado technology experience may establish experience
    in a banking/financial institution, but never upgrades to
    insurance, brokerage, COMEX or specialized banking products.
    """

    if str(
        field.get("kind")
        or ""
    ) != "text":
        return None

    label = _norm(
        field.get("label")
        or ""
    )

    terms = (
        "instituciones financieras",
        "institución financiera",
        "institucion financiera",
        "sector financiero",
        "experiencia en banca",
        "experiencia bancaria",
        "financial institutions",
        "financial institution",
        "financial sector",
        "banking experience",
    )

    if not any(
        term in label
        for term in terms
    ):
        return None

    # Let the existing dedicated COMEX policy win.
    specialized = (
        "comex",
        "comercio exterior",
        "foreign trade",
        "core bancario",
        "core banking",
    )

    if any(
        term in label
        for term in specialized
    ):
        return None

    truth = (
        _career_truth()
        .get("career", {})
        .get(
            "financial_sector",
            {},
        )
    )

    if not truth.get(
        "confirmed"
    ):
        return None

    print(
        "🏦 CAREER TRUTH: "
        "BancoEstado / sector financiero"
    )

    return KnownCustomAnswer(
        text=(
            "Sí. Tengo experiencia en el sector financiero "
            "en BancoEstado, en un contexto tecnológico de "
            "producción. Mi experiencia incluye monitoreo y "
            "observabilidad, análisis de logs y trazabilidad, "
            "respuesta y resolución de incidentes, continuidad "
            "operacional y documentación técnica. "
            "No atribuyo esta experiencia a funciones "
            "específicas de compañías de seguros, corredoras "
            "de bolsa o productos bancarios especializados "
            "que no estén documentados."
        )
    )


def project_stack_custom_answer(
    field: dict,
    job_text: str = "",
) -> KnownCustomAnswer | None:
    """
    Safe narrative for confirmed Java + Spring Boot + Angular work.

    Critically:
        Angular != AngularJS 1.x
        Java/Spring/Angular != invented project/module names.
    """

    if str(
        field.get("kind")
        or ""
    ) != "text":
        return None

    label = _norm(
        field.get("label")
        or ""
    )

    narrative_terms = (
        "cuentenos sobre un proyecto",
        "cuéntenos sobre un proyecto",
        "cuentame sobre un proyecto",
        "cuéntame sobre un proyecto",
        "describe un proyecto",
        "proyecto donde",
        "proyecto en el que",
        "experiencia trabajando con",
        "tell us about a project",
        "describe a project",
        "project where",
        "experience working with",
    )

    if not any(
        term in label
        for term in narrative_terms
    ):
        return None

    java = (
        "java" in label
    )

    spring = any(
        term in label
        for term in (
            "spring",
            "spring boot",
            "springboot",
        )
    )

    angular = (
        "angular" in label
    )

    matched = sum(
        (
            bool(java),
            bool(spring),
            bool(angular),
        )
    )

    # Do not hijack arbitrary project questions.
    if matched < 2:
        return None

    truth = (
        _career_truth()
        .get("career", {})
        .get(
            "java_spring_angular",
            {},
        )
    )

    if not truth.get(
        "confirmed"
    ):
        return None

    text = str(
        truth.get(
            "safe_narrative_es"
        )
        or ""
    ).strip()

    if not text:
        return None

    # AngularJS is NOT Angular.
    if "angularjs" in label:

        text += (
            " Mi experiencia confirmada es con Angular. "
            "No atribuyo experiencia específica con "
            "AngularJS 1.x si la pregunta se refiere "
            "concretamente a ese framework."
        )

    # Answer role/modules without inventing business module names.
    if any(
        term in label
        for term in (
            "rol",
            "role",
            "modulo",
            "módulo",
            "modulos",
            "módulos",
            "module",
            "modules",
        )
    ):

        text += (
            " Mi rol ha estado centrado en desarrollo "
            "e integración de software. Los componentes "
            "que puedo describir de forma defendible son "
            "servicios y APIs del backend y componentes "
            "de interfaz del frontend; no atribuyo nombres "
            "de módulos de negocio que no estén "
            "documentados."
        )

    print(
        "🧩 CAREER TRUTH: "
        "Java + Spring Boot + Angular"
    )

    return KnownCustomAnswer(
        text=text
    )
