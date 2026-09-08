from __future__ import annotations

import json
import os
import re
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field

from agentes.jobs.schemas import JobDecision
from agentes.ollama_native import structured_chat


class GrayDecision(BaseModel):
    decision: Literal["APPLY", "SKIP", "REVIEW"]
    match_score: int = Field(ge=0, le=100)


GRAY_SYSTEM = """
Classify a technology job for this candidate.

Candidate:
Python, Java, Kotlin, SQL, REST APIs, Linux, Docker,
Kubernetes, observability, Grafana, Splunk, Instana,
PySpark, LangChain, RAG, LLM APIs, systems administration,
production support and technical teaching.

Location Santiago Chile.
Spanish native, English upper-intermediate.

APPLY if plausibly interview-defensible.
REVIEW if uncertain.
SKIP if central role mismatch.
Never invent experience.
""".strip()


HARD_BLOCKERS = (
    "práctica profesional",
    "practica profesional",
    "internship",
    "intern position",
    "intern role",
    "trainee program",
    "unpaid",
    "sin remuneración",
    "sin remuneracion",
    "mandatory relocation",
    "relocation required",
    "must relocate",
    "reubicación obligatoria",
    "reubicacion obligatoria",
)


FAMILIES = {
    "ai": {
        "es": "01_ES",
        "en": "02_EN",
        "signals": {
            "artificial intelligence": 5,
            "inteligencia artificial": 5,
            "generative ai": 5,
            "genai": 5,
            "machine learning": 4,
            "llm": 5,
            "large language model": 5,
            "rag": 5,
            "langchain": 5,
            "prompt engineer": 5,
            "ai engineer": 5,
            "openai": 3,
            "embeddings": 4,
            "vector search": 4,
        },
    },

    "python": {
        "es": "03_ES",
        "en": "04_EN",
        "signals": {
            "python": 5,
            "fastapi": 5,
            "django": 4,
            "flask": 4,
            "backend": 3,
            "back-end": 3,
            "rest api": 3,
            "restful": 3,
            "automation": 3,
            "automatización": 3,
            "automatizacion": 3,
        },
    },

    "data": {
        "es": "07_ES",
        "en": "08_EN",
        "signals": {
            "data engineer": 6,
            "data engineering": 5,
            "ingeniero de datos": 6,
            "pyspark": 6,
            "apache spark": 5,
            "spark": 4,
            "etl": 4,
            "data pipeline": 4,
            "pipeline de datos": 4,
            "airflow": 3,
            "databricks": 3,
            "data governance": 5,
            "gobierno de datos": 5,
            "metadata": 4,
            "metadatos": 4,
            "data quality": 4,
            "calidad de datos": 4,
        },
    },

    "ops": {
        "es": "05_ES",
        "en": "06_EN",
        "signals": {
            "systems analyst": 6,
            "system analyst": 6,
            "business systems analyst": 6,
            "analista de sistemas": 6,
            "analista funcional": 5,
            "production support": 6,
            "soporte de producción": 6,
            "soporte de produccion": 6,
            "observability": 5,
            "observabilidad": 5,
            "devops": 4,
            "sre": 4,
            "site reliability": 4,
            "grafana": 3,
            "splunk": 3,
            "instana": 3,
            "kubernetes": 3,
            "linux": 2,
            "operations": 2,
            "operaciones ti": 4,
            "technical support": 5,
            "support engineer": 5,
            "application support": 5,
            "soporte técnico": 5,
            "soporte tecnico": 5,
            "soporte ti": 5,
            "soporte nivel 2": 4,
            "soporte n2": 4,
            "mesa de ayuda": 3,
            "help desk": 3,
            "service desk": 3,
            "monitoring": 3,
            "monitoreo": 3,
            "cloud engineer": 5,
            "aws": 3,
            "gcp": 3,
            "terraform": 3,
            "prometheus": 3,
            "datadog": 3,
            "cybersecurity": 5,
            "ciberseguridad": 5,
            "security analyst": 5,
            "information security": 5,
            "seguridad de la información": 5,
            "seguridad de la informacion": 5,
            "network engineer": 4,
            "network administrator": 4,
            "redes": 2,
            "business analyst": 4,
            "analista de negocio": 4,
        },
    },

    "software": {
        "es": "09_ES",
        "en": "10_EN",
        "signals": {
            "software engineer": 6,
            "software developer": 5,
            "desarrollador": 5,
            "desarrolladora": 5,
            "programador": 5,
            "developer": 4,
            "full stack": 4,
            "full-stack": 4,
            "java": 3,
            "kotlin": 3,
            "microservices": 2,
            "microservicios": 2,
            "solution engineer": 3,
            "solutions engineer": 3,
        },
    },
}


COMMON_TECH = (
    "python",
    "java",
    "kotlin",
    "sql",
    "postgresql",
    "api",
    "linux",
    "docker",
    "kubernetes",
    "cloud",
    "git",
    "microservices",
    "microservicios",
    "spark",
    "pyspark",
    "grafana",
    "splunk",
    "instana",
    "llm",
    "rag",
    "backend",
    "software",
    "developer",
    "desarrollador",
    "aws",
    "gcp",
    "terraform",
    "prometheus",
    "datadog",
    "opensearch",
    "monitoring",
    "monitoreo",
    "technical support",
    "support engineer",
    "application support",
    "sistemas",
)


AVOID_CENTRAL = (
    # Commercial / sales
    "sales representative",
    "sales executive",
    "account executive",
    "business development representative",
    "gerente de cuentas",
    "key account manager",

    # HR / recruiting
    "recruiter",
    "talent acquisition",
    "human resources",
    "recursos humanos",
    "rrhh",

    # Finance / accounting
    "contador",
    "contable",
    "contabilidad",
    "accountant",
    "accounting manager",
    "director of finance",
    "finance director",
    "billing specialist",
    "tesorería",
    "tesoreria",
    "cobranza",
    "insurance agent",

    # Administrative / generic service roles
    "asistente administrativo",
    "administrative assistant",
    "executive assistant",
    "call center",
    "customer service representative",
    "customer success manager",
    "customer success associate",
    "customer success senior",
    "customer care",
    "customer engagement",
    "guest experience",
    "resident service coordinator",
    "dispatcher",
    "coordinador de eventos",
    "coordinador/a de eventos",

    # Finance / compliance / business operations
    "control interno",
    "cumplimiento sox",
    "control de gestión",
    "control de gestion",
    "back office",
    "mesa de dinero",
    "lavado de dinero",
    "prevención de lavado",
    "prevencion de lavado",
    "bookkeeping",
    "actuario",
    "actuary",
    "operaciones bancarias",
    "revenue operations manager",
    "licitaciones",
    "excelencia operacional",
    "asesor financiero",
    "financial advisor",

    # Generic non-technical operations / customer roles.
    # Some have explicit technical exceptions below.
    "operations analyst",
    "operations assistant",
    "onboarding",
    "customer support",
    "customer succes associate",
)


ACCEPTED_LOCATION = (
    "remote",
    "remoto",
    "santiago",
    "chile",
    "latam",
    "latin america",
    "south america",
)


EN_MARKERS = (
    "requirements",
    "responsibilities",
    "we are looking",
    "experience with",
    "about the role",
    "developer",
    "engineer",
    "skills",
    "remote",
)

ES_MARKERS = (
    "requisitos",
    "responsabilidades",
    "buscamos",
    "experiencia",
    "sobre el cargo",
    "desarrollador",
    "ingeniero",
    "conocimientos",
    "remoto",
)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _compact(text: str, max_chars: int) -> str:
    text = re.sub(
        r"\n{3,}",
        "\n\n",
        text or "",
    ).strip()

    if len(text) <= max_chars:
        return text

    head = int(max_chars * 0.72)
    tail = max_chars - head

    return (
        text[:head]
        + "\n[...]\n"
        + text[-tail:]
    )


def _role_identity(
    job_text: str,
    source_url: str | None,
) -> str:
    """
    Stable role identity.

    Prefer the final URL slug because Get on Board's body may
    contain recommendations, navigation and unrelated jobs.
    """

    slug = ""

    try:
        slug = (
            urlsplit(str(source_url or ""))
            .path
            .rstrip("/")
            .split("/")[-1]
        )
    except Exception:
        slug = ""

    if slug:
        return re.sub(
            r"[-_]+",
            " ",
            slug.casefold(),
        ).strip()

    # Fallback only when there is no URL.
    for line in (job_text or "").splitlines():
        value = line.strip()

        if value:
            return value.casefold()[:300]

    return ""


def _vacancy_text(job_text: str) -> str:
    """
    Keep the actual vacancy area and discard common recommendation/
    footer sections that otherwise contaminate skill detection.
    """

    text = (job_text or "").strip()

    if not text:
        return ""

    lowered = text.casefold()

    markers = (
        "\ntrabajos similares",
        "\ntrabajos recomendados",
        "\nofertas similares",
        "\notras ofertas",
        "\nsimilar jobs",
        "\nrecommended jobs",
        "\nother jobs",
        "\nmore jobs",
        "\nexplora otros",
        "\nexplore other",
    )

    cuts = []

    for marker in markers:
        pos = lowered.find(marker)

        # Never cut inside the vacancy header.
        if pos >= 700:
            cuts.append(pos)

    if cuts:
        text = text[:min(cuts)]

    # Hard upper bound against huge navigation/sidebar blobs.
    return text[:9000]


def _targeting_blob(
    job_text: str,
    source_url: str | None,
) -> str:
    return (
        _role_identity(
            job_text,
            source_url,
        )
        + "\n"
        + _vacancy_text(job_text)
    ).casefold()


def _internship_role(
    role_identity: str,
) -> str | None:

    patterns = (
        r"\bpráctica\b",
        r"\bpractica\b",
        r"\bpracticante\b",
        r"\binternship\b",
        r"\bintern\b",
        r"\btrainee\b",
    )

    for pattern in patterns:
        if re.search(
            pattern,
            role_identity,
        ):
            return pattern

    return None


def _strict_location_ok(
    job_text: str,
    source_url: str | None,
) -> bool:
    """
    Auto-apply target:
      - Remote / remoto / regional remote
      - Santiago

    'Chile' by itself is intentionally NOT sufficient because
    the user only targets presencial/híbrido in Santiago.
    """

    identity = _role_identity(
        job_text,
        source_url,
    )

    head = _vacancy_text(
        job_text
    )[:1400].casefold()

    location_blob = (
        identity
        + "\n"
        + head
    )

    if re.search(
        r"\b(remote|remoto)\b",
        location_blob,
    ):
        return True

    if "santiago" in location_blob:
        return True

    # Regional remote wording.
    if (
        any(
            term in location_blob
            for term in (
                "latam",
                "latin america",
                "south america",
            )
        )
        and any(
            term in location_blob
            for term in (
                "remote",
                "remoto",
                "based anywhere",
            )
        )
    ):
        return True

    return False


def _language(blob: str) -> str:
    en = sum(
        marker in blob
        for marker in EN_MARKERS
    )

    es = sum(
        marker in blob
        for marker in ES_MARKERS
    )

    return "en" if en > es else "es"


def _family_scores(blob: str) -> dict[str, int]:
    scores: dict[str, int] = {}

    for name, data in FAMILIES.items():
        score = 0

        for token, weight in data["signals"].items():
            if token in blob:
                score += weight

        scores[name] = score

    return scores


def _best_family(blob: str) -> tuple[str, int]:
    """
    Return the strongest supported family.

    Important:
    FAMILIES starts with ``ai``.  A raw max() therefore made
    every all-zero tie become ``ai`` even when the vacancy had
    absolutely no AI evidence.

    Zero-signal vacancies now use the neutral software family;
    the low-signal gate later decides whether they should be
    discarded.
    """
    scores = _family_scores(blob)

    family, score = max(
        scores.items(),
        key=lambda item: item[1],
    )

    if score <= 0:
        return "software", 0

    return family, score


def _cv_for(
    family: str,
    language: str,
) -> str:

    data = FAMILIES.get(
        family,
        FAMILIES["software"],
    )

    return str(data[language])


def _tech_hits(blob: str) -> int:
    return sum(
        token in blob
        for token in COMMON_TECH
    )


def _max_required_years(blob: str) -> int:
    values: list[int] = []

    patterns = (
        r"(\d+)\+?\s*(?:years|year)\b",
        r"(\d+)\+?\s*(?:años|anos)\b",
    )

    for pattern in patterns:
        for match in re.findall(pattern, blob):
            try:
                values.append(int(match))
            except ValueError:
                pass

    return max(values, default=0)


def _hard_blocker(blob: str) -> str | None:
    for blocker in HARD_BLOCKERS:
        if blocker in blob:
            return blocker

    return None


def _central_mismatch(
    role_identity: str,
) -> str | None:
    """
    Central-function mismatches come from the role identity only.

    Generic operations/support/onboarding titles may still be
    legitimate when the title itself explicitly identifies an
    IT/technical function. Finance, compliance, accounting, sales,
    HR and generic customer-success roles remain hard mismatches.
    """

    technical_identity_markers = (
        "technical",
        "técnico",
        "tecnico",
        "technology",
        "tecnología",
        "tecnologia",
        " it ",
        " ti ",
        "devops",
        "sre",
        "cloud",
        "infraestructura",
        "infrastructure",
        "application support",
        "soporte ti",
        "soporte técnico",
        "soporte tecnico",
        "helpdesk",
        "help desk",
        "service desk",
        "systems",
        "sistemas",
        "software",
        "developer",
        "desarrollador",
        "engineer",
        "ingeniero",
        "data ",
        "datos",
        "database",
        "dba",
        "cybersecurity",
        "ciberseguridad",
        "security",
        "seguridad",
        "network",
        "redes",
    )

    technical_identity = any(
        marker in f" {role_identity} "
        for marker in technical_identity_markers
    )

    technical_exemptable = (
        "operations analyst",
        "onboarding",
        "customer support",
    )

    for term in AVOID_CENTRAL:

        if term not in role_identity:
            continue

        if (
            term in technical_exemptable
            and technical_identity
        ):
            continue

        return term

    return None


def _central_qa_role(
    job_text: str,
    source_url: str | None,
) -> str | None:
    """
    Exclude formal QA roles based on the actual role identity.

    Never inspect the page body for QA markers: Get on Board can
    include recommended QA vacancies in the same rendered page.
    """

    identity = _role_identity(
        job_text,
        source_url,
    )

    if re.search(
        r"(^|\s)qa(\s|$)",
        identity,
    ):
        return "qa"

    strong_markers = (
        "quality assurance",
        "software tester",
        "manual tester",
        "automation tester",
        "test automation engineer",
        "test engineer",
        "software development engineer in test",
    )

    for marker in strong_markers:
        if marker in identity:
            return marker

    if re.search(
        r"(^|\s)sdet(\s|$)",
        identity,
    ):
        return "sdet"

    return None


def _build_result(
    *,
    decision: str,
    score: int,
    cv_id: str | None,
    source_url: str | None,
    why: str,
    hard_gaps: list[str] | None = None,
) -> JobDecision:

    return JobDecision.model_validate(
        {
            "decision": decision,
            "match_score": max(
                0,
                min(100, int(score)),
            ),
            "job": {
                "url": source_url,
            },
            "cv_id": cv_id,
            "salary_usd_monthly": 2050,
            "salary_reason": (
                "Default autonomous salary policy; "
                "later form logic may refine it."
            ),
            "why": why,
            "hard_gaps": hard_gaps or [],
            "unsupported_claims": [],
            "form_answers": [],
            "interview_defensibility": (
                "Decision based only on verified candidate "
                "facts and deterministic role/skill matching."
            ),
        }
    )


def _deterministic_score(
    *,
    blob: str,
    family_score: int,
    tech_hits: int,
    location_ok: bool,
) -> int:

    score = 52

    score += min(
        family_score * 3,
        27,
    )

    score += min(
        tech_hits * 2,
        10,
    )

    if location_ok:
        score += 4

    years = _max_required_years(blob)

    if years >= 8:
        score -= 14
    elif years >= 6:
        score -= 10
    elif years >= 5:
        score -= 6

    if any(
        x in blob
        for x in (
            "principal engineer",
            "staff engineer",
            "engineering manager",
            "head of engineering",
            "director of engineering",
        )
    ):
        score -= 12

    elif any(
        x in blob
        for x in (
            "senior",
            "tech lead",
            "technical lead",
        )
    ):
        score -= 5

    return max(
        0,
        min(100, score),
    )


async def _gray_llm(
    *,
    vacancy: str,
    model: str,
    timeout: int,
) -> GrayDecision | None:
    """
    LLM only handles ambiguous edge cases.

    Timeout is non-fatal: an ambiguous vacancy simply remains REVIEW.
    """

    schema = GrayDecision.model_json_schema()

    prompt = (
        "VACANCY:\n"
        + _compact(vacancy, 1300)
    )

    print(
        "🧠 GRAY-ZONE LLM:"
        f" model={model}"
        f" prompt_chars={len(prompt)}"
        f" schema_chars={len(json.dumps(schema))}"
    )

    try:
        response = await structured_chat(
            system=GRAY_SYSTEM,
            user=prompt,
            schema=schema,
            model=model,
            num_ctx=1024,
            num_predict=48,
            timeout=timeout,
        )

        decision = GrayDecision.model_validate(
            response["data"]
        )

        metrics = response.get(
            "metrics"
        ) or {}

        print(
            "🦙 GRAY-ZONE RESULT:"
            f" decision={decision.decision}"
            f" score={decision.match_score}"
            f" prompt_s={metrics.get('prompt_seconds')}"
            f" gen_s={metrics.get('generation_seconds')}"
        )

        return decision

    except Exception as exc:
        print(
            "⚠️ GRAY-ZONE LLM unavailable:"
            f" {type(exc).__name__}: {exc}"
            " → REVIEW seguro, batch continúa."
        )

        return None


def _resolve_gray_advisory(
    *,
    deterministic_score: int,
    gray: GrayDecision | None,
) -> tuple[str, int, str]:
    """
    v0.6.11.7 GRAY ADVISORY POLICY.

    The deterministic engine owns MATCH SCORE.

    The tiny local LLM may provide an advisory decision,
    but its numeric score never overwrites deterministic
    evidence.

    Safety:
      - timeout/unavailable => REVIEW, deterministic score
      - APPLY => APPLY only when deterministic score >= 60
      - REVIEW => REVIEW
      - SKIP => honored only when deterministic score < 60
      - a weak/invalid LLM score (including 0) is telemetry only
    """

    score = max(
        0,
        min(
            100,
            int(
                deterministic_score
            ),
        ),
    )

    if gray is None:
        return (
            "REVIEW",
            score,
            "llm_unavailable",
        )

    raw_decision = str(
        gray.decision
        or ""
    ).upper()

    try:
        raw_score = int(
            gray.match_score
        )
    except Exception:
        raw_score = -1

    if raw_decision == "APPLY":

        if score >= 60:
            final = "APPLY"
        else:
            final = "REVIEW"

    elif raw_decision == "SKIP":

        # Tiny LLM cannot discard an otherwise
        # promotion-grade deterministic match.
        if score >= 60:
            final = "REVIEW"
        else:
            final = "SKIP"

    else:
        final = "REVIEW"

    reason = (
        f"llm_decision={raw_decision or 'UNKNOWN'};"
        f"llm_score={raw_score};"
        f"deterministic_score={score};"
        f"final={final}"
    )

    return (
        final,
        score,
        reason,
    )


async def analyze_job(
    job_text: str,
    source_url: str | None = None,
) -> JobDecision:

    role_identity = _role_identity(
        job_text,
        source_url,
    )

    vacancy_text = _vacancy_text(
        job_text
    )

    blob = _targeting_blob(
        job_text,
        source_url,
    )

    internship = _internship_role(
        role_identity
    )

    if internship:
        print(
            "⚡ DETERMINISTIC SKIP:"
            " internship_or_practice_role"
        )

        return _build_result(
            decision="SKIP",
            score=0,
            cv_id=None,
            source_url=source_url,
            why=(
                "Internship/practice role excluded "
                "by candidate targeting policy."
            ),
            hard_gaps=[
                "internship/practice role excluded",
            ],
        )

    blocker = _hard_blocker(blob)

    if blocker:
        print(
            "⚡ DETERMINISTIC SKIP:"
            f" blocker={blocker!r}"
        )

        return _build_result(
            decision="SKIP",
            score=0,
            cv_id=None,
            source_url=source_url,
            why=(
                "Deterministic hard blocker: "
                + blocker
            ),
            hard_gaps=[blocker],
        )

    qa_role = _central_qa_role(
        job_text,
        source_url,
    )

    if qa_role:
        print(
            "⚡ DETERMINISTIC SKIP:"
            f" formal_qa_role={qa_role!r}"
        )

        return _build_result(
            decision="SKIP",
            score=0,
            cv_id=None,
            source_url=source_url,
            why=(
                "Formal QA/testing role excluded "
                "by candidate targeting policy: "
                + qa_role
            ),
            hard_gaps=[
                "formal QA/testing role excluded",
            ],
        )

    language = _language(blob)

    family, family_score = _best_family(
        blob
    )

    tech_hits = _tech_hits(blob)

    mismatch = _central_mismatch(
        role_identity,
    )

    if mismatch:
        print(
            "⚡ DETERMINISTIC SKIP:"
            f" central_mismatch={mismatch!r}"
        )

        return _build_result(
            decision="SKIP",
            score=15,
            cv_id=None,
            source_url=source_url,
            why=(
                "Central function mismatch: "
                + mismatch
            ),
            hard_gaps=[mismatch],
        )

    # No family evidence and no known technology evidence:
    # do not create permanent REVIEW debt simply because the
    # local LLM is unavailable.
    if (
        family_score == 0
        and tech_hits < 3
    ):
        print(
            "⚡ DETERMINISTIC SKIP:"
            " no technology targeting signal"
        )

        return _build_result(
            decision="SKIP",
            score=20,
            cv_id=None,
            source_url=source_url,
            why=(
                "Deterministic low-signal technology "
                "mismatch; no supported family or "
                "candidate technology signal."
            ),
            hard_gaps=[
                "no supported technology targeting signal",
            ],
        )

    cv_id = _cv_for(
        family,
        language,
    )

    location_ok = _strict_location_ok(
        job_text,
        source_url,
    )

    score = _deterministic_score(
        blob=blob,
        family_score=family_score,
        tech_hits=tech_hits,
        location_ok=location_ok,
    )

    print(
        "⚡ DETERMINISTIC TRIAGE:"
        f" family={family}"
        f" family_score={family_score}"
        f" tech_hits={tech_hits}"
        f" score={score}"
        f" cv={cv_id}"
        f" lang={language}"
    )

    # --------------------------------------------------------
    # CLEAR TECH MATCH
    # --------------------------------------------------------
    #
    # REVIEW is intentional. The existing post-LLM safety
    # policy remains responsible for promoting safe REVIEW
    # decisions to APPLY.
    if (
        family_score >= 6
        and tech_hits >= 2
        and score >= 60
    ):
        return _build_result(
            decision="REVIEW",
            score=score,
            cv_id=cv_id,
            source_url=source_url,
            why=(
                "Deterministic clear technology match; "
                f"family={family}, score={score}."
            ),
        )

    # --------------------------------------------------------
    # WEAK TECH / AMBIGUOUS CASE
    # --------------------------------------------------------
    model = os.getenv(
        "AGENT_ANALYSIS_MODEL",
        "llama3.2:1b",
    )

    timeout = _env_int(
        "AGENT_ANALYSIS_TIMEOUT",
        30,
    )

    gray = await _gray_llm(
        vacancy=vacancy_text,
        model=model,
        timeout=timeout,
    )

    (
        decision,
        resolved_score,
        gray_reason,
    ) = _resolve_gray_advisory(
        deterministic_score=score,
        gray=gray,
    )

    if gray is None:

        print(
            "🛡️ GRAY ADVISORY FALLBACK:"
            f" deterministic_score={score}"
            " preserved"
        )

    else:

        print(
            "🛡️ GRAY ADVISORY:"
            f" llm_decision={gray.decision}"
            f" llm_score={gray.match_score}"
            f" deterministic_score={score}"
            f" final={decision}"
        )

    if decision == "SKIP":
        cv_result = None
    else:
        cv_result = cv_id

    return _build_result(
        decision=decision,
        score=resolved_score,
        cv_id=cv_result,
        source_url=source_url,
        why=(
            "Gray-zone advisory decision; "
            f"family={family}; "
            f"{gray_reason}."
        ),
    )
