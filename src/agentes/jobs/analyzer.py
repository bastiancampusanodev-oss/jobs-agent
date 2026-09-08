from __future__ import annotations

import json
import os
import re
from typing import Literal

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
    "sales representative",
    "sales executive",
    "account executive",
    "business development representative",
    "recruiter",
    "talent acquisition",
    "human resources",
    "recursos humanos",
    "contador",
    "contabilidad",
    "accountant",
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
    blob: str,
    tech_hits: int,
) -> str | None:

    # Focus mainly on title / beginning of vacancy.
    head = blob[:1000]

    for term in AVOID_CENTRAL:
        if term in head and tech_hits < 3:
            return term

    return None


def _central_qa_role(
    blob: str,
    source_url: str | None,
) -> str | None:
    """
    Exclude formal QA/testing jobs while preserving the mixed
    Get on Board sysadmin-devops-qa discovery category.

    Generic words such as ``test`` or the category slug ``qa``
    are deliberately NOT enough to reject a vacancy because
    developers, DevOps and SRE roles frequently mention tests
    or live inside that mixed category.
    """

    url_text = re.sub(
        r"[-_/]+",
        " ",
        str(source_url or "").casefold(),
    )

    # The title and role identity normally appear near the top.
    head = (
        url_text
        + "\n"
        + blob[:1400]
    )

    strong_markers = (
        "qa engineer",
        "qa analyst",
        "analista qa",
        "ingeniero qa",
        "qa automation",
        "automation qa",
        "qa funcional",
        "qa manual",
        "quality assurance engineer",
        "quality assurance analyst",
        "software tester",
        "manual tester",
        "automation tester",
        "test automation engineer",
        "test engineer",
        "sdet",
        "software development engineer in test",
    )

    for marker in strong_markers:
        if marker in head:
            return marker

    if re.search(
        r"\btester\b",
        head,
    ):
        return "tester"

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

    if any(
        x in blob
        for x in ACCEPTED_LOCATION
    ):
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

    blob = (job_text or "").casefold()

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
        blob,
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
        blob,
        tech_hits,
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
        and tech_hits == 0
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

    score = _deterministic_score(
        blob=blob,
        family_score=family_score,
        tech_hits=tech_hits,
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
        vacancy=job_text,
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
