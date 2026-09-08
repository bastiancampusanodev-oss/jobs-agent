from __future__ import annotations

import asyncio
import json
import os
import re
import time
import unicodedata
from urllib import request as urllib_request
from typing import Literal, Optional

from pydantic import BaseModel, Field


class GroundedFallbackAnswer(BaseModel):
    field_key: str
    action: Literal["answer", "human"] = "human"
    basis: Literal["grounded", "conservative_no", "human"] = "human"
    text: Optional[str] = None
    selected: list[str] = Field(default_factory=list)
    checked: Optional[bool] = None
    evidence_quotes: list[str] = Field(default_factory=list)
    reason: str = ""


class GroundedFallbackAnswers(BaseModel):
    answers: list[GroundedFallbackAnswer] = Field(default_factory=list)


def _norm(text: str) -> str:
    raw = unicodedata.normalize("NFKD", str(text or "").casefold())
    raw = "".join(ch for ch in raw if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", raw).strip()


def _field_blob(field: dict) -> str:
    return _norm(
        " ".join(
            str(field.get(key) or "")
            for key in ("field_key", "label", "name", "id")
        )
    )


def _visible_options(field: dict) -> list[str]:
    out: list[str] = []
    for option in field.get("options") or []:
        if isinstance(option, dict):
            label = str(option.get("label") or "").strip()
            value = str(option.get("value") or "").strip()
            visible = label or value
        else:
            visible = str(option or "").strip()
        if visible:
            out.append(visible)
    return out


def recover_group_question(
    option_labels: list[str],
    context_labels: list[str],
) -> str | None:
    """Recover a radio/checkbox question when DOM labels are only SI/NO options."""

    option_norms = {_norm(value) for value in option_labels if _norm(value)}

    for context in context_labels:
        lines = [
            re.sub(r"\s+", " ", line).strip()
            for line in str(context or "").splitlines()
            if re.sub(r"\s+", " ", line).strip()
        ]
        filtered = [
            line
            for line in lines
            if _norm(line) not in option_norms
            and _norm(line) not in {"required", "requerido", "obligatorio"}
        ]
        candidate = " ".join(filtered).strip()
        if candidate and _norm(candidate) not in option_norms and len(candidate) >= 4:
            return candidate[:700]

    return None


def field_blocked_from_llm(field: dict) -> tuple[bool, str]:
    """Fields that must remain HUMAN_REVIEW even with a local LLM fallback."""

    label = _norm(field.get("label") or "")
    blob = _field_blob(field)

    # Broken/low-information extraction such as a field whose only visible
    # label is "SI" is not enough context for an autonomous choice.
    if label in {"", "si", "no", "yes", "true", "false", "n/a", "na"}:
        return True, "Etiqueta ambigua o sin contexto suficiente."

    sensitive_or_identity = (
        "rut",
        "dni",
        "cedula",
        "pasaporte",
        "passport",
        "ssn",
        "social security",
        "fecha de nacimiento",
        "date of birth",
        "estado civil",
        "marital status",
        "discapacidad",
        "disability",
        "genero",
        "gender",
        "sexo",
        "antecedentes penales",
        "criminal record",
        "cuenta bancaria",
        "bank account",
        "tax id",
    )
    if any(term in blob for term in sensitive_or_identity):
        return True, "Dato personal/sensible no automatizable por fallback."

    legal_consent = (
        "acepto los terminos",
        "acepto terminos",
        "terms and conditions",
        "privacy policy",
        "politica de privacidad",
        "consentimiento",
        "consent",
        "autorizo el tratamiento",
        "declaro bajo",
        "i certify",
        "certifico que",
    )
    if any(term in blob for term in legal_consent):
        return True, "Consentimiento/declaración legal requiere regla explícita."

    # Salary already has a dedicated deterministic engine. If it reaches the
    # fallback, especially in another currency or net/gross terms, guessing is
    # worse than stopping.
    money_terms = (
        "salario",
        "salary",
        "renta",
        "sueldo",
        "compensation",
        "remuneracion",
        "pretension",
        "pretensiones",
        "expectativa salarial",
        "espectativa salarial",
        "salary expectation",
        "expected salary",
        "clp",
        "liquida",
        "liquido",
        "gross",
        "net salary",
    )
    if any(term in blob for term in money_terms):
        return True, "Compensación no resuelta por el salary engine."

    return False, ""


def _looks_like_experience_question(field: dict) -> bool:
    blob = _field_blob(field)
    terms = (
        "experiencia",
        "experience",
        "conocimiento",
        "knowledge",
        "manejo",
        "dominio",
        "proficiency",
        "worked with",
        "trabajado con",
        "utilizando",
        "using",
        "implementado",
        "implemented",
        "administrado",
        "administered",
        "herramientas",
        "tools",
        "tecnologia",
        "technology",
        "aws",
        "azure",
        "gcp",
        "python",
        "java",
        "javascript",
        "node",
        "sql",
    )
    return any(term in blob for term in terms)


def _quote_is_grounded(quote: str, grounding: str) -> bool:
    q = _norm(quote)
    corpus = _norm(grounding)
    return len(q) >= 3 and q in corpus


def validate_fallback_answer(
    field: dict,
    answer: GroundedFallbackAnswer,
    grounding: str,
) -> GroundedFallbackAnswer | None:
    """Deterministically reject an LLM answer unless it satisfies guardrails."""

    blocked, _ = field_blocked_from_llm(field)
    if blocked or answer.action != "answer":
        return None

    kind = str(field.get("kind") or "")

    if answer.basis == "grounded":
        quotes = [q.strip() for q in answer.evidence_quotes if str(q).strip()]
        if not quotes or not all(_quote_is_grounded(q, grounding) for q in quotes):
            return None
    elif answer.basis == "conservative_no":
        # A conservative negative is allowed only for a question about
        # experience/knowledge. It must be phrased as lack of *documented*
        # direct experience, rather than an absolute autobiographical claim.
        if not _looks_like_experience_question(field):
            return None
        text_norm = _norm(answer.text or "")
        safe_markers = (
            "no cuento con experiencia directa respaldada",
            "no tengo experiencia directa respaldada",
            "no tengo experiencia directa documentada",
            "i do not have documented direct experience",
            "i do not have direct experience documented",
            "my current profile does not document direct experience",
        )
        if not any(marker in text_norm for marker in safe_markers):
            return None
    else:
        return None

    if kind == "text":
        text = str(answer.text or "").strip()
        if not text or len(text) > 1200:
            return None
        answer.text = text
        answer.selected = []
        answer.checked = None
        return answer

    if kind in {"select", "radio"}:
        options = _visible_options(field)
        if len(answer.selected) != 1 or not options:
            return None
        target = _norm(answer.selected[0])
        exact = next((option for option in options if _norm(option) == target), None)
        if exact is None:
            return None
        answer.selected = [exact]
        answer.text = None
        answer.checked = None
        return answer

    if kind == "checkbox":
        if answer.checked is None:
            return None
        answer.text = None
        answer.selected = []
        return answer

    return None


def _fallback_prompt(
    fields: list[dict],
    job_text: str,
    grounding: str,
    salary_usd: int | None,
    cv_id: str,
) -> str:
    return f"""
CANDIDATE GROUNDING — AUTHORITATIVE
===================================
{grounding[:5000]}

JOB CONTEXT — NOT EVIDENCE ABOUT THE CANDIDATE
===============================================
{str(job_text or '')[:2200]}

CURRENT APPLICATION STATE
=========================
salary_usd_monthly={salary_usd or ''}
cv_id={cv_id}

UNRESOLVED CUSTOM FIELDS
========================
{json.dumps(fields, ensure_ascii=False, separators=(",", ":"))[:3200]}
"""


def _native_ollama_url() -> str:
    base = os.getenv(
        "AGENT_LLM_BASE_URL",
        "http://127.0.0.1:11434/v1",
    ).rstrip("/")
    if base.endswith("/v1"):
        base = base[:-3]
    return base.rstrip("/") + "/api/chat"


def _native_ollama_call(
    *,
    model: str,
    system_prompt: str,
    user_prompt: str,
    timeout_seconds: float,
) -> tuple[GroundedFallbackAnswers, dict]:
    """Single-shot structured call to local Ollama's native /api/chat API."""

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "format": GroundedFallbackAnswers.model_json_schema(),
        "keep_alive": "10m",
        "options": {
            "temperature": 0,
            "seed": 42,
            "num_ctx": 4096,
            "num_predict": 360,
        },
    }

    req = urllib_request.Request(
        _native_ollama_url(),
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urllib_request.urlopen(req, timeout=timeout_seconds) as response:
        body = json.loads(response.read().decode("utf-8"))

    content = str(((body.get("message") or {}).get("content")) or "").strip()
    if not content:
        raise RuntimeError("Ollama devolvió una respuesta estructurada vacía.")

    parsed = GroundedFallbackAnswers.model_validate_json(content)
    return parsed, body


_SYSTEM_PROMPT = """
You answer ONLY unresolved job-application CUSTOM fields using a candidate's
provided grounding. You are a fallback after deterministic rules failed.

NON-NEGOTIABLE RULES:
1. Never invent candidate experience, years, achievements, certifications,
   language level, legal facts, salary, or preferences.
2. CANDIDATE GROUNDING is the only evidence about the candidate. JOB CONTEXT
   describes employer needs and is NEVER evidence about the candidate.
3. Preserve the language of each question whenever practical.
4. For an affirmative candidate-specific answer, use basis=grounded and copy
   short evidence_quotes VERBATIM from CANDIDATE GROUNDING.
5. Every candidate-specific factual claim must be supported by those quotes.
   Never upgrade exposure/use to implementation, administration or expertise.
6. Motivation may combine JOB CONTEXT with grounded candidate interests/skills,
   but candidate-specific claims still require evidence_quotes.
7. Willingness/availability/contract answers may be positive only when the
   grounding explicitly supports them.
8. If technology/experience is undocumented, basis=conservative_no is allowed
   ONLY for experience/knowledge questions. State lack of documented/direct
   experience in the current profile, not an absolute life-history claim.
9. For select/radio, selected must exactly copy ONE visible option.
10. For an ordinary job-application question, do not return action=human merely because a positive claim is unsupported. Answer truthfully using grounded evidence when available; otherwise use a conservative limitation or negative answer without inventing experience or years. For select/radio, prefer an exact visible No/0/None option when a positive answer cannot be grounded. Reserve action=human for authentication secrets, sensitive identity numbers, or explicit legal consent.
11. Keep answers concise, natural, professional and interview-defensible.
12. Never mention internal systems, grounding, RAG, CandidateTruth or AI.
"""


async def answer_with_grounded_ollama(
    fields: list[dict],
    job_text: str,
    grounding: str,
    salary_usd: int | None,
    cv_id: str,
) -> dict[str, GroundedFallbackAnswer]:
    """
    Ask local Ollama only for unresolved CUSTOM fields.

    v0.5.36 deliberately bypasses the Agents SDK for this fallback. The
    previous agent loop could perform multiple large OpenAI-compatible turns
    and time out on CPU-only laptops. This path performs ONE compact native
    Ollama /api/chat request with a JSON schema, then applies the same
    deterministic evidence validation as before.
    """

    eligible: list[dict] = []
    for field in fields:
        blocked, _ = field_blocked_from_llm(field)
        if not blocked:
            eligible.append(field)

    if not eligible:
        return {}

    provider = os.getenv("AGENT_LLM_PROVIDER", "ollama").strip().lower()
    if provider != "ollama":
        # This fallback is intentionally local-only. Never silently send the
        # candidate grounding to a cloud provider.
        raise RuntimeError(
            "CUSTOM fallback requiere AGENT_LLM_PROVIDER=ollama; "
            f"provider actual={provider!r}."
        )

    model = os.getenv(
        "AGENT_CUSTOM_LLM_MODEL",
        "llama3.2:1b",
    ).strip()
    timeout_seconds = float(os.getenv("AGENT_CUSTOM_LLM_TIMEOUT", "60"))

    prompt = _fallback_prompt(
        eligible,
        job_text,
        grounding,
        salary_usd,
        cv_id,
    )

    started = time.monotonic()
    output, raw = await asyncio.to_thread(
        _native_ollama_call,
        model=model,
        system_prompt=_SYSTEM_PROMPT,
        user_prompt=prompt,
        timeout_seconds=timeout_seconds,
    )
    elapsed = time.monotonic() - started

    print(
        "🦙 OLLAMA CUSTOM FALLBACK:"
        f" model={model}"
        f" fields={len(eligible)}"
        f" prompt_chars={len(prompt)}"
        f" prompt_tokens={raw.get('prompt_eval_count', '-')}"
        f" output_tokens={raw.get('eval_count', '-')}"
        f" elapsed={elapsed:.1f}s"
    )

    field_by_key = {
        str(field.get("field_key") or ""): field
        for field in eligible
    }

    safe: dict[str, GroundedFallbackAnswer] = {}
    for answer in output.answers:
        field = field_by_key.get(answer.field_key)
        if not field:
            continue
        validated = validate_fallback_answer(field, answer, grounding)
        if validated is not None:
            safe[answer.field_key] = validated

    return safe
