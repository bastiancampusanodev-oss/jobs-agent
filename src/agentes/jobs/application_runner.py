from __future__ import annotations

import asyncio
import json
import os
import re
import unicodedata
from pathlib import Path
from typing import Optional, Literal

from agents import Agent, Runner, ModelSettings
from pydantic import BaseModel, Field

from agentes.browser import BrowserSession
from agentes.config import Settings, load_yaml
from agentes.llm_provider import get_agent_model
from agentes.jobs.analyzer import analyze_job
from agentes.jobs.cv_selector import select_cv, assert_cv_selected
from agentes.jobs.evidence_answerer import answer_from_evidence, evidence_is_user_facing
from agentes.jobs.candidate_truth import lookup_candidate_truth
from agentes.jobs.technical_answer_engine import (
    build_partial_technical_answer,
    looks_like_technical_question,
)
from agentes.jobs.experience_duration_engine import build_sre_devops_duration_answer
from agentes.jobs.profile_engine import build_profile
from agentes.jobs.motivation_engine import build_motivation
from agentes.jobs.gob_stage import resolve_gob_step
from agentes.jobs.salary_engine import (
    quote_salary,
    salary_answer_text,
)
from agentes.jobs.custom_llm_fallback import (
    answer_with_grounded_ollama,
    recover_group_question,
)
from agentes.jobs.custom_autonomy_policy import (
    autonomous_answer,
)
from agentes.jobs.custom_semantic_gate import (
    normalize_custom_answer,
)
from agentes.jobs.custom_known_facts import (
    work_authorization_answer,
    liquid_clp_salary_answer,
    motivation_custom_answer,
    work_mode_custom_answer,
    data_analysis_custom_answer,
    office_stack_custom_answer,
    banking_comex_custom_answer,
    process_certification_custom_answer,
    role_experience_custom_answer,
    qa_custom_answer,
    residence_country_custom_answer,
    english_level_custom_answer,
    professional_summary_custom_answer,
    technology_duration_custom_answer,
)
from agentes.jobs.custom_known_facts import financial_sector_custom_answer, project_stack_custom_answer


ROOT = Path(__file__).resolve().parents[3]


# ============================================================
# SCHEMAS
# ============================================================

class ProfileAnswers(BaseModel):
    language: Literal["es", "en"]
    professional: str
    academic: str


class Motivation(BaseModel):
    language: Literal["es", "en"]
    text: str


class CustomAnswer(BaseModel):
    field_key: str

    text: Optional[str] = None

    selected: list[str] = Field(
        default_factory=list
    )

    checked: Optional[bool] = None

    requires_human: bool = False

    reason: str = ""


class CustomAnswers(BaseModel):
    answers: list[CustomAnswer]


# ============================================================
# KNOWLEDGE / MINI-RAG
# ============================================================

def read_text(path: Path) -> str:
    try:
        return path.read_text(
            encoding="utf-8"
        )
    except Exception:
        return ""


def knowledge_chunks() -> list[str]:
    chunks: list[str] = []

    candidate = ROOT / "config" / "candidate.yaml"

    if candidate.exists():
        chunks.append(
            "SOURCE: candidate.yaml\n"
            + read_text(candidate)
        )

    rules = (
        ROOT
        / "config"
        / "application_rules.yaml"
    )

    if rules.exists():
        chunks.append(
            "SOURCE: application_rules.yaml\n"
            + read_text(rules)
        )

    technology_truth = (
        ROOT
        / "config"
        / "technology_truth.yaml"
    )

    if technology_truth.exists():
        chunks.append(
            "SOURCE: technology_truth.yaml\n"
            + read_text(technology_truth)
        )

    knowledge_dir = ROOT / "knowledge"

    if knowledge_dir.exists():
        for path in knowledge_dir.rglob("*"):
            if (
                path.is_file()
                and path.suffix.lower()
                in {".md", ".txt", ".yaml", ".yml"}
            ):
                text = read_text(path)

                if text:
                    chunks.append(
                        f"SOURCE: {path.name}\n{text}"
                    )

    # PDFs opcionales.
    cvs_dir = ROOT / "cvs"

    if cvs_dir.exists():
        try:
            from pypdf import PdfReader

            for path in cvs_dir.glob("*.pdf"):
                try:
                    reader = PdfReader(str(path))

                    text = "\n".join(
                        page.extract_text() or ""
                        for page in reader.pages
                    )

                    if text.strip():
                        chunks.append(
                            f"SOURCE CV: {path.name}\n{text}"
                        )

                except Exception:
                    pass

        except ImportError:
            pass

    # Dividir documentos grandes.
    out: list[str] = []

    for document in chunks:
        if len(document) <= 5000:
            out.append(document)
            continue

        paragraphs = document.split("\n\n")

        buffer = ""

        for paragraph in paragraphs:
            if len(buffer) + len(paragraph) > 3500:
                if buffer.strip():
                    out.append(buffer)

                buffer = paragraph
            else:
                buffer += "\n\n" + paragraph

        if buffer.strip():
            out.append(buffer)

    return out


def retrieve(
    query: str,
    limit: int = 8,
) -> str:

    chunks = knowledge_chunks()

    if not chunks:
        return ""

    tokens = set(
        re.findall(
            r"[a-záéíóúñ0-9+#.]{3,}",
            query.lower(),
        )
    )

    scored = []

    for chunk in chunks:
        text = chunk.lower()

        score = sum(
            1
            for token in tokens
            if token in text
        )

        scored.append(
            (score, chunk)
        )

    scored.sort(
        key=lambda x: x[0],
        reverse=True,
    )

    selected = [
        chunk
        for score, chunk in scored[:limit]
        if score > 0
    ]

    if not selected:
        selected = chunks[:4]

    return "\n\n---\n\n".join(selected)


# ============================================================
# PAGE / JOB
# ============================================================

async def _profile_editor_dom_present(
    page,
) -> bool:
    """
    v0.6.11.3 PROFILE DOM TRUTH.

    A query string saying step=experience is not sufficient
    evidence that the legacy draft actually exposes PROFILE.

    Require real editable DOM evidence.
    """

    async def any_visible(
        selectors,
    ) -> bool:

        for css in selectors:

            try:
                loc = page.locator(css)
                count = await loc.count()

                for index in range(count):

                    try:
                        if await loc.nth(
                            index
                        ).is_visible():
                            return True
                    except Exception:
                        continue

            except Exception:
                continue

        return False

    professional = await any_visible(
        (
            "#trix-professional",
            'textarea[id*="professional" i]',
            'textarea[name*="professional" i]',
            (
                '[contenteditable="true"]'
                '[id*="professional" i]'
            ),
            (
                '[contenteditable="true"]'
                '[aria-label*="professional" i]'
            ),
        )
    )

    academic = await any_visible(
        (
            "#trix-academic_background",
            'textarea[id*="academic" i]',
            'textarea[name*="academic" i]',
            (
                '[contenteditable="true"]'
                '[id*="academic" i]'
            ),
            (
                '[contenteditable="true"]'
                '[aria-label*="academic" i]'
            ),
        )
    )

    if professional and academic:
        return True

    # Modern/alternate GOB shape:
    # two visible Trix editors in PROFILE.
    try:
        editors = page.locator(
            "trix-editor"
        )

        visible = 0

        for index in range(
            await editors.count()
        ):

            try:
                if await editors.nth(
                    index
                ).is_visible():
                    visible += 1
            except Exception:
                continue

        if visible >= 2:
            return True

    except Exception:
        pass

    return False



async def _basic_form_dom_present(
    page,
) -> bool:
    """
    v0.6.11.4 BASIC DOM TRUTH.

    step=basic in URL/hidden state is not enough.
    Require visible controls belonging to the real BASIC form.
    """

    selectors = (
        "#job_application_expected_salary",
        "#reason-to-apply",
        'input[type="file"]',
        'select[id*="cv" i]',
        'select[name*="cv" i]',
        'select[id*="resume" i]',
        'select[name*="resume" i]',
        'input[id*="expected_salary" i]',
        'input[name*="expected_salary" i]',
    )

    for css in selectors:

        try:
            loc = page.locator(css)
            count = await loc.count()

            for index in range(count):

                try:
                    if await loc.nth(
                        index
                    ).is_visible():
                        return True

                except Exception:
                    continue

        except Exception:
            continue

    return False


async def detect_stage(page) -> str:
    """
    v0.6.11.3 DOM-FIRST STAGE DETECTION.

    Never trust step=experience by itself.  Legacy drafts can
    preserve that query parameter while rendering a different
    edit/preview shape.
    """

    url = page.url.lower()

    gob_step = await resolve_gob_step(
        page
    )

    if gob_step == "experience":

        if await _profile_editor_dom_present(
            page
        ):
            return "PROFILE"

        print(
            "⚠️ PROFILE STAGE GUARD: "
            "step=experience sin editores PROFILE reales."
        )

    if gob_step == "basic":

        if await _basic_form_dom_present(
            page
        ):
            return "BASIC"

        print(
            "⚠️ BASIC STAGE GUARD: "
            "step=basic sin formulario BASIC real."
        )

    if gob_step == "custom":
        return "CUSTOM"

    if (
        "/applications/new" in url
        and await _profile_editor_dom_present(
            page
        )
    ):
        return "PROFILE"

    if "job_application_preview=true" in url:
        return "REVIEW"

    body = (
        await page.locator(
            "body"
        ).inner_text()
    ).lower()

    if any(
        x in body
        for x in (
            "enviar postulación",
            "enviar postulacion",
            "submit application",
            "confirm application",
        )
    ):
        return "REVIEW"

    fields = await extract_custom_fields(
        page
    )

    if fields:
        return "CUSTOM"

    return "UNKNOWN"



async def get_job(page):
    # Si ya estamos directamente en una oferta.
    if (
        "/empleos/" in page.url
        and "/applications" not in page.url
    ):
        return (
            page.url,
            await page.locator("body").inner_text(),
        )

    links = await page.locator("a").evaluate_all(
        """
        els => els.map(a => ({
            text: (
                a.innerText ||
                a.textContent ||
                ''
            ).trim(),
            href: a.href || ''
        }))
        """
    )

    job_url = None

    for link in links:
        href = link["href"]

        if (
            "getonbrd.com" in href
            and "/applications/" not in href
            and (
                "/empleos/" in href
                or "/jobs/" in href
            )
        ):
            text = link["text"].lower()

            if text not in {
                "empleos para ti",
                "tus postulaciones",
                "invitaciones",
            }:
                job_url = href
                break

    if not job_url:
        raise RuntimeError(
            "No pude encontrar la oferta original."
        )

    temp = await page.context.new_page()

    try:
        await temp.goto(
            job_url,
            wait_until="domcontentloaded",
            timeout=30000,
        )

        await temp.wait_for_timeout(1000)

        text = await temp.locator(
            "body"
        ).inner_text()

    finally:
        await temp.close()

    return job_url, text


# ============================================================
# NAVIGATION
# ============================================================

# ============================================================
# v0.6.11.8a PROFESSIONAL PROFILE FALLBACK
# ============================================================

def _professional_profile_url() -> str:
    return str(
        os.getenv(
            "AGENT_PROFESSIONAL_PROFILE_URL",
            "",
        )
        or ""
    ).strip()



# ============================================================
# v0.6.11.8d PROFILE URL ROUTER
# ============================================================

def _portfolio_url() -> str:

    return str(
        os.getenv(
            "AGENT_PORTFOLIO_URL",
            "",
        )
        or ""
    ).strip()


def _known_profile_url_for_field(
    value: str,
) -> str | None:

    low = " ".join(
        str(value or "")
        .casefold()
        .replace("_", " ")
        .replace("-", " ")
        .split()
    )

    if not low:
        return None

    # Explicit portfolio/work samples/GitHub:
    # use the user's real GitHub portfolio.
    portfolio_markers = (
        "portfolio",
        "portafolio",
        "webpro portfolio",
        "github",
        "trabajos publicados",
        "work samples",
        "projects url",
        "project url",
    )

    if any(
        marker in low
        for marker in portfolio_markers
    ):
        return (
            _portfolio_url()
            or None
        )

    # Other named platforms must NOT receive LinkedIn.
    blocked_platforms = (
        "gitlab",
        "behance",
        "dribbble",
        "stackoverflow",
        "stack overflow",
    )

    if any(
        marker in low
        for marker in blocked_platforms
    ):
        return None

    linkedin_markers = (
        "linkedin",
        "linked in",
        "professional profile",
        "perfil profesional",
    )

    if any(
        marker in low
        for marker in linkedin_markers
    ):
        return (
            _professional_profile_url()
            or None
        )

    return None


def _is_professional_profile_field(
    value: str,
) -> bool:

    low = " ".join(
        str(value or "")
        .casefold()
        .replace("_", " ")
        .replace("-", " ")
        .split()
    )

    if not low:
        return False

    # Never disguise the LinkedIn fallback as another
    # explicitly requested platform.
    blocked = (
        "github",
        "gitlab",
        "behance",
        "dribbble",
        "stackoverflow",
        "stack overflow",
    )

    if any(
        token in low
        for token in blocked
    ):
        return False

    markers = (
        "linkedin",
        "linked in",
        "portfolio",
        "professional profile",
        "perfil profesional",
        "professional website",
        "sitio profesional",
        "webpro portfolio",
    )

    return any(
        marker in low
        for marker in markers
    )


async def _fill_known_professional_profile_urls(
    page,
) -> int:
    """
    Fill known candidate URL fields with the correct source:

      LinkedIn/profile  -> AGENT_PROFESSIONAL_PROFILE_URL
      Portfolio/GitHub -> AGENT_PORTFOLIO_URL

    Unknown URL fields remain untouched.
    """

    fields = page.locator(
        'input[type="url"]'
    )

    filled = 0

    for i in range(
        await fields.count()
    ):

        field = fields.nth(i)

        try:
            if not await field.is_visible():
                continue
        except Exception:
            continue

        try:
            current = (
                await field.input_value()
            ).strip()
        except Exception:
            current = ""

        if current:
            continue

        try:
            meta = await field.evaluate(
                """
                el => {
                    const labels = el.labels
                        ? Array.from(el.labels)
                            .map(x => (
                                x.innerText ||
                                x.textContent ||
                                ''
                            ).trim())
                            .join(' ')
                        : '';

                    return {
                        id: el.id || '',
                        name: el.name || '',
                        placeholder:
                            el.getAttribute('placeholder') || '',
                        aria:
                            el.getAttribute('aria-label') || '',
                        labels: labels
                    };
                }
                """
            )
        except Exception:
            meta = {}

        blob = " ".join(
            str(meta.get(key) or "")
            for key in (
                "id",
                "name",
                "placeholder",
                "aria",
                "labels",
            )
        )

        field_url = (
            _known_profile_url_for_field(
                blob
            )
        )

        if not field_url:
            continue

        await field.fill(
            field_url
        )

        # v0.6.11.9 — REACTIVE URL COMMIT
        #
        # Playwright fill() emits an input event, but some Get on Board
        # forms only recalculate their NEXT state after change + blur.
        # Commit the value through the same observable DOM events a human
        # edit would produce.  This never clicks or submits anything.
        try:
            await field.evaluate(
                """
                el => {
                    el.dispatchEvent(
                        new Event('input', {bubbles: true})
                    );
                    el.dispatchEvent(
                        new Event('change', {bubbles: true})
                    );
                    el.blur();
                }
                """
            )
        except Exception:
            try:
                await field.blur()
            except Exception:
                pass

        await page.wait_for_timeout(
            500
        )

        actual = (
            await field.input_value()
        ).strip()

        if actual != field_url:
            raise RuntimeError(
                "PROFILE_URL_FILL_FAILED: "
                f"expected={field_url!r} "
                f"actual={actual!r}"
            )

        filled += 1

        kind = (
            "portfolio"
            if field_url == _portfolio_url()
            else "linkedin"
        )

        print(
            f"🔗 {kind.upper()} URL rellenado: "
            + str(
                meta.get("id")
                or meta.get("name")
                or "url-field"
            )
        )

    return filled


# ============================================================
# v0.6.11.8d1 — RESTORED NEXT SAFETY HELPERS
# ============================================================

def _is_final_application_submit(
    text: str,
) -> bool:

    low = " ".join(
        str(text or "")
        .casefold()
        .split()
    )

    return (
        "enviar postulación" in low
        or "enviar postulacion" in low
        or low == "submit application"
    )


def _is_next_control_label(
    text: str,
) -> bool:

    if _is_final_application_submit(
        text
    ):
        return False

    return bool(
        re.search(
            r"(siguiente|next|continue|revisar|review)",
            str(text or ""),
            re.I,
        )
    )


async def _invalid_fields_for_button_form(
    button,
) -> list[dict]:
    """
    Diagnose only the HTML form associated with the
    application NEXT button.

    Never use page-wide :invalid here: Get on Board has
    unrelated navigation/search forms in the same DOM.
    """

    try:
        result = await button.evaluate(
            """
            el => {
                const form =
                    el.form ||
                    el.closest('form');

                if (!form) {
                    return [];
                }

                return Array.from(
                    form.querySelectorAll(
                        'input:invalid, '
                        + 'textarea:invalid, '
                        + 'select:invalid'
                    )
                ).map(node => ({
                    id: node.id || '',
                    name: node.name || '',
                    type: node.type || '',
                    value: node.value || '',
                    required: !!node.required
                }));
            }
            """
        )

        return (
            result
            if isinstance(
                result,
                list,
            )
            else []
        )

    except Exception:
        return []


# ============================================================
# v0.6.11.8c — NEXT TRANSITION SETTLE
# ============================================================

async def _stage_for_next_transition(
    page,
) -> str | None:

    try:
        stage = await detect_stage(
            page
        )
    except Exception:
        return None

    return (
        stage
        if stage
        in {
            "PROFILE",
            "BASIC",
            "CUSTOM",
            "REVIEW",
        }
        else None
    )


async def _wait_for_next_transition(
    page,
    previous_stage: str | None,
    timeout_ms: int | None = None,
) -> str | None:
    """
    Get on Board can disable/re-render NEXT while an application
    step is being persisted.

    Do not immediately re-enter the same stage after a successful
    NEXT click. Poll until a different known stage is stable twice.

    This is navigation settling only. It never performs another
    click and is never used for the irreversible final submit.
    """

    if previous_stage not in {
        "PROFILE",
        "BASIC",
        "CUSTOM",
        "REVIEW",
    }:

        await page.wait_for_timeout(
            1200
        )

        return None

    if timeout_ms is None:
        try:
            timeout_ms = int(
                os.getenv(
                    "NEXT_TRANSITION_TIMEOUT_MS",
                    "20000",
                )
            )
        except Exception:
            timeout_ms = 20000

    timeout_ms = max(
        4000,
        min(int(timeout_ms), 60000),
    )

    interval_ms = 250

    attempts = max(
        1,
        int(timeout_ms)
        // interval_ms,
    )

    candidate = None
    stable = 0

    for _ in range(
        attempts
    ):

        await page.wait_for_timeout(
            interval_ms
        )

        current = await (
            _stage_for_next_transition(
                page
            )
        )

        if (
            current
            and current
            != previous_stage
        ):

            if current == candidate:
                stable += 1

            else:
                candidate = current
                stable = 1

            if stable >= 2:

                print(
                    "⏳ NEXT settle: "
                    f"{previous_stage} → {current}"
                )

                return current

        else:

            candidate = None
            stable = 0

    print(
        "⚠️ NEXT settle timeout: "
        f"stage sigue {previous_stage}; "
        "el loop lo re-evaluará "
        "conservadoramente."
    )

    return previous_stage


async def _next_form_feedback(
    button,
) -> list[str]:
    """Return visible validation/server feedback from NEXT's own form."""

    try:
        result = await button.evaluate(
            """
            el => {
                const form = el.form || el.closest('form');
                if (!form) return [];

                const selectors = [
                    '[role="alert"]',
                    '.invalid-feedback',
                    '.error',
                    '.errors',
                    '.help-block',
                    '[aria-invalid="true"]'
                ];

                const out = [];
                for (const selector of selectors) {
                    for (const node of form.querySelectorAll(selector)) {
                        const style = window.getComputedStyle(node);
                        const visible =
                            style.display !== 'none' &&
                            style.visibility !== 'hidden' &&
                            node.getClientRects().length > 0;

                        if (!visible) continue;

                        const text = (
                            node.innerText ||
                            node.textContent ||
                            node.validationMessage ||
                            ''
                        ).trim();

                        if (text && !out.includes(text)) {
                            out.push(text);
                        }
                    }
                }
                return out.slice(0, 12);
            }
            """
        )

        return (
            [str(x) for x in result if str(x).strip()]
            if isinstance(result, list)
            else []
        )

    except Exception:
        return []


async def click_next(page):

    await _fill_known_professional_profile_urls(
        page
    )

    submits = page.locator(
        "button[type='submit'],"
        "input[type='submit']"
    )

    visible = []

    for i in range(
        await submits.count()
    ):

        el = submits.nth(i)

        if not await el.is_visible():
            continue

        try:
            text = (
                await el.inner_text()
            ).strip()

        except Exception:
            text = (
                await el.get_attribute(
                    "value"
                )
                or ""
            ).strip()

        visible.append(
            (el, text)
        )

    # --------------------------------------------------------
    # NEXT / CONTINUE / REVIEW candidates
    #
    # v0.6.11.8b:
    # do NOT abort on the first disabled duplicate.
    # Prefer an enabled candidate.
    # --------------------------------------------------------

    next_candidates = [
        (el, text)
        for el, text in visible
        if _is_next_control_label(
            text
        )
    ]

    for el, text in next_candidates:

        try:
            enabled = await el.is_enabled()
        except Exception:
            enabled = False

        if not enabled:
            continue

        print(
            f"➡️ {text}"
        )

        await el.scroll_into_view_if_needed()

        previous_stage = await _stage_for_next_transition(page)

        await el.click(
            timeout=10000
        )

        settled_stage = await _wait_for_next_transition(
            page,
            previous_stage,
        )

        # A successful click is not the same as a successful transition.
        # Never immediately refill/reclick the same step while Get on Board
        # still has the form disabled/persisting.  Quarantine this job and
        # let the persistent retry lane revisit it later.
        if (
            previous_stage
            and settled_stage == previous_stage
        ):
            feedback = await _next_form_feedback(
                el
            )

            if feedback:
                print(
                    "⚠️ Feedback del formulario tras NEXT:"
                )
                for message in feedback:
                    print(
                        "   • "
                        + message[:500].replace(
                            "\n",
                            " | ",
                        )
                    )

            raise RuntimeError(
                "NEXT_TRANSITION_STALLED: "
                f"stage={previous_stage}; "
                "el click no produjo una transición estable."
            )

        return

    # --------------------------------------------------------
    # We found application NEXT controls, but every matching
    # candidate is actually disabled.
    #
    # Diagnose each candidate's OWN form only.
    # --------------------------------------------------------

    if next_candidates:

        print()
        print(
            "🛑 Todos los botones de avance "
            "detectados están deshabilitados."
        )

        all_invalid = []

        for el, text in next_candidates:

            invalid = await (
                _invalid_fields_for_button_form(
                    el
                )
            )

            for field in invalid:

                item = dict(field)

                item[
                    "_button"
                ] = text

                all_invalid.append(
                    item
                )

        if all_invalid:

            print(
                "Campos inválidos/requeridos "
                "del formulario de postulación:"
            )

            seen = set()

            for field in all_invalid:

                signature = (
                    field.get("id") or "",
                    field.get("name") or "",
                    field.get("type") or "",
                    field.get("value") or "",
                )

                if signature in seen:
                    continue

                seen.add(
                    signature
                )

                print(
                    "  • "
                    f"id={field.get('id') or '—'} "
                    f"name={field.get('name') or '—'} "
                    f"type={field.get('type') or '—'} "
                    f"value={field.get('value')!r}"
                )

        else:

            print(
                "ℹ️ El formulario asociado al botón "
                "no expone controles HTML inválidos."
            )

            print(
                "   No se culpará a formularios globales "
                "de navegación/búsqueda."
            )

        raise RuntimeError(
            "Formulario incompleto: "
            "todos los botones de avance "
            "están deshabilitados."
        )

    # --------------------------------------------------------
    # Historical conservative fallback:
    # exactly one visible submit-like control.
    # Still never use the irreversible final submit here.
    # --------------------------------------------------------

    if len(visible) == 1:

        el, text = visible[0]

        if not _is_final_application_submit(
            text
        ):

            if not await el.is_enabled():

                invalid = await (
                    _invalid_fields_for_button_form(
                        el
                    )
                )

                print()
                print(
                    "🛑 Único control de avance "
                    "visible está deshabilitado."
                )

                if invalid:

                    print(
                        "Campos inválidos/requeridos "
                        "del formulario de postulación:"
                    )

                    for field in invalid:

                        print(
                            "  • "
                            f"id={field.get('id') or '—'} "
                            f"name={field.get('name') or '—'} "
                            f"type={field.get('type') or '—'} "
                            f"value={field.get('value')!r}"
                        )

                raise RuntimeError(
                    "Formulario incompleto: "
                    "único control de avance "
                    "deshabilitado."
                )

            print(
                f"➡️ único submit: {text}"
            )

            previous_stage = await _stage_for_next_transition(page)

            await el.click(
                timeout=10000
            )

            settled_stage = await _wait_for_next_transition(
                page,
                previous_stage,
            )

            if (
                previous_stage
                and settled_stage == previous_stage
            ):
                raise RuntimeError(
                    "NEXT_TRANSITION_STALLED: "
                    f"stage={previous_stage}; "
                    "el único control no produjo transición estable."
                )

            return

    raise RuntimeError(
        "No encontré un botón seguro "
        "para avanzar."
    )


# ============================================================
# PROFILE
# ============================================================

async def generate_profile(
    job_text: str,
) -> ProfileAnswers:
    """
    Deterministic local PROFILE.

    No LLM call:
      - detects job language
      - detects role family
      - uses only verified candidate facts
    """

    profile = build_profile(
        job_text
    )

    print(
        "⚡ PROFILE determinista:"
        f" language={profile['language']}"
        f" family={profile['family']}"
        f" professional={profile['professional_chars']} chars"
        f" academic={profile['academic_chars']} chars"
    )

    return ProfileAnswers(
        language=profile["language"],
        professional=profile["professional"],
        academic=profile["academic"],
    )


async def set_trix(
    page,
    selector: str,
    text: str,
):
    """
    v0.6.11.

    Resolve the semantic PROFILE editor instead of assuming that
    Get on Board always exposes one exact hard-coded selector.
    """

    requested = str(
        selector or ""
    )

    requested_low = (
        requested.casefold()
    )

    if "professional" in requested_low:
        semantic = "professional"

    elif "academic" in requested_low:
        semantic = "academic"

    else:
        semantic = ""

    async def resolve_target():

        candidates = []

        # Exact historical selector first.
        if requested:

            try:
                exact = page.locator(
                    requested
                )

                if await exact.count():
                    candidates.append(
                        exact.first
                    )

            except Exception:
                pass

        # Discover semantic Trix editors.
        editors = page.locator(
            "trix-editor"
        )

        editor_count = (
            await editors.count()
        )

        for i in range(
            editor_count
        ):

            editor = editors.nth(i)

            try:
                meta = await editor.evaluate(
                    """
                    el => {
                        const inputId =
                            el.getAttribute('input') || '';

                        const hidden =
                            inputId
                            ? document.getElementById(inputId)
                            : null;

                        return {
                            id: el.id || '',
                            inputId: inputId,
                            hiddenId:
                                hidden
                                ? (hidden.id || '')
                                : '',
                            hiddenName:
                                hidden
                                ? (hidden.name || '')
                                : '',
                            aria:
                                el.getAttribute('aria-label') || '',
                            placeholder:
                                el.getAttribute('placeholder') || ''
                        };
                    }
                    """
                )

                blob = " ".join(
                    str(
                        meta.get(key)
                        or ""
                    )
                    for key in (
                        "id",
                        "inputId",
                        "hiddenId",
                        "hiddenName",
                        "aria",
                        "placeholder",
                    )
                ).casefold()

                if (
                    semantic
                    and semantic in blob
                ):
                    candidates.append(
                        editor
                    )

            except Exception:
                pass

        # Known GOB shape: two PROFILE Trix editors.
        # Use positional fallback only when the shape is unambiguous.
        if (
            semantic
            and editor_count == 2
        ):
            candidates.append(
                editors.nth(
                    0
                    if semantic == "professional"
                    else 1
                )
            )

        # Alternate non-Trix implementation.
        if semantic:

            alternate_selectors = (
                f'textarea[id*="{semantic}" i]',
                f'textarea[name*="{semantic}" i]',
                (
                    'input:not([type="hidden"])'
                    f'[id*="{semantic}" i]'
                ),
                (
                    'input:not([type="hidden"])'
                    f'[name*="{semantic}" i]'
                ),
                (
                    '[contenteditable="true"]'
                    f'[id*="{semantic}" i]'
                ),
                (
                    '[contenteditable="true"]'
                    f'[aria-label*="{semantic}" i]'
                ),
            )

            for css in alternate_selectors:

                try:
                    loc = page.locator(
                        css
                    )

                    if await loc.count():
                        candidates.append(
                            loc.first
                        )

                except Exception:
                    pass

        for candidate in candidates:

            try:
                if await candidate.is_visible():
                    return candidate

            except Exception:
                continue

        return None

    target = None

    # Bounded ~5 second semantic wait.
    for _ in range(20):

        target = await resolve_target()

        if target is not None:
            break

        await page.wait_for_timeout(
            250
        )

    if target is None:
        raise RuntimeError(
            "PROFILE_EDITOR_NOT_FOUND: "
            f"selector={requested!r}; "
            f"semantic={semantic or '-'}"
        )

    tag = await target.evaluate(
        "(el) => el.tagName.toLowerCase()"
    )

    if tag == "trix-editor":

        ok = await target.evaluate(
            """
            (el, text) => {
                if (!el.editor) {
                    return false;
                }

                el.editor.loadHTML("");
                el.editor.insertString(text);

                el.dispatchEvent(
                    new Event(
                        "input",
                        {bubbles: true}
                    )
                );

                el.dispatchEvent(
                    new Event(
                        "change",
                        {bubbles: true}
                    )
                );

                return true;
            }
            """,
            text,
        )

        if not ok:

            await target.click()

            await page.keyboard.press(
                "Control+A"
            )

            await page.keyboard.insert_text(
                text
            )

        actual = await target.evaluate(
            """
            el => {
                if (
                    el.editor &&
                    el.editor.getDocument
                ) {
                    return (
                        el.editor
                        .getDocument()
                        .toString()
                    );
                }

                return (
                    el.innerText ||
                    el.textContent ||
                    ''
                );
            }
            """
        )

    else:

        await target.fill(
            text
        )

        try:
            actual = (
                await target.input_value()
            )

        except Exception:
            actual = (
                await target.inner_text()
            )

    expected_norm = re.sub(
        r"\s+",
        " ",
        str(text or "").strip(),
    ).casefold()

    actual_norm = re.sub(
        r"\s+",
        " ",
        str(actual or "").strip(),
    ).casefold()

    probe = expected_norm[:80]

    if (
        not actual_norm
        or (
            probe
            and probe not in actual_norm
        )
    ):
        raise RuntimeError(
            "PROFILE_EDITOR_WRITE_NOT_PERSISTED: "
            f"{semantic or requested}"
        )

    print(
        "✅ PROFILE editor verificado: "
        f"{semantic or requested}"
    )


async def fill_profile(
    page,
    job_text: str,
):
    print("🧠 Generando experiencia/formación...")

    answers = await generate_profile(
        job_text
    )

    await set_trix(
        page,
        "#trix-professional",
        answers.professional,
    )

    await set_trix(
        page,
        "#trix-academic_background",
        answers.academic,
    )

    print(
        "✅ PROFILE completado "
        f"({answers.language.upper()})"
    )

def resolve_salary(
    decision,
    job_text: str = "",
) -> int:
    """
    Single salary source of truth.

    Priority:
    1. Published salary range.
    2. Published fixed salary.
    3. Market estimate.

    The chosen amount is synchronized back into the
    JobDecision for logs/auditing.
    """

    quote = quote_salary(
        decision,
        job_text,
    )

    try:
        decision.salary_usd_monthly = (
            quote.amount_usd_monthly
        )

        decision.salary_reason = (
            quote.reason
        )
    except Exception:
        pass

    return quote.amount_usd_monthly

async def generate_motivation(
    job_text: str,
    decision,
    language_override: str | None = None,
) -> Motivation:
    """
    Deterministic motivation.
    No LLM / no API / no Ollama.
    """

    result = build_motivation(
        job_text,
        decision,
        language_override=language_override,
    )

    print(
        "⚡ MOTIVATION determinista:"
        f" language={result['language']}"
        f" chars={result['chars']}"
    )

    return Motivation(
        language=result["language"],
        text=result["text"],
    )


async def _salary_form_status(
    page,
    salary_locator,
) -> str:
    """
    Read visible salary validation feedback.

    Returns:
      OK
      TOO_HIGH
      TOO_LOW
    """

    await page.wait_for_timeout(
        450
    )

    result = await salary_locator.evaluate(
        """el => {
            const visible = node => {
                if (!node) return false;

                const s = getComputedStyle(node);
                const r = node.getBoundingClientRect();

                return (
                    s.display !== 'none' &&
                    s.visibility !== 'hidden' &&
                    r.width > 0 &&
                    r.height > 0
                );
            };

            let root = el;

            // Search locally first.
            for (
                let i = 0;
                i < 5 && root.parentElement;
                i++
            ) {
                root = root.parentElement;
            }

            const texts = [];

            for (
                const node of root.querySelectorAll('*')
            ) {
                if (!visible(node)) {
                    continue;
                }

                const text = (
                    node.innerText ||
                    node.textContent ||
                    ''
                ).trim();

                if (text) {
                    texts.push(text);
                }
            }

            return texts.join('\\n');
        }"""
    )

    low = str(
        result or ""
    ).casefold()

    too_high_terms = (
        "excede el rango de sueldo",
        "excede el rango salarial",
        "supera el rango de sueldo",
        "supera el rango salarial",
        "exceeds the salary range",
        "above the salary range",
        "higher than the salary range",
    )

    too_low_terms = (
        "por debajo del rango de sueldo",
        "por debajo del rango salarial",
        "below the salary range",
        "lower than the salary range",
    )

    if any(
        term in low
        for term in too_high_terms
    ):
        return "TOO_HIGH"

    if any(
        term in low
        for term in too_low_terms
    ):
        return "TOO_LOW"

    return "OK"


async def _fit_salary_to_form(
    page,
    salary_locator,
    desired: int,
) -> int:
    """
    Use Get on Board's own visible salary validation as
    the final authority when the employer range is hidden.

    We search in USD 50 increments and choose the highest
    salary that the form accepts.

    This never submits the application.
    """

    desired = int(
        round(
            desired / 50
        ) * 50
    )

    desired = max(
        1000,
        desired,
    )

    # --------------------------------------------------------
    # Get on Board can expose the hidden employer ceiling
    # directly in data-max-salary.
    # --------------------------------------------------------

    raw_max = await salary_locator.get_attribute(
        "data-max-salary"
    )

    raw_step = await salary_locator.get_attribute(
        "step"
    )

    try:
        form_max = float(
            raw_max
        )
    except Exception:
        form_max = None

    try:
        form_step = int(
            float(
                raw_step
                or 50
            )
        )
    except Exception:
        form_step = 50

    if (
        form_max is not None
        and form_max > 0
        and desired > form_max
    ):

        ceiling = int(
            form_max
            // form_step
            * form_step
        )

        ceiling = max(
            form_step,
            ceiling,
        )

        print(
            "💰 Rango GOB detectado en DOM: "
            f"max={form_max:g}, "
            f"step={form_step}"
        )

        desired = ceiling

    async def probe(
        value: int,
    ) -> str:

        await salary_locator.fill(
            str(value)
        )

        # Blur to trigger any validation that depends
        # on change/focusout.
        await salary_locator.press(
            "Tab"
        )

        status = await _salary_form_status(
            page,
            salary_locator,
        )

        print(
            f"💰 Salary probe: "
            f"{value} USD → {status}"
        )

        return status

    initial = await probe(
        desired
    )

    if initial == "OK":
        return desired

    # --------------------------------------------------------
    # DESIRED ABOVE EMPLOYER RANGE
    # --------------------------------------------------------

    if initial == "TOO_HIGH":

        low = 1000
        high = desired - 50

        best = None

        # Binary search in $50 increments.
        while low <= high:

            mid = (
                (
                    (
                        low + high
                    )
                    // 2
                )
                // 50
                * 50
            )

            status = await probe(
                mid
            )

            if status == "TOO_HIGH":
                high = mid - 50

            elif status == "TOO_LOW":
                low = mid + 50

            else:
                best = mid
                low = mid + 50

        if best is None:
            raise RuntimeError(
                "No pude encontrar una renta dentro "
                "del rango aceptado por Get on Board."
            )

        # Restore final accepted value.
        await salary_locator.fill(
            str(best)
        )

        await salary_locator.press(
            "Tab"
        )

        print(
            "🛡️ Salary form guardrail PASS: "
            f"{best} USD"
        )

        return best

    # --------------------------------------------------------
    # DESIRED BELOW EMPLOYER RANGE
    # --------------------------------------------------------

    if initial == "TOO_LOW":

        low = desired + 50
        high = 10000

        best = None

        while low <= high:

            mid = (
                (
                    (
                        low + high
                    )
                    // 2
                )
                // 50
                * 50
            )

            status = await probe(
                mid
            )

            if status == "TOO_LOW":
                low = mid + 50

            elif status == "TOO_HIGH":
                high = mid - 50

            else:
                # First accepted value is enough when our
                # market estimate was below the band.
                best = mid
                high = mid - 50

        if best is None:
            raise RuntimeError(
                "No pude encontrar una renta dentro "
                "del rango aceptado por Get on Board."
            )

        await salary_locator.fill(
            str(best)
        )

        await salary_locator.press(
            "Tab"
        )

        print(
            "🛡️ Salary form guardrail PASS: "
            f"{best} USD"
        )

        return best

    return desired


async def _motivation_language_requirement(
    page,
) -> str | None:
    """
    The form's explicit language requirement overrides
    job-description language detection.
    """

    body = (
        await page.locator(
            "body"
        ).inner_text()
    ).casefold()

    english_markers = (
        "debe estar escrita en inglés",
        "debe estar escrita en ingles",
        "debe estar escrito en inglés",
        "debe estar escrito en ingles",
        "must be written in english",
        "write your reason in english",
    )

    spanish_markers = (
        "debe estar escrita en español",
        "debe estar escrita en espanol",
        "must be written in spanish",
    )

    if any(
        marker in body
        for marker in english_markers
    ):
        return "en"

    if any(
        marker in body
        for marker in spanish_markers
    ):
        return "es"

    return None


async def fill_basic(
    page,
    job_text: str,
    decision,
):
    print(
        f"📄 CV: {decision.cv_id}"
    )

    salary_usd = resolve_salary(decision, job_text)

    print(
        f"💰 Renta: "
        f"{salary_usd} USD"
    )

    # CV
    cv_result = await select_cv(
        page,
        decision.cv_id,
    )

    print(
        "✅ CV seleccionado: "
        + cv_result["filename"]
    )

    await assert_cv_selected(
        page,
        decision.cv_id,
    )

    print(
        "🛡️ CV guardrail PASS"
    )

    # Salary
    salary = page.locator(
        "#job_application_expected_salary"
    )

    if await salary.count():

        salary_usd = await _fit_salary_to_form(
            page,
            salary,
            salary_usd,
        )

        # Synchronize the final form-approved value.
        try:
            decision.salary_usd_monthly = (
                salary_usd
            )

            previous_reason = str(
                getattr(
                    decision,
                    "salary_reason",
                    "",
                )
                or ""
            )

            decision.salary_reason = (
                previous_reason
                + (
                    " | Ajustado por validación "
                    "del rango de Get on Board."
                )
            ).strip(" |")

        except Exception:
            pass

        print(
            f"✅ Renta rellenada: "
            f"{salary_usd} USD"
        )

    # Motivation
    reason = page.locator(
        "#reason-to-apply"
    )

    if await reason.count():

        constraints = getattr(
            decision,
            "form_constraints",
            {},
        ) or {}

        if not isinstance(
            constraints,
            dict,
        ):
            constraints = {}

        learned_language = str(
            constraints.get(
                "motivation_language",
                "",
            )
            or ""
        ).casefold()

        visible_language = (
            await _motivation_language_requirement(
                page
            )
        )

        language_override = (
            learned_language
            if learned_language
            in {
                "es",
                "en",
            }
            else visible_language
        )

        if language_override:

            source = (
                "restricción aprendida"
                if learned_language
                in {
                    "es",
                    "en",
                }
                else "formulario visible"
            )

            print(
                "🌐 Idioma de motivación: "
                f"{language_override.upper()} "
                f"({source})"
            )

        motivation = (
            await generate_motivation(
                job_text,
                decision,
                language_override=language_override,
            )
        )

        text_value = str(
            motivation.text
            or ""
        ).strip()

        min_attr = (
            await reason.get_attribute(
                "minlength"
            )
        )

        max_attr = (
            await reason.get_attribute(
                "maxlength"
            )
        )

        learned_min = constraints.get(
            "motivation_min_chars"
        )

        learned_max = constraints.get(
            "motivation_max_chars"
        )

        try:
            min_chars = int(
                learned_min
                if learned_min is not None
                else (
                    min_attr
                    or 50
                )
            )
        except Exception:
            min_chars = 50

        try:
            max_chars = int(
                learned_max
                if learned_max is not None
                else (
                    max_attr
                    or 1000
                )
            )
        except Exception:
            max_chars = 1000

        if len(text_value) < min_chars:
            raise RuntimeError(
                "Motivación demasiado corta: "
                f"{len(text_value)} < {min_chars}"
            )

        if len(text_value) > max_chars:
            raise RuntimeError(
                "Motivación demasiado larga: "
                f"{len(text_value)} > {max_chars}"
            )

        await reason.fill(
            text_value
        )

        print(
            "✅ Motivación rellenada: "
            f"{len(text_value)} chars "
            f"({motivation.language.upper()})"
        )

    # Residency
    residency = page.locator(
        "#confirm_residency"
    )

    if await residency.count():
        if not await residency.is_checked():
            await residency.check()

        print(
            "✅ Residencia confirmada"
        )

    # Final CV guardrail.
    await assert_cv_selected(
        page,
        decision.cv_id,
    )


# ============================================================
# CUSTOM QUESTIONS
# ============================================================

async def extract_custom_fields(
    page,
) -> list[dict]:
    """
    v0.6.11.1 CUSTOM extractor.

    Besides the input itself, inspect the local question wrapper.
    Get on Board frequently represents required checkbox/radio
    groups on the question heading instead of each individual input.
    """

    raw = await page.locator(
        """
        input:not([type='hidden']),
        textarea,
        select,
        trix-editor,
        [role='textbox']
        """
    ).evaluate_all(
        """
        els => els
        .filter(el => {

            const s =
                window.getComputedStyle(el);

            const r =
                el.getBoundingClientRect();

            if (
                s.display === 'none' ||
                s.visibility === 'hidden' ||
                r.width <= 0 ||
                r.height <= 0
            ) {
                return false;
            }

            const ignored = new Set([
                'job_application_expected_salary',
                'reason-to-apply',
                'confirm_residency',
                'trix-professional',
                'trix-academic_background'
            ]);

            if (ignored.has(el.id)) {
                return false;
            }

            if (
                el.classList.contains(
                    'chosen-search-input'
                )
            ) {
                return false;
            }

            const form =
                el.closest('form');

            if (!form) {
                return false;
            }

            const action = (
                form.getAttribute('action')
                || ''
            ).toLowerCase();

            const applicationNamedControl =
                Array.from(
                    form.querySelectorAll(
                        '[name], [id]'
                    )
                ).some(node => {

                    const name = (
                        node.getAttribute('name')
                        || ''
                    ).toLowerCase();

                    const id = (
                        node.id || ''
                    ).toLowerCase();

                    return (
                        name.startsWith(
                            'job_application['
                        )
                        ||
                        id.startsWith(
                            'job_application_'
                        )
                        ||
                        id === 'reason-to-apply'
                        ||
                        id === 'trix-professional'
                        ||
                        id ===
                            'trix-academic_background'
                    );
                });

            return (
                action.includes(
                    '/applications'
                )
                ||
                action.includes(
                    'job_application'
                )
                ||
                applicationNamedControl
            );
        })
        .map((el, index) => {

            const form =
                el.closest('form');

            let label = '';

            if (
                el.labels &&
                el.labels.length
            ) {
                label = Array.from(
                    el.labels
                ).map(
                    x => (
                        x.innerText ||
                        x.textContent ||
                        ''
                    ).trim()
                ).join(' ');
            }

            if (!label && el.id) {

                const lab =
                    document.querySelector(
                        `label[for="${
                            CSS.escape(el.id)
                        }"]`
                    );

                if (lab) {
                    label = (
                        lab.innerText ||
                        lab.textContent ||
                        ''
                    ).trim();
                }
            }

            if (!label) {

                label = (
                    el.getAttribute(
                        'aria-label'
                    )
                    ||
                    el.getAttribute(
                        'placeholder'
                    )
                    ||
                    ''
                ).trim();
            }

            if (!label) {

                let p =
                    el.parentElement;

                for (
                    let depth = 0;
                    depth < 4
                    && p
                    && p !== form;
                    depth++,
                    p = p.parentElement
                ) {

                    const txt = (
                        p.innerText ||
                        p.textContent ||
                        ''
                    ).trim();

                    if (
                        txt
                        && txt.length <= 500
                    ) {
                        label = txt;
                        break;
                    }
                }
            }

            // -----------------------------------------------
            // Recover surrounding question context.
            // -----------------------------------------------

            let contextLabel = '';

            let cp =
                el.parentElement;

            const ownLabel =
                (label || '').trim();

            for (
                let depth = 0;
                depth < 6
                && cp
                && cp !== form;
                depth++,
                cp = cp.parentElement
            ) {

                const txt = (
                    cp.innerText ||
                    cp.textContent ||
                    ''
                ).trim();

                if (
                    txt
                    && txt.length <= 900
                    && txt !== ownLabel
                ) {
                    contextLabel = txt;
                    break;
                }
            }

            // -----------------------------------------------
            // REQUIRED GROUP DETECTION
            // -----------------------------------------------

            let requiredHint = (
                !!el.required
                ||
                (
                    el.getAttribute(
                        'aria-required'
                    ) || ''
                ).toLowerCase()
                === 'true'
            );

            const requiredSources = [];

            if (el.required) {
                requiredSources.push(
                    'input.required'
                );
            }

            if (
                (
                    el.getAttribute(
                        'aria-required'
                    ) || ''
                ).toLowerCase()
                === 'true'
            ) {
                requiredSources.push(
                    'input.aria-required'
                );
            }

            let rp =
                el.parentElement;

            for (
                let depth = 0;
                depth < 6
                && rp
                && rp !== form;
                depth++,
                rp = rp.parentElement
            ) {

                const ariaRequired = (
                    rp.getAttribute(
                        'aria-required'
                    ) || ''
                ).toLowerCase();

                const dataRequired = (
                    rp.getAttribute(
                        'data-required'
                    ) || ''
                ).toLowerCase();

                const className = (
                    typeof rp.className
                    === 'string'
                    ? rp.className
                    : ''
                ).toLowerCase();

                const txt = (
                    rp.innerText ||
                    rp.textContent ||
                    ''
                )
                .replace(
                    /\\s+/g,
                    ' '
                )
                .trim();

                let before = '';
                let after = '';

                try {
                    before = (
                        getComputedStyle(
                            rp,
                            '::before'
                        ).content || ''
                    );

                    after = (
                        getComputedStyle(
                            rp,
                            '::after'
                        ).content || ''
                    );
                }
                catch (_) {
                }

                const localMarker = (
                    ariaRequired === 'true'
                    ||
                    dataRequired === 'true'
                    ||
                    (
                        className.includes(
                            'required'
                        )
                        &&
                        txt.length <= 1200
                    )
                    ||
                    (
                        txt.length <= 1200
                        &&
                        txt.includes('*')
                    )
                    ||
                    before.includes('*')
                    ||
                    after.includes('*')
                );

                if (localMarker) {

                    requiredHint = true;

                    requiredSources.push(
                        `ancestor:${depth}`
                    );

                    break;
                }

                // Some GOB headings render their asterisk on
                // a child/span/pseudo-element.
                if (txt.length <= 1200) {

                    const children =
                        rp.querySelectorAll(
                            'label, legend, h1, h2, h3, h4, '
                            + 'p, span, strong, abbr'
                        );

                    for (
                        const child
                        of children
                    ) {

                        const childText = (
                            child.innerText ||
                            child.textContent ||
                            ''
                        ).trim();

                        let childBefore = '';
                        let childAfter = '';

                        try {

                            childBefore = (
                                getComputedStyle(
                                    child,
                                    '::before'
                                ).content || ''
                            );

                            childAfter = (
                                getComputedStyle(
                                    child,
                                    '::after'
                                ).content || ''
                            );
                        }
                        catch (_) {
                        }

                        if (
                            childText.includes('*')
                            ||
                            childBefore.includes('*')
                            ||
                            childAfter.includes('*')
                            ||
                            (
                                (
                                    typeof child.className
                                    === 'string'
                                    ? child.className
                                    : ''
                                )
                                .toLowerCase()
                                .includes('required')
                            )
                        ) {

                            requiredHint = true;

                            requiredSources.push(
                                `child:${depth}`
                            );

                            break;
                        }
                    }
                }

                if (requiredHint) {
                    break;
                }
            }

            return {
                index,

                tag:
                    el.tagName.toLowerCase(),

                type:
                    el.getAttribute(
                        'type'
                    ) || '',

                id:
                    el.id || '',

                name:
                    el.getAttribute(
                        'name'
                    ) || '',

                value:
                    el.value || '',

                checked:
                    !!el.checked,

                required:
                    !!el.required,

                requiredHint:
                    !!requiredHint,

                requiredSource:
                    requiredSources.join(','),

                label:
                    label.slice(
                        0,
                        500
                    ),

                contextLabel:
                    contextLabel.slice(
                        0,
                        900
                    ),

                options:
                    el.tagName === 'SELECT'
                    ? Array.from(
                        el.options
                    ).map(
                        option => ({
                            text:
                                (
                                    option.textContent
                                    || ''
                                ).trim(),

                            value:
                                option.value
                        })
                    )
                    : []
            };
        })
        """
    )

    def plausible_label(
        value: str,
    ) -> bool:

        low = _norm_custom(
            value
        )

        if not low:
            return True

        junk_exact = {
            "ayuda",
            "help",
            "buscar",
            "search",
            "bastian campusano",
            "bastian campusano sanhueza",
        }

        if low in junk_exact:
            return False

        if (
            low.startswith("ayuda ")
            and "bastian campusano"
            in low
        ):
            return False

        return True

    groups: dict[str, dict] = {}
    normal = []

    for field in raw:

        if field["type"] in {
            "radio",
            "checkbox",
        }:

            key = (
                field["name"]
                or field["id"]
                or f"field_{field['index']}"
            )

            if key not in groups:

                groups[key] = {
                    "field_key": key,
                    "kind": field["type"],
                    "name": field["name"],
                    "id": field["id"],
                    "label": field["label"],
                    "required": bool(
                        field["required"]
                        or field.get(
                            "requiredHint"
                        )
                    ),
                    "required_hint": bool(
                        field.get(
                            "requiredHint"
                        )
                    ),
                    "required_sources": [],
                    "options": [],
                    "contexts": [],
                }

            if field.get(
                "contextLabel"
            ):

                groups[key][
                    "contexts"
                ].append(
                    field[
                        "contextLabel"
                    ]
                )

            groups[key][
                "required"
            ] = bool(
                groups[key].get(
                    "required"
                )
                or field.get(
                    "required"
                )
                or field.get(
                    "requiredHint"
                )
            )

            groups[key][
                "required_hint"
            ] = bool(
                groups[key].get(
                    "required_hint"
                )
                or field.get(
                    "requiredHint"
                )
            )

            if field.get(
                "requiredSource"
            ):

                groups[key][
                    "required_sources"
                ].append(
                    field[
                        "requiredSource"
                    ]
                )

            groups[key][
                "options"
            ].append({
                "id":
                    field["id"],

                "value":
                    field["value"],

                "label":
                    field["label"],
            })

            continue

        if not plausible_label(
            field.get(
                "label"
            ) or ""
        ):
            continue

        key = (
            field["id"]
            or field["name"]
            or f"field_{field['index']}"
        )

        normal.append({
            "field_key": key,

            "kind":
                (
                    "select"
                    if field["tag"]
                    == "select"
                    else "text"
                ),

            "tag":
                field["tag"],

            "id":
                field["id"],

            "name":
                field["name"],

            "label":
                field["label"],

            "required":
                bool(
                    field["required"]
                    or field.get(
                        "requiredHint"
                    )
                ),

            "required_hint":
                bool(
                    field.get(
                        "requiredHint"
                    )
                ),

            "required_sources":
                [
                    field[
                        "requiredSource"
                    ]
                ]
                if field.get(
                    "requiredSource"
                )
                else [],

            "options":
                field["options"],
        })

    grouped = []

    for group in groups.values():

        option_labels = [
            str(
                option.get(
                    "label"
                )
                or option.get(
                    "value"
                )
                or ""
            )
            for option
            in group.get(
                "options"
            ) or []
        ]

        current_label = str(
            group.get(
                "label"
            )
            or ""
        ).strip()

        current_norm = (
            _norm_custom(
                current_label
            )
        )

        option_norms = {
            _norm_custom(value)
            for value in option_labels
            if _norm_custom(
                value
            )
        }

        if (
            not current_label
            or current_norm
            in option_norms
        ):

            recovered = (
                recover_group_question(
                    option_labels,
                    list(
                        group.get(
                            "contexts"
                        )
                        or []
                    ),
                )
            )

            if recovered:
                group[
                    "label"
                ] = recovered

        group.pop(
            "contexts",
            None,
        )

        if plausible_label(
            group.get(
                "label"
            ) or ""
        ):

            grouped.append(
                group
            )

    return normal + grouped



def _norm_custom(value) -> str:
    return re.sub(
        r"\s+",
        " ",
        str(value or "").strip(),
    ).casefold()


def _custom_options(field: dict) -> list[tuple[str, str]]:
    out = []

    for option in field.get("options") or []:
        if isinstance(option, dict):
            label = str(
                option.get("label") or ""
            ).strip()

            value = str(
                option.get("value") or ""
            ).strip()
        else:
            label = str(option).strip()
            value = str(option).strip()

        if label or value:
            out.append(
                (label, value)
            )

    return out


def _exact_visible_option(
    field: dict,
    candidate: str,
) -> str | None:

    target = _norm_custom(candidate)

    if not target:
        return None

    for label, value in _custom_options(field):

        if (
            label
            and _norm_custom(label) == target
        ):
            return label

        if (
            value
            and _norm_custom(value) == target
        ):
            return value

    return None


def _effective_custom_salary(
    decision,
    job_text: str,
) -> tuple[int, bool]:
    """
    Preserve a salary already validated against Get on Board.

    Once the form has adjusted the amount to the employer's
    hidden range, that value has priority for the remainder
    of this application.
    """

    reason = str(
        getattr(
            decision,
            "salary_reason",
            "",
        )
        or ""
    ).casefold()

    adjusted = (
        "ajustado por validación"
        in reason
        and "get on board"
        in reason
    )

    if adjusted:
        current = getattr(
            decision,
            "salary_usd_monthly",
            None,
        )

        try:
            current = int(current)
        except Exception:
            current = 0

        if current > 0:
            return current, True

    return (
        int(
            resolve_salary(
                decision,
                job_text,
            )
        ),
        False,
    )


def _custom_salary_answer_text(
    decision,
    job_text: str,
    language: str = "es",
) -> str:

    salary, adjusted = (
        _effective_custom_salary(
            decision,
            job_text,
        )
    )

    if adjusted:
        formatted = f"{salary:,}"

        if language == "en":
            return (
                f"USD {formatted} monthly, "
                "negotiable depending on scope, "
                "responsibilities and benefits."
            )

        return (
            f"USD {formatted} mensuales, "
            "conversable según alcance, "
            "responsabilidades y beneficios."
        )

    return salary_answer_text(
        decision,
        job_text,
        language=language,
    )


def _extract_secret_phrase(
    job_text: str,
) -> str | None:
    """
    v0.6.11.6a SECRET PHRASE FAIL-CLOSED.

    Extract only a phrase explicitly presented as the secret
    phrase/word in the job posting.

    Negative statements such as:
        "No explicit secret phrase is stated here"
    must never produce a value.
    """

    text = str(
        job_text
        or ""
    )

    # --------------------------------------------------
    # Patterns with quoted values have strongest evidence.
    # --------------------------------------------------

    quoted_patterns = (
        (
            r'(?i)\bsecret\s+phrase\s*'
            r'(?:is\s*)?(?::|-|=)?\s*'
            r'["“‘\']([^"”’\'\n]{2,80})["”’\']'
        ),
        (
            r'(?i)\bsecret\s+word\s*'
            r'(?:is\s*)?(?::|-|=)?\s*'
            r'["“‘\']([^"”’\'\n]{2,80})["”’\']'
        ),
        (
            r'(?i)\bfrase\s+secreta\s*'
            r'(?:es\s*)?(?::|-|=)?\s*'
            r'["“‘\']([^"”’\'\n]{2,80})["”’\']'
        ),
        (
            r'(?i)\bpalabra\s+secreta\s*'
            r'(?:es\s*)?(?::|-|=)?\s*'
            r'["“‘\']([^"”’\'\n]{2,80})["”’\']'
        ),
    )

    # --------------------------------------------------
    # Unquoted values are accepted only after an explicit
    # delimiter and are deliberately limited to a short
    # phrase.
    # --------------------------------------------------

    token = r'[\wÀ-ÿ-]+'

    unquoted_patterns = (
        (
            rf'(?i)\bsecret\s+phrase\s*'
            rf'(?:is\s+|:\s*|-\s*|=\s*)'
            rf'({token}(?:\s+{token}){{0,5}})'
        ),
        (
            rf'(?i)\bsecret\s+word\s*'
            rf'(?:is\s+|:\s*|-\s*|=\s*)'
            rf'({token}(?:\s+{token}){{0,5}})'
        ),
        (
            rf'(?i)\bfrase\s+secreta\s*'
            rf'(?:es\s+|:\s*|-\s*|=\s*)'
            rf'({token}(?:\s+{token}){{0,5}})'
        ),
        (
            rf'(?i)\bpalabra\s+secreta\s*'
            rf'(?:es\s+|:\s*|-\s*|=\s*)'
            rf'({token}(?:\s+{token}){{0,5}})'
        ),
    )

    negative_context_markers = (
        "no explicit",
        "there is no",
        "there's no",
        "no secret",
        "not stated",
        "not provided",
        "not included",
        "not mentioned",
        "no hay",
        "no existe",
        "sin frase secreta",
        "sin palabra secreta",
    )

    invalid_value_prefixes = (
        "stated",
        "provided",
        "included",
        "mentioned",
        "shown",
        "found",
        "located",
        "required",
        "available",
        "not ",
        "none",
        "n a",
        "in the ",
        "in this ",
        "here",
    )

    def valid_match(
        match,
    ) -> str | None:

        value = " ".join(
            match.group(1).split()
        ).strip(
            ' "\'“”‘’'
        )

        if not (
            2 <= len(value) <= 80
        ):
            return None

        low_value = (
            value.casefold()
        )

        # Inspect text immediately preceding the expression.
        context_start = max(
            0,
            match.start() - 80,
        )

        context = (
            text[
                context_start:
                match.start()
            ]
            .casefold()
        )

        if any(
            marker in context
            for marker in negative_context_markers
        ):
            return None

        if any(
            low_value.startswith(prefix)
            for prefix in invalid_value_prefixes
        ):
            return None

        if (
            "hint" in low_value
            or "secret phrase" in low_value
            or "secret word" in low_value
            or "frase secreta" in low_value
            or "palabra secreta" in low_value
        ):
            return None

        return value

    # Quoted evidence first.
    for pattern in quoted_patterns:

        for match in re.finditer(
            pattern,
            text,
        ):
            value = valid_match(
                match
            )

            if value:
                return value

    # Then conservative unquoted extraction.
    for pattern in unquoted_patterns:

        for match in re.finditer(
            pattern,
            text,
        ):
            value = valid_match(
                match
            )

            if value:
                return value

    return None




def _hypothetical_scope_answer(
    field: dict,
) -> str | None:
    """
    Answer design/scoping scenarios without turning them into
    autobiographical claims.
    """

    if str(
        field.get("kind")
        or ""
    ) != "text":
        return None

    label = _norm_custom(
        field.get("label")
        or ""
    )

    hypothetical_markers = (
        "imagine a client",
        "client says",
        "before writing any code",
        "before you write any code",
        "how would you scope",
        "what would you ask the client",
        "how would you phase",
        "how would you approach",
        "what would your approach be",
        "imagina que un cliente",
        "antes de escribir codigo",
        "antes de escribir código",
        "como abordarias",
        "cómo abordarías",
        "como lo abordarias",
        "cómo lo abordarías",
        "como definirias el alcance",
        "cómo definirías el alcance",
    )

    if not any(
        marker in label
        for marker in hypothetical_markers
    ):
        return None

    # Explicitly avoid past-experience prompts.
    autobiographical = (
        "walk me through a project where you",
        "tell me about a project where you",
        "describe a project where you",
        "cuentame de un proyecto donde",
        "cuéntame de un proyecto donde",
        "describe un proyecto donde hayas",
    )

    if any(
        marker in label
        for marker in autobiographical
    ):
        return None

    english = any(
        marker in label
        for marker in (
            "imagine a client",
            "client says",
            "before writing",
            "before you write",
            "how would",
            "what would",
        )
    )

    if english:
        return (
            "I would start by defining the business outcome and the "
            "boundaries before choosing technology: lead sources, expected "
            "volume, operating hours, qualification criteria, appointment "
            "rules, time zones, calendar/CRM integrations, privacy constraints "
            "and the situations that require human escalation. I would also "
            "clarify what a successful conversation and a qualified lead mean. "
            "Then I would ship the solution in small stages: first reliable "
            "lead ingestion and logging, then qualification with observable "
            "decision rules, then calendar booking, and finally automated "
            "follow-up and optimization. Each stage would include test cases, "
            "retry/idempotency behavior for external APIs, audit logs, metrics "
            "and a human fallback. I would validate the workflow with real "
            "examples before increasing autonomy, so failures are visible and "
            "reversible rather than silently losing or misclassifying leads."
        )

    return (
        "Primero definiría el objetivo de negocio y los límites antes de "
        "elegir tecnología: origen y volumen de leads, horario, criterios "
        "de calificación, reglas de agenda, zonas horarias, integraciones "
        "con calendario/CRM, privacidad y casos que requieren intervención "
        "humana. También definiría qué significa exactamente un lead "
        "calificado y una conversación exitosa. Luego entregaría por etapas: "
        "primero captura confiable y trazabilidad, después calificación con "
        "reglas observables, luego reserva de citas y finalmente seguimiento "
        "y optimización. Cada etapa tendría pruebas, manejo de reintentos e "
        "idempotencia para APIs externas, logs, métricas y fallback humano. "
        "Validaría el flujo con casos reales antes de aumentar la autonomía, "
        "de modo que los errores sean visibles y reversibles."
    )


def _liquid_salary_without_currency(
    field: dict,
) -> bool:
    """
    Net/liquid salary semantics are unsafe when the requested
    currency is not explicit.
    """

    if str(
        field.get("kind")
        or ""
    ) != "text":
        return False

    blob = _norm_custom(
        " ".join(
            [
                str(
                    field.get("label")
                    or ""
                ),
                str(
                    field.get("name")
                    or ""
                ),
                str(
                    field.get("id")
                    or ""
                ),
            ]
        )
    )

    liquid_terms = (
        "liquida",
        "líquida",
        "liquido",
        "líquido",
        "net salary",
        "net monthly",
        "take home",
        "take-home",
    )

    currency_terms = (
        "clp",
        "peso chileno",
        "pesos chilenos",
        "usd",
        "dolar",
        "dólar",
        "dolares",
        "dólares",
        "us dollar",
        "us dollars",
    )

    asks_liquid = any(
        term in blob
        for term in liquid_terms
    )

    explicit_currency = any(
        term in blob
        for term in currency_terms
    )

    return (
        asks_liquid
        and not explicit_currency
    )


def _deterministic_custom_answer(
    field: dict,
    decision,
    job_text: str,
) -> CustomAnswer | None:

    key = str(
        field.get("field_key") or ""
    )

    label = str(
        field.get("label") or ""
    )

    blob = _norm_custom(
        " ".join(
            [
                key,
                label,
                field.get("name") or "",
                field.get("id") or "",
            ]
        )
    )

    kind = field.get("kind")


    # --------------------------------------------------------
    # v0.6.11.8a — PROFESSIONAL PROFILE URL
    # --------------------------------------------------------

    if kind == "text":

        known_profile_url = (
            _known_profile_url_for_field(
                blob
            )
        )

        if known_profile_url:
            return CustomAnswer(
                field_key=key,
                text=known_profile_url,
                selected=[],
                checked=None,
                requires_human=False,
                reason="",
            )

    # --------------------------------------------------------
    # v0.6.11.6 — LIQUID/NET SALARY WITHOUT CURRENCY
    # --------------------------------------------------------

    if _liquid_salary_without_currency(
        field
    ):
        return CustomAnswer(
            field_key=key,
            text=None,
            selected=[],
            checked=None,
            requires_human=True,
            reason=(
                "La pregunta solicita renta/sueldo líquido "
                "pero no especifica moneda. No es seguro "
                "asumir USD o CLP."
            ),
        )

    # --------------------------------------------------------
    # v0.6.11.6 — SECRET PHRASE
    # --------------------------------------------------------

    if (
        kind == "text"
        and any(
            token in blob
            for token in (
                "secret phrase",
                "secret word",
                "frase secreta",
                "palabra secreta",
            )
        )
    ):

        secret = _extract_secret_phrase(
            job_text
        )

        if secret:
            return CustomAnswer(
                field_key=key,
                text=secret,
                selected=[],
                checked=None,
                requires_human=False,
                reason="",
            )

        return CustomAnswer(
            field_key=key,
            text=None,
            selected=[],
            checked=None,
            requires_human=True,
            reason=(
                "La oferta solicita una frase secreta, "
                "pero no pudo extraerse literalmente del "
                "job posting con evidencia suficiente."
            ),
        )

    # --------------------------------------------------------
    # v0.6.11.6 — HYPOTHETICAL / DESIGN SCENARIO
    # --------------------------------------------------------

    hypothetical = (
        _hypothetical_scope_answer(
            field
        )
    )

    if hypothetical:
        return CustomAnswer(
            field_key=key,
            text=hypothetical,
            selected=[],
            checked=None,
            requires_human=False,
            reason="",
        )

    # --------------------------------------------------------
    # v0.6.11.5 — COMPOSITE JOIN AVAILABILITY + SALARY
    # --------------------------------------------------------

    if kind == "text":

        join_terms = (
            "disponibilidad para unirte",
            "disponibilidad para incorporarte",
            "fecha de incorporacion",
            "fecha de incorporación",
            "fecha de inicio",
            "cuando puedes comenzar",
            "cuándo puedes comenzar",
            "join our team",
            "available to start",
            "when can you start",
            "start date",
        )

        salary_terms = (
            "expectativa salarial",
            "expectativas salariales",
            "pretension salarial",
            "pretensión salarial",
            "pretensiones de renta",
            "renta esperada",
            "salary expectation",
            "salary expectations",
            "compensation expectation",
        )

        asks_join = any(
            term in blob
            for term in join_terms
        )

        asks_salary = any(
            term in blob
            for term in salary_terms
        )

        if (
            asks_join
            and asks_salary
        ):

            spanish = any(
                term in blob
                for term in (
                    "disponibilidad",
                    "unirte",
                    "incorporarte",
                    "expectativa salarial",
                    "pretension",
                    "pretensión",
                    "renta",
                )
            )

            english = (
                not spanish
                and any(
                    term in blob
                    for term in (
                        "join our team",
                        "available to start",
                        "when can you start",
                        "start date",
                        "salary",
                        "compensation",
                    )
                )
            )

            salary_text = (
                _custom_salary_answer_text(
                    decision,
                    job_text,
                    language=(
                        "en"
                        if english
                        else "es"
                    ),
                )
            )

            return CustomAnswer(
                field_key=key,
                text=(
                    (
                        "Immediate if required. "
                        "My salary expectation is "
                        f"{salary_text}"
                    )
                    if english
                    else (
                        "Disponibilidad inmediata si es requerido. "
                        "Mi expectativa salarial es "
                        f"{salary_text}"
                    )
                ),
                selected=[],
                checked=None,
                requires_human=False,
                reason="",
            )

        # ----------------------------------------------------
        # v0.6.11.5 — SPECIFIC TECH/PROJECT/DURATION GUARD
        #
        # A question requesting several technologies plus
        # project/time detail must not be answered with a
        # generic 5+ year career summary.
        # ----------------------------------------------------

        tech_tokens = (
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
            "azure",
            "gcp",
            "sql",
        )

        tech_hits = sum(
            token in blob
            for token in tech_tokens
        )

        evidence_depth_terms = (
            "tiempo",
            "anos",
            "años",
            "proyecto",
            "proyectos",
            "duration",
            "how long",
            "years",
            "project",
            "projects",
        )

        experience_terms = (
            "experiencia",
            "experience",
            "trabajando con",
            "working with",
        )

        if (
            tech_hits >= 2
            and any(
                term in blob
                for term in evidence_depth_terms
            )
            and any(
                term in blob
                for term in experience_terms
            )
        ):
            return CustomAnswer(
                field_key=key,
                text=None,
                selected=[],
                checked=None,
                requires_human=True,
                reason=(
                    "La pregunta exige evidencia específica "
                    "por tecnología/proyecto/duración y no "
                    "puede responderse con la experiencia "
                    "profesional general."
                ),
            )

    # --------------------------------------------------------
    # KNOWN FACTS / GENERAL DETERMINISTIC CUSTOM POLICY
    # --------------------------------------------------------

    # --------------------------------------------------------
    # v0.6.11.8 — SPANISH LANGUAGE TRUTH
    #
    # CandidateTruth: Spanish is native. This answers only
    # direct language-level/proficiency questions and does
    # not infer experience, certification or years.
    # --------------------------------------------------------

    if (
        kind == "text"
        and (
            "espanol" in blob
            or "español" in blob
            or "spanish" in blob
        )
        and any(
            term in blob
            for term in (
                "nivel",
                "level",
                "proficiency",
                "dominio",
                "tecnico",
                "técnico",
                "conversacional",
                "conversational",
                "avanzado",
                "advanced",
                "nativo",
                "native",
            )
        )
    ):
        english_question = (
            "spanish" in blob
            and "espanol" not in blob
            and "español" not in blob
        )

        return CustomAnswer(
            field_key=key,
            text=(
                "Native Spanish, with professional, technical "
                "and conversational proficiency."
                if english_question
                else
                "Español nativo, con dominio profesional, "
                "técnico y conversacional."
            ),
            selected=[],
            checked=None,
            requires_human=False,
            reason="",
        )

    known = residence_country_custom_answer(field)
    if known is None:
        known = english_level_custom_answer(field)
    if known is None:
        known = professional_summary_custom_answer(field)
    if known is None:
        known = technology_duration_custom_answer(field)
    if known is None:
        known = work_authorization_answer(field)
    if known is None and kind == "text":
        salary_usd, _ = _effective_custom_salary(decision, job_text)
        known = liquid_clp_salary_answer(field, salary_usd)
    if known is None:
        known = motivation_custom_answer(field, job_text, decision)
    if known is None:
        known = work_mode_custom_answer(field, job_text)
    if known is None:
        known = data_analysis_custom_answer(field)
    if known is None:
        known = office_stack_custom_answer(field)
    if known is None:
        known = banking_comex_custom_answer(field)
    if known is None:
        known = process_certification_custom_answer(field)
    if known is None:
        known = financial_sector_custom_answer(field)
    if known is None:
        known = project_stack_custom_answer(field, job_text)
    if known is None:
        known = role_experience_custom_answer(field, job_text)
    if known is None:
        known = qa_custom_answer(field, job_text)

    if known is not None:
        return CustomAnswer(
            field_key=key,
            text=known.text,
            selected=list(known.selected),
            checked=getattr(known, "checked", None),
            requires_human=False,
            reason="",
        )

    # --------------------------------------------------------
    # HOURLY / BY-HOUR AVAILABILITY
    # --------------------------------------------------------

    hourly_terms = (
        "trabajar por horas",
        "trabajo por horas",
        "por horas",
        "hourly work",
        "work hourly",
        "work by the hour",
        "paid by the hour",
    )

    if any(
        term in blob
        for term in hourly_terms
    ):

        english = any(
            term in blob
            for term in (
                "hourly work",
                "work hourly",
                "work by the hour",
                "paid by the hour",
            )
        )

        if kind == "text":
            return CustomAnswer(
                field_key=key,
                text=(
                    "Yes, I am available to work "
                    "on an hourly basis."
                    if english
                    else
                    "Sí, estoy dispuesto a trabajar por horas."
                ),
                selected=[],
                checked=None,
                requires_human=False,
                reason="",
            )

        for option_label, option_value in _custom_options(
            field
        ):
            visible = (
                option_label
                or option_value
            )

            option_norm = _norm_custom(
                visible
            )

            if (
                option_norm in {
                    "si",
                    "sí",
                    "yes",
                }
                or option_norm.startswith("si ")
                or option_norm.startswith("sí ")
                or option_norm.startswith("yes ")
            ):
                return CustomAnswer(
                    field_key=key,
                    text=None,
                    selected=[visible],
                    checked=None,
                    requires_human=False,
                    reason="",
                )

    # --------------------------------------------------------
    # PROJECT + SALARY COMPOSITE
    # --------------------------------------------------------

    project_terms = (
        "trabajar por un proyecto",
        "trabajo por proyecto",
        "por proyecto",
        "project-based",
        "project based",
        "work on a project",
    )

    project_salary_terms = (
        "pretensiones",
        "pretensión",
        "expectativa salarial",
        "espectativa salarial",
        "renta",
        "salary",
        "salary expectation",
        "compensation",
        "sueldo",
        "remuneracion",
        "remuneración",
    )

    if (
        kind == "text"
        and any(
            term in blob
            for term in project_terms
        )
        and any(
            term in blob
            for term in project_salary_terms
        )
    ):

        english = any(
            term in blob
            for term in (
                "project-based",
                "project based",
                "salary",
                "compensation",
            )
        )

        salary_text = _custom_salary_answer_text(
            decision,
            job_text,
            language=(
                "en"
                if english
                else "es"
            ),
        )

        text_value = (
            (
                "Yes, I am available to work on a "
                "project basis. My compensation "
                f"expectation is {salary_text}"
            )
            if english
            else (
                "Sí, estoy dispuesto a trabajar por "
                "proyecto. Mi pretensión de renta es "
                f"{salary_text}"
            )
        )

        return CustomAnswer(
            field_key=key,
            text=text_value,
            selected=[],
            checked=None,
            requires_human=False,
            reason="",
        )

    # --------------------------------------------------------
    # YEARS — SRE / DEVOPS / CLOUD OPERATIONS
    # --------------------------------------------------------

    if kind == "text":

        duration_answer = (
            build_sre_devops_duration_answer(
                label
            )
        )

        if duration_answer:

            return CustomAnswer(
                field_key=key,
                text=duration_answer,
                selected=[],
                checked=None,
                requires_human=False,
                reason="",
            )

    # --------------------------------------------------------
    # PROJECT-BASED AVAILABILITY
    #
    # The composite PROJECT + SALARY rule above has priority.
    # This handles the simple willingness question.
    # --------------------------------------------------------

    standalone_project_terms = (
        "trabajar inicialmente por un proyecto",
        "trabajar por un proyecto",
        "trabajar por proyecto",
        "trabajo por proyecto",
        "dispuesto a trabajar por proyecto",
        "dispuesto trabajar por proyecto",
        "por un proyecto",
        "por proyecto",
        "project-based",
        "project based",
        "work on a project",
        "work by project",
    )

    if any(
        term in blob
        for term in standalone_project_terms
    ):

        english = any(
            term in blob
            for term in (
                "project-based",
                "project based",
                "work on a project",
                "work by project",
            )
        )

        if kind == "text":

            return CustomAnswer(
                field_key=key,
                text=(
                    "Yes, I am available to work "
                    "on a project basis."
                    if english
                    else
                    "Sí, estoy dispuesto a trabajar "
                    "inicialmente por proyecto."
                ),
                selected=[],
                checked=None,
                requires_human=False,
                reason="",
            )

        # Select / radio / checkbox-like choices.
        for option_label, option_value in _custom_options(
            field
        ):

            visible = (
                option_label
                or option_value
            )

            option_norm = _norm_custom(
                visible
            )

            if (
                option_norm in {
                    "si",
                    "sí",
                    "yes",
                }
                or option_norm.startswith("si ")
                or option_norm.startswith("sí ")
                or option_norm.startswith("yes ")
            ):

                return CustomAnswer(
                    field_key=key,
                    text=None,
                    selected=[visible],
                    checked=None,
                    requires_human=False,
                    reason="",
                )

    # --------------------------------------------------------
    # SALARY
    # --------------------------------------------------------

    salary_terms = (
        "salary",
        "expected salary",
        "salary expectation",
        "renta",
        "pretension",
        "pretensión",
        "expectativa salarial",
        "aspiracion salarial",
        "aspiración salarial",
        "aspiracion de renta",
        "aspiración de renta",
        "espectativa salarial",
        "expectativa de renta",
        "espectativa de renta",
        "sueldo",
        "remuneracion",
        "remuneración",
        "compensation",
    )

    if any(
        term in blob
        for term in salary_terms
    ):
        salary_value, _salary_adjusted = (
            _effective_custom_salary(
                decision,
                job_text,
            )
        )

        salary = str(
            salary_value
        )

        if kind == "text":
            tag = str(
                field.get("tag") or ""
            ).casefold()

            # Standard inputs are safest as numeric values.
            # Free-text salary questions may communicate
            # negotiability when the amount came from market.
            if tag in {
                "textarea",
                "trix-editor",
            }:
                english = any(
                    term in blob
                    for term in (
                        "salary",
                        "compensation",
                        "expected pay",
                    )
                )

                text_value = _custom_salary_answer_text(
                    decision,
                    job_text,
                    language=(
                        "en"
                        if english
                        else "es"
                    ),
                )
            else:
                text_value = salary

            return CustomAnswer(
                field_key=key,
                text=text_value,
                selected=[],
                checked=None,
                requires_human=False,
                reason="",
            )

        # Si excepcionalmente viene como select/radio,
        # usar sólo una opción visible que contenga
        # exactamente el monto.
        for option_label, option_value in _custom_options(field):
            visible = (
                option_label
                or option_value
            )

            if re.search(
                rf"(?<!\d){re.escape(salary)}(?!\d)",
                visible,
            ):
                return CustomAnswer(
                    field_key=key,
                    text=None,
                    selected=[visible],
                    checked=None,
                    requires_human=False,
                    reason="",
                )

    # --------------------------------------------------------
    # AVAILABILITY
    # --------------------------------------------------------

    availability_terms = (
        "availability",
        "disponibilidad",
        "when can you start",
        "cuando puedes comenzar",
        "cuándo puedes comenzar",
        "fecha de inicio",
        "start date",
        "incorporacion",
        "incorporación",
    )

    if any(
        term in blob
        for term in availability_terms
    ):

        if kind == "text":
            label_norm = _norm_custom(
                label
            )

            spanish_markers = (
                "disponibilidad",
                "cuando puedes",
                "cuándo puedes",
                "comenzar",
                "incorporacion",
                "incorporación",
                "fecha de inicio",
            )

            english_markers = (
                "availability",
                "when can you start",
                "start date",
                "available to start",
            )

            english = (
                any(
                    term in label_norm
                    for term in english_markers
                )
                and not any(
                    term in label_norm
                    for term in spanish_markers
                )
            )

            text = (
                "Immediate if required."
                if english
                else "Inmediata si es requerido."
            )

            return CustomAnswer(
                field_key=key,
                text=text,
                selected=[],
                checked=None,
                requires_human=False,
                reason="",
            )

        for option_label, option_value in _custom_options(field):
            visible = (
                option_label
                or option_value
            )

            option_norm = _norm_custom(
                visible
            )

            if (
                "immediate" in option_norm
                or "inmediat" in option_norm
            ):
                return CustomAnswer(
                    field_key=key,
                    text=None,
                    selected=[visible],
                    checked=None,
                    requires_human=False,
                    reason="",
                )

    return None


def _normalize_custom_answer(
    field: dict,
    answer: CustomAnswer,
) -> CustomAnswer:

    key = field["field_key"]
    kind = field["kind"]
    required = bool(
        field.get("required")
    )

    # HUMAN REVIEW conserva el bloqueo,
    # pero elimina basura estructural.
    if answer.requires_human:
        return CustomAnswer(
            field_key=key,
            text=answer.text,
            selected=[],
            checked=None,
            requires_human=True,
            reason=(
                answer.reason
                or "Información requerida no confirmada."
            ),
        )

    # --------------------------------------------------------
    # TEXT
    # --------------------------------------------------------

    if kind == "text":
        text = (
            str(answer.text).strip()
            if answer.text is not None
            else ""
        )

        # Algunos modelos pequeños ponen la respuesta
        # textual dentro de selected. Se permite recuperar
        # sólo ese contenido y después se limpia selected.
        if (
            not text
            and answer.selected
        ):
            text = str(
                answer.selected[0]
            ).strip()

        if required and not text:
            return CustomAnswer(
                field_key=key,
                text=None,
                selected=[],
                checked=None,
                requires_human=True,
                reason=(
                    "El LLM no produjo una respuesta "
                    "textual segura."
                ),
            )

        return CustomAnswer(
            field_key=key,
            text=text or None,
            selected=[],
            checked=None,
            requires_human=False,
            reason="",
        )

    # --------------------------------------------------------
    # SELECT / RADIO
    # --------------------------------------------------------

    if kind in {
        "select",
        "radio",
    }:
        candidates = list(
            answer.selected or []
        )

        if (
            not candidates
            and answer.text
        ):
            candidates = [
                answer.text
            ]

        matched = None

        for candidate in candidates:
            matched = _exact_visible_option(
                field,
                candidate,
            )

            if matched:
                break

        if not matched:
            return CustomAnswer(
                field_key=key,
                text=None,
                selected=[],
                checked=None,
                requires_human=required,
                reason=(
                    "La respuesta no coincide exactamente "
                    "con ninguna opción visible."
                    if required
                    else ""
                ),
            )

        return CustomAnswer(
            field_key=key,
            text=None,
            selected=[matched],
            checked=None,
            requires_human=False,
            reason="",
        )

    # --------------------------------------------------------
    # CHECKBOX
    # --------------------------------------------------------

    if kind == "checkbox":
        candidates = list(
            answer.selected or []
        )

        matched = []

        for candidate in candidates:
            visible = _exact_visible_option(
                field,
                candidate,
            )

            if (
                visible
                and visible not in matched
            ):
                matched.append(
                    visible
                )

        if (
            required
            and not matched
        ):
            return CustomAnswer(
                field_key=key,
                text=None,
                selected=[],
                checked=None,
                requires_human=True,
                reason=(
                    "No existe una selección segura "
                    "entre las opciones visibles."
                ),
            )

        return CustomAnswer(
            field_key=key,
            text=None,
            selected=matched,
            checked=None,
            requires_human=False,
            reason="",
        )

    return CustomAnswer(
        field_key=key,
        text=None,
        selected=[],
        checked=None,
        requires_human=required,
        reason="Tipo de campo no soportado.",
    )


async def _answer_custom_fields_legacy(
    fields: list[dict],
    job_text: str,
    decision,
) -> CustomAnswers:
    """
    Hybrid deterministic/extractive form answering.

    No LLM is allowed to invent custom-field answers.

    Priority:
      1. deterministic rules
      2. extractive evidence
      3. safe binary technical answer
      4. HUMAN_REVIEW when genuinely unknown
    """

    answers = []

    deterministic_count = 0
    evidence_count = 0
    safe_no_count = 0
    human_count = 0

    for field in fields:

        key = field["field_key"]
        kind = field["kind"]

        label = str(
            field.get("label") or ""
        )

        required = bool(
            field.get("required")
        )

        # ----------------------------------------------------
        # PASS 1 — DETERMINISTIC RULES
        # ----------------------------------------------------

        deterministic = (
            _deterministic_custom_answer(
                field,
                decision,
                job_text,
            )
        )

        if deterministic is not None:

            normalized = (
                _normalize_custom_answer(
                    field,
                    deterministic,
                )
            )

            answers.append(
                normalized
            )

            deterministic_count += 1

            continue

        # ----------------------------------------------------
        # PASS 2 — RETRIEVE ONLY RELEVANT EVIDENCE
        # ----------------------------------------------------

        # CUSTOM evidence retrieval must be driven by the
        # actual question, not by the whole job description.
        # Otherwise generic job keywords can overpower the
        # evidence that directly answers the field.
        knowledge = retrieve(
            label,
            limit=4,
        )

        evidence = answer_from_evidence(
            label,
            knowledge,
        )
        if evidence and not evidence_is_user_facing(evidence):
            evidence = None

        # ----------------------------------------------------
        # TEXT / TEXTAREA
        # ----------------------------------------------------

        if kind == "text":

            field_blob = _norm_custom(
                " ".join(
                    [
                        key,
                        label,
                        field.get("name") or "",
                        field.get("id") or "",
                    ]
                )
            )

            technical_question = (
                looks_like_technical_question(
                    field_blob
                )
            )

            truth = lookup_candidate_truth(
                label
            )

            label_norm = _norm_custom(
                label
            )

            spanish = any(
                term in label_norm
                for term in (
                    "experiencia",
                    "conocimiento",
                    "tienes",
                    "describe",
                    "manejo",
                    "dominio",
                    "utilizando",
                    "trabajado",
                )
            )

            # ------------------------------------------------
            # 1. EXPLICIT DENIAL/GUARDRAIL HAS TOP PRIORITY
            #
            # Important:
            # RAG can retrieve the text of a "never_claim"
            # guardrail. That is NOT positive evidence.
            # ------------------------------------------------

            if (
                technical_question
                and truth.status == "denied"
            ):

                answer = CustomAnswer(
                    field_key=key,
                    text=(
                        "No cuento con experiencia directa "
                        "en esta área."
                        if spanish
                        else
                        "I do not have direct experience "
                        "in this area."
                    ),
                    selected=[],
                    checked=None,
                    requires_human=False,
                    reason="",
                )

                safe_no_count += 1

            # ------------------------------------------------
            # 2. STRUCTURED PROFESSIONAL TRUTH
            #
            # Prefer clean candidate.yaml context over raw RAG
            # fragments when professional evidence exists.
            # ------------------------------------------------

            elif (
                technical_question
                and truth.status == "confirmed"
            ):

                contextual = next(
                    (
                        item
                        for item in truth.evidence
                        if (
                            item.organization
                            and item.role
                        )
                    ),
                    None,
                )

                skill = next(
                    iter(truth.concepts),
                    "esta tecnología",
                )

                if contextual:

                    fact = str(
                        contextual.text or ""
                    ).strip()

                    if spanish:
                        text_value = (
                            f"Sí. He trabajado con {skill} "
                            f"en {contextual.organization}, "
                            f"en mi rol de {contextual.role}"
                        )

                        if (
                            fact
                            and _norm_custom(fact)
                            != _norm_custom(skill)
                        ):
                            text_value += (
                                f", incluyendo {fact}."
                            )
                        else:
                            text_value += "."

                    else:
                        text_value = (
                            f"Yes. I have worked with {skill} "
                            f"at {contextual.organization} "
                            f"in my role as {contextual.role}"
                        )

                        if (
                            fact
                            and _norm_custom(fact)
                            != _norm_custom(skill)
                        ):
                            text_value += (
                                f", including {fact}."
                            )
                        else:
                            text_value += "."

                else:

                    if spanish:
                        text_value = (
                            f"Sí. Cuento con experiencia "
                            f"práctica con {skill}."
                        )
                    else:
                        text_value = (
                            f"Yes. I have hands-on "
                            f"experience with {skill}."
                        )

                answer = CustomAnswer(
                    field_key=key,
                    text=text_value,
                    selected=[],
                    checked=None,
                    requires_human=False,
                    reason="",
                )

                evidence_count += 1

            # ------------------------------------------------
            # 3. COMPOSITE TECHNICAL QUESTION
            #
            # Structured CandidateTruth must win over raw RAG.
            # This is especially important for questions that mix
            # confirmed and unknown technologies: the partial-answer
            # engine can state only the defensible subset and preserve
            # explicit qualifiers.
            # ------------------------------------------------

            elif technical_question:

                partial_text = (
                    build_partial_technical_answer(
                        label
                    )
                )

                if partial_text:

                    answer = CustomAnswer(
                        field_key=key,
                        text=partial_text,
                        selected=[],
                        checked=None,
                        requires_human=False,
                        reason="",
                    )

                    evidence_count += 1

                elif evidence and truth.status == "unknown":

                    answer = CustomAnswer(
                        field_key=key,
                        text=evidence,
                        selected=[],
                        checked=None,
                        requires_human=False,
                        reason="",
                    )

                    evidence_count += 1

                else:

                    answer = CustomAnswer(
                        field_key=key,
                        text=None,
                        selected=[],
                        checked=None,
                        requires_human=required,
                        reason=(
                            "CandidateTruth no permite confirmar "
                            "ni negar este campo con seguridad."
                            if required
                            else ""
                        ),
                    )

                    if required:
                        human_count += 1

            # ------------------------------------------------
            # 4. PROJECT / EXTENDED RAG EVIDENCE
            # ------------------------------------------------

            elif evidence:

                answer = CustomAnswer(
                    field_key=key,
                    text=evidence,
                    selected=[],
                    checked=None,
                    requires_human=False,
                    reason="",
                )

                evidence_count += 1

            # ------------------------------------------------
            # 5. UNKNOWN / GUARDED != NO
            # ------------------------------------------------

            else:

                answer = CustomAnswer(
                    field_key=key,
                    text=None,
                    selected=[],
                    checked=None,
                    requires_human=required,
                    reason=(
                        "CandidateTruth no permite confirmar "
                        "ni negar este campo con seguridad."
                        if required
                        else ""
                    ),
                )

                if required:
                    human_count += 1

            answers.append(
                _normalize_custom_answer(
                    field,
                    answer,
                )
            )

            continue

        # ----------------------------------------------------
        # SELECT / RADIO
        #
        # Sólo automatizamos YES/NO cuando la pregunta
        # claramente trata de experiencia/conocimiento.
        # ----------------------------------------------------

        if kind in {
            "select",
            "radio",
        }:

            blob = _norm_custom(
                " ".join(
                    [
                        key,
                        label,
                        field.get("name") or "",
                        field.get("id") or "",
                    ]
                )
            )

            is_technical_question = (
                looks_like_technical_question(
                    blob
                )
            )

            yes_option = None
            no_option = None

            for option_label, option_value in (
                _custom_options(field)
            ):

                visible = (
                    option_label
                    or option_value
                )

                norm = _norm_custom(
                    visible
                )

                if norm in {
                    "yes",
                    "si",
                    "sí",
                    "true",
                    "yes.",
                    "si.",
                    "sí.",
                }:
                    yes_option = visible

                elif norm in {
                    "no",
                    "false",
                    "no.",
                }:
                    no_option = visible

            if (
                is_technical_question
                and yes_option
                and no_option
            ):

                truth = lookup_candidate_truth(
                    label
                )

                if (
                    evidence
                    or truth.status == "confirmed"
                ):
                    selected = yes_option
                    evidence_count += 1

                    answer = CustomAnswer(
                        field_key=key,
                        text=None,
                        selected=[selected],
                        checked=None,
                        requires_human=False,
                        reason="",
                    )

                elif truth.status == "denied":
                    selected = no_option
                    safe_no_count += 1

                    answer = CustomAnswer(
                        field_key=key,
                        text=None,
                        selected=[selected],
                        checked=None,
                        requires_human=False,
                        reason="",
                    )

                else:
                    # UNKNOWN/GUARDED != NO
                    answer = CustomAnswer(
                        field_key=key,
                        text=None,
                        selected=[],
                        checked=None,
                        requires_human=required,
                        reason=(
                            "No existe evidencia suficiente "
                            "para confirmar Sí o No."
                            if required
                            else ""
                        ),
                    )

                    if required:
                        human_count += 1

                answers.append(
                    _normalize_custom_answer(
                        field,
                        answer,
                    )
                )

                continue

            # Non-binary or non-technical choice:
            # do not guess.
            answer = CustomAnswer(
                field_key=key,
                text=None,
                selected=[],
                checked=None,
                requires_human=required,
                reason=(
                    "No existe una regla segura para "
                    "seleccionar esta opción."
                    if required
                    else ""
                ),
            )

            if required:
                human_count += 1

            answers.append(
                _normalize_custom_answer(
                    field,
                    answer,
                )
            )

            continue

        # ----------------------------------------------------
        # CHECKBOX
        # ----------------------------------------------------

        if kind == "checkbox":

            answer = CustomAnswer(
                field_key=key,
                text=None,
                selected=[],
                checked=None,
                requires_human=required,
                reason=(
                    "Checkbox sin regla determinista."
                    if required
                    else ""
                ),
            )

            if required:
                human_count += 1

            answers.append(
                answer
            )

            continue

        # ----------------------------------------------------
        # UNKNOWN
        # ----------------------------------------------------

        answer = CustomAnswer(
            field_key=key,
            text=None,
            selected=[],
            checked=None,
            requires_human=required,
            reason=(
                "Tipo de campo no soportado."
                if required
                else ""
            ),
        )

        if required:
            human_count += 1

        answers.append(
            answer
        )

    # --------------------------------------------------------
    # PASS 4 — GROUNDED LOCAL OLLAMA FALLBACK
    #
    # Only fields that would otherwise require HUMAN_REVIEW are
    # offered to the local model. Deterministic validation inside
    # custom_llm_fallback accepts grounded answers/conservative
    # negatives and rejects ambiguous, sensitive or monetary fields.
    # A model failure never weakens the existing HUMAN_REVIEW guardrail.
    # --------------------------------------------------------

    ollama_count = 0

    unresolved_keys = {
        answer.field_key
        for answer in answers
        if answer.requires_human
    }

    if unresolved_keys:
        unresolved_fields = [
            field
            for field in fields
            if field.get("field_key") in unresolved_keys
        ]

        labels = "\n".join(
            str(field.get("label") or "")
            for field in unresolved_fields
        )

        relevant_chunks = retrieve(
            labels,
            limit=8,
        )

        candidate_text = read_text(
            ROOT / "config" / "candidate.yaml"
        )

        rules_text = read_text(
            ROOT / "config" / "application_rules.yaml"
        )

        technology_text = read_text(
            ROOT / "config" / "technology_truth.yaml"
        )

        grounding = (
            "SOURCE candidate.yaml\n"
            + candidate_text
            + "\n\nSOURCE application_rules.yaml\n"
            + rules_text
            + "\n\nSOURCE technology_truth.yaml\n"
            + technology_text
            + "\n\nRELEVANT PERSONAL KNOWLEDGE\n"
            + "\n\n---\n\n".join(relevant_chunks)
        )

        try:
            fallback = await answer_with_grounded_ollama(
                unresolved_fields,
                job_text,
                grounding,
                getattr(decision, "salary_usd_monthly", None),
                str(getattr(decision, "cv_id", "") or ""),
            )
        except Exception as exc:
            print(
                "⚠️ OLLAMA CUSTOM FALLBACK no disponible; "
                "se conserva HUMAN_REVIEW: "
                f"{type(exc).__name__}: {exc}"
            )
            fallback = {}

        if fallback:
            replaced = []
            for answer in answers:
                fb = fallback.get(answer.field_key)
                if not answer.requires_human or fb is None:
                    replaced.append(answer)
                    continue

                converted = CustomAnswer(
                    field_key=answer.field_key,
                    text=fb.text,
                    selected=list(fb.selected),
                    checked=fb.checked,
                    requires_human=False,
                    reason="",
                )
                replaced.append(converted)
                ollama_count += 1

            answers = replaced
            human_count = sum(
                1
                for answer in answers
                if answer.requires_human
            )

    # --------------------------------------------------------
    # v0.6.11.7 CUSTOM HUMAN METRIC
    #
    # Some deterministic rules can deliberately return
    # requires_human=True. Recalculate from final normalized
    # answers instead of relying on incremental bookkeeping.
    # --------------------------------------------------------

    human_count = sum(
        1
        for answer in answers
        if answer.requires_human
    )


    # ========================================================
    # PASS 5 — v0.6.11.12b AUTONOMOUS CUSTOM RESCUE
    #
    # Ollama has already received every unresolved field.
    # If an ordinary question still remains HUMAN because of
    # timeout / parser / lack of positive evidence, convert it
    # into a truthful conservative answer instead of None.
    # ========================================================

    autonomous_count = 0

    if human_count:

        field_by_key = {
            str(
                field.get("field_key")
                or ""
            ): field
            for field in fields
        }

        salary_usd = getattr(
            decision,
            "salary_usd_monthly",
            None,
        )

        rescued = []

        for answer in answers:

            if not answer.requires_human:
                rescued.append(
                    answer
                )
                continue

            field = field_by_key.get(
                answer.field_key
            )

            if field is None:
                rescued.append(
                    answer
                )
                continue

            fallback = autonomous_answer(
                field,
                salary_usd=salary_usd,
            )

            if fallback is None:
                rescued.append(
                    answer
                )
                continue

            rescued.append(
                CustomAnswer(
                    field_key=answer.field_key,
                    text=fallback.text,
                    selected=list(
                        fallback.selected
                    ),
                    checked=fallback.checked,
                    requires_human=False,
                    reason="",
                )
            )

            autonomous_count += 1

        answers = rescued

        human_count = sum(
            1
            for answer in answers
            if answer.requires_human
        )

    if autonomous_count:
        print(
            "🤖 AUTONOMOUS CUSTOM RESCUE:"
            f" answered={autonomous_count}"
            f" remaining_human={human_count}"
        )

    print(
        "⚙️ CUSTOM v0.5.37:"
        f" deterministic={deterministic_count}"
        f" evidence={evidence_count}"
        f" safe_no={safe_no_count}"
        f" ollama={ollama_count}"
        f" autonomous={autonomous_count}"
        f" human={human_count}"
    )

    return CustomAnswers(
        answers=answers
    )


async def _fill_custom_fields_legacy(
    page,
    fields: list[dict],
    answers: CustomAnswers,
):
    by_key = {
        f["field_key"]: f
        for f in fields
    }

    blockers = []

    for answer in answers.answers:
        field = by_key.get(
            answer.field_key
        )

        if not field:
            continue

        print()
        print(
            f"❓ {field.get('label')}"
        )

        print(
            f"   → {answer.text or answer.selected or answer.checked}"
        )

        if answer.requires_human:
            blockers.append(
                (
                    field.get("label"),
                    answer.reason,
                )
            )
            continue

        kind = field["kind"]

        # TEXT / TEXTAREA / TRIX
        if kind == "text":
            selector = None

            if field.get("id"):
                selector = (
                    "#"
                    + field["id"]
                )

            elif field.get("name"):
                escaped = (
                    field["name"]
                    .replace(
                        '"',
                        '\\"'
                    )
                )

                selector = (
                    f'[name="{escaped}"]'
                )

            if (
                selector
                and answer.text is not None
            ):
                el = page.locator(
                    selector
                ).first

                tag = await el.evaluate(
                    "(e) => e.tagName.toLowerCase()"
                )

                if tag == "trix-editor":
                    await set_trix(
                        page,
                        selector,
                        answer.text,
                    )
                else:
                    await el.fill(
                        answer.text
                    )

        # SELECT
        elif kind == "select":
            if not answer.selected:
                continue

            el = (
                page.locator(
                    "#"
                    + field["id"]
                )
                if field.get("id")
                else page.locator(
                    f'[name="{field["name"]}"]'
                )
            )

            target = (
                answer.selected[0]
            )

            try:
                await el.select_option(
                    label=target
                )
            except Exception:
                await el.select_option(
                    value=target
                )

        # RADIO
        elif kind == "radio":
            if not answer.selected:
                continue

            targets = set(
                x.lower()
                for x in answer.selected
            )

            for option in field["options"]:
                label = (
                    option.get("label")
                    or ""
                ).lower()

                value = (
                    option.get("value")
                    or ""
                ).lower()

                if (
                    label in targets
                    or value in targets
                    or any(
                        t in label
                        for t in targets
                    )
                ):
                    if option.get("id"):
                        el = page.locator(
                            "#"
                            + option["id"]
                        )

                        await el.check()

                        break

        # CHECKBOX
        elif kind == "checkbox":
            targets = set(
                x.lower()
                for x in answer.selected
            )

            for option in field["options"]:
                if not option.get("id"):
                    continue

                el = page.locator(
                    "#"
                    + option["id"]
                )

                if answer.checked is not None:
                    desired = (
                        answer.checked
                    )

                else:
                    label = (
                        option.get("label")
                        or ""
                    ).lower()

                    value = (
                        option.get("value")
                        or ""
                    ).lower()

                    desired = (
                        label in targets
                        or value in targets
                        or any(
                            t in label
                            for t in targets
                        )
                    )

                if desired:
                    if not await el.is_checked():
                        await el.check()
                else:
                    if await el.is_checked():
                        await el.uncheck()

    return blockers


# ============================================================
# MAIN STATE MACHINE
# ============================================================

async def run_application(
    dry_run: bool = True,
):
    settings = Settings()

    session = await BrowserSession.connect_cdp(
        settings.brave_cdp_url
    )

    try:
        page = session.find_page(
            "getonbrd.com"
        )

        if page is None:
            raise RuntimeError(
                "No hay pestaña Get on Board."
            )

        print()
        print("🤖 GET ON BOARD APPLICATION AGENT")
        print("=" * 72)

        stage = await detect_stage(
            page
        )

        print(
            f"📍 Stage inicial: {stage}"
        )

        # Si venimos de REVIEW, volver a BASIC y luego PROFILE.
        if stage == "REVIEW":
            print(
                "⬅️ Volviendo desde REVIEW "
                "para probar flujo completo..."
            )

            await page.go_back()
            await page.wait_for_timeout(
                1200
            )

            stage = await detect_stage(
                page
            )

        # Si estamos BASIC, intentar volver a experiencia.
        if stage == "BASIC":
            experience_link = page.locator(
                'a[href*="step=experience"]'
            )

            if await experience_link.count():
                await experience_link.first.click()
                await page.wait_for_timeout(
                    1000
                )

                stage = await detect_stage(
                    page
                )

        job_url, job_text = await get_job(
            page
        )

        print(
            f"✅ Oferta: {job_url}"
        )

        print()
        print(
            "🧠 Analizando oferta..."
        )

        decision = await analyze_job(
            job_text,
            job_url,
        )

        print()
        print(
            f"🎯 {decision.decision} "
            f"{decision.match_score}%"
        )

        print(
            f"📄 {decision.cv_id}"
        )

        # ====================================================
        # DECISION GATE
        # ====================================================

        decision_name = str(
            decision.decision
        ).upper()

        if decision_name == "SKIP":
            print()
            print(
                "⏭️ SKIP: oferta descartada."
            )
            print(
                "No se modificará ningún campo "
                "de la postulación."
            )
            print(
                f"Motivo: {decision.why}"
            )
            return

        if decision_name == "REVIEW":
            print()
            print(
                "⚠️ REVIEW: continuamos únicamente "
                "porque estamos en DRY RUN."
            )
            print(
                "Esta oferta jamás podrá enviarse "
                "automáticamente."
            )

        # En futuro SUBMIT:
        # REVIEW jamás podrá enviarse.
        if (
            not dry_run
            and str(
                decision.decision
            ).upper() != "APPLY"
        ):
            raise RuntimeError(
                "SUBMIT bloqueado porque "
                "decision != APPLY."
            )

        max_steps = 8

        for step in range(
            1,
            max_steps + 1,
        ):
            stage = await detect_stage(
                page
            )

            print()
            print(
                f"──────── STEP {step}: "
                f"{stage} ────────"
            )

            # PROFILE
            if stage == "PROFILE":
                await fill_profile(
                    page,
                    job_text,
                )

                await click_next(
                    page
                )

                continue

            # BASIC
            if stage == "BASIC":
                await fill_basic(
                    page,
                    job_text,
                    decision,
                )

                await click_next(
                    page
                )

                continue

            # CUSTOM
            if stage == "CUSTOM":
                fields = (
                    await extract_custom_fields(
                        page
                    )
                )

                print(
                    f"🧩 {len(fields)} "
                    "campo(s) extra detectados"
                )

                answers = (
                    await answer_custom_fields(
                        fields,
                        job_text,
                        decision,
                    )
                )

                blockers = (
                    await fill_custom_fields(
                        page,
                        fields,
                        answers,
                    )
                )

                if blockers:
                    print()
                    print(
                        "🛑 HUMAN REVIEW NECESARIO"
                    )

                    for question, reason in blockers:
                        print(
                            f"• {question}"
                        )
                        print(
                            f"  {reason}"
                        )

                    return

                print(
                    "✅ Preguntas extra "
                    "respondidas"
                )

                await click_next(
                    page
                )

                continue

            # REVIEW
            if stage == "REVIEW":
                print()
                print(
                    "🔥 REVIEW ALCANZADO"
                )

                print(
                    f"🎯 Match: "
                    f"{decision.match_score}%"
                )

                print(
                    f"📄 CV: "
                    f"{decision.cv_id}"
                )

                print(
                    f"💰 Renta: "
                    f"{resolve_salary(decision, job_text)} USD"
                )

                if dry_run:
                    print()
                    print(
                        "🛑 DRY RUN: "
                        "NO SE ENVÍA LA POSTULACIÓN."
                    )

                    return

                raise RuntimeError(
                    "Submit real todavía "
                    "no está habilitado."
                )

            raise RuntimeError(
                f"Stage desconocido: {stage}"
            )

        raise RuntimeError(
            "Se alcanzó el máximo "
            "de pasos del formulario."
        )

    finally:
        await session.close()


if __name__ == "__main__":
    asyncio.run(
        run_application(
            dry_run=True
        )
    )



# === v0.6.10 MULTI CHECKBOX ENGINE ===

_CHECKBOX_CORPUS_CACHE = None


def _checkbox_candidate_corpus() -> str:
    """
    Corpus local ya existente del candidato.

    Sólo se usa para políticas deterministas de checklist.
    Nunca convierte requisitos de la oferta en experiencia.
    """

    global _CHECKBOX_CORPUS_CACHE

    if _CHECKBOX_CORPUS_CACHE is None:
        try:
            raw = "\n".join(
                knowledge_chunks()
            )
        except Exception:
            raw = read_text(
                ROOT / "config" / "candidate.yaml"
            )

        _CHECKBOX_CORPUS_CACHE = _norm_custom(
            raw
        )

    return _CHECKBOX_CORPUS_CACHE


def _checkbox_visible_option(
    option: dict,
) -> str:

    return str(
        option.get("label")
        or option.get("value")
        or ""
    ).strip()


def _checkbox_evidence_blob(
    truth,
) -> str:

    values = []

    for evidence in (
        getattr(
            truth,
            "evidence",
            [],
        )
        or []
    ):
        values.append(
            str(
                getattr(
                    evidence,
                    "text",
                    "",
                )
                or ""
            )
        )

        values.append(
            str(
                getattr(
                    evidence,
                    "organization",
                    "",
                )
                or ""
            )
        )

        values.append(
            str(
                getattr(
                    evidence,
                    "role",
                    "",
                )
                or ""
            )
        )

    values.extend(
        str(value)
        for value in (
            getattr(
                truth,
                "concepts",
                [],
            )
            or []
        )
    )

    return _norm_custom(
        " ".join(values)
    )


def _checkbox_is_legal_or_sensitive(
    text: str,
) -> bool:

    low = _norm_custom(text)

    markers = (
        "acepto los terminos",
        "acepto terminos",
        "terms and conditions",
        "privacy policy",
        "politica de privacidad",
        "consentimiento",
        "autorizo el tratamiento",
        "declaro bajo",
        "i certify",
        "certifico que",
        "rut",
        "dni",
        "pasaporte",
        "passport",
        "antecedentes penales",
        "criminal record",
    )

    return any(
        marker in low
        for marker in markers
    )


def _checkbox_option_supported(
    option_text: str,
    truth,
    candidate_corpus: str,
) -> bool:
    """
    Decide si una afirmación individual del checklist puede marcarse.

    Principio:
      - confirmed CandidateTruth es necesario para el caso general;
      - ownership/impact fuerte requiere evidencia más específica;
      - existen unas pocas composiciones deterministas derivadas de hechos
        ya documentados del perfil.
    """

    low = _norm_custom(
        option_text
    )

    evidence = _checkbox_evidence_blob(
        truth
    )

    status = str(
        getattr(
            truth,
            "status",
            "",
        )
        or ""
    ).casefold()

    if _checkbox_is_legal_or_sensitive(
        option_text
    ):
        return False


    # --------------------------------------------------------
    # CASOS COMPUESTOS SEGUROS DEL PERFIL ACTUAL
    # --------------------------------------------------------

    # Kubernetes:
    #
    # "configurado O interactuado" permite marcar si podemos
    # defender interacción práctica con Kubernetes; no estamos
    # afirmando necesariamente administración del cluster.
    if (
        "kubernetes" in low
        and any(
            marker in low
            for marker in (
                "interactuado",
                "interact",
                "utilizado",
                "used",
                "trabajado",
                "worked",
            )
        )
        and "kubernetes" in candidate_corpus
    ):
        return True


    # Scripts Python/Bash para automatización.
    #
    # "Bash y/o Python" means either language is sufficient.
    # Evidence can live in CandidateTruth concepts, evidence text
    # or the standing candidate corpus, so combine all three.
    if (
        "script" in low
        and (
            "python" in low
            or "bash" in low
        )
        and "automat" in low
    ):
        concepts = " ".join(
            str(value)
            for value in (
                getattr(
                    truth,
                    "concepts",
                    [],
                )
                or []
            )
        )

        support = _norm_custom(
            " ".join(
                (
                    candidate_corpus,
                    evidence,
                    concepts,
                )
            )
        )

        language_supported = bool(
            (
                "python" in low
                and "python" in support
            )
            or (
                "bash" in low
                and "bash" in support
            )
        )

        automation_supported = (
            "automat" in support
            or "automation" in support
        )

        if (
            language_supported
            and automation_supported
        ):
            return True


    # Identificación/documentación de incidentes productivos:
    # respaldado por production monitoring + incident response +
    # log analysis/traceability.
    if (
        "incidenc" in low
        and (
            "produccion" in low
            or "production" in low
        )
        and (
            "identific" in low
            or "document" in low
        )
        and (
            "incident response" in candidate_corpus
            or "respuesta a incidentes" in candidate_corpus
        )
        and (
            "log analysis" in candidate_corpus
            or "traceability" in candidate_corpus
            or "trazabilidad" in candidate_corpus
        )
    ):
        return True


    # Operación/mantenimiento para disponibilidad del sistema.
    if (
        (
            "manten" in low
            or "ajust" in low
        )
        and (
            "disponibilidad" in low
            or "availability" in low
        )
        and (
            "operational continuity" in candidate_corpus
            or "continuidad operacional" in candidate_corpus
        )
    ):
        return True


    # --------------------------------------------------------
    # GENERAL: CandidateTruth confirmado.
    # --------------------------------------------------------

    if status != "confirmed":
        return False


    # No convertir "Docker" en "creé imágenes Docker", ni
    # "AWS" en "administré AWS".
    strong_ownership = (
        "creado",
        "creé",
        "created",
        "modificado",
        "modified",
        "implementado",
        "implemented",
        "administrado",
        "administered",
        "liderado",
        "led ",
        "configurado",
        "configured",
        "diseñado",
        "designed",
        "arquitectado",
        "architected",
    )

    has_strong_ownership = any(
        marker in low
        for marker in strong_ownership
    )

    weak_alternative = any(
        marker in low
        for marker in (
            "interactuado",
            "utilizado",
            "used",
            "worked with",
            "trabajado con",
            "participado",
            "colaborado",
        )
    )

    if (
        has_strong_ownership
        and not weak_alternative
    ):
        evidence_ownership = (
            "implement" in evidence
            or "administ" in evidence
            or "configur" in evidence
            or "cread" in evidence
            or "created" in evidence
            or "modific" in evidence
            or "built" in evidence
            or "desarroll" in evidence
        )

        if not evidence_ownership:
            return False


    # Outcome claims need actual outcome evidence.
    outcome_claim = any(
        marker in low
        for marker in (
            "redujo",
            "redujeron",
            "reducir tiempos",
            "reducir errores",
            "reduced time",
            "reduced errors",
            "mejoró",
            "mejoraron",
            "improved",
        )
    )

    if outcome_claim:
        outcome_evidence = any(
            marker in evidence
            for marker in (
                "redu",
                "reduc",
                "improv",
                "ahorro",
                "saving",
                "tiempo",
                "error",
            )
        )

        if not outcome_evidence:
            return False


    return True


def _checkbox_selected_labels(
    field: dict,
) -> list[str]:

    selected = []

    corpus = _checkbox_candidate_corpus()

    for option in (
        field.get("options")
        or []
    ):
        visible = _checkbox_visible_option(
            option
        )

        if not visible:
            continue

        truth = lookup_candidate_truth(
            visible
        )

        if _checkbox_option_supported(
            visible,
            truth,
            corpus,
        ):
            selected.append(
                visible
            )

    return selected


def _checkbox_required(
    field: dict,
) -> bool:
    """
    v0.6.11.1.

    Group-level required evidence wins even if the individual
    checkbox inputs do not carry the HTML required attribute.
    """

    if bool(
        field.get("required")
    ):
        return True

    if bool(
        field.get(
            "required_hint"
        )
    ):
        return True

    label = str(
        field.get("label")
        or ""
    ).strip()

    if "*" in label:
        return True

    return False



def _checkbox_answer(
    field: dict,
    decision,
    job_text: str,
) -> CustomAnswer:

    key = str(
        field.get("field_key")
        or ""
    )

    options = list(
        field.get("options")
        or []
    )

    required = _checkbox_required(
        field
    )


    # --------------------------------------------------------
    # SINGLE BOOLEAN CHECKBOX
    #
    # Preserve v0.6.9 deterministic policies such as
    # "resido en Chile".
    # --------------------------------------------------------

    if len(options) <= 1:

        deterministic = (
            _deterministic_custom_answer(
                field,
                decision,
                job_text,
            )
        )

        if deterministic is not None:
            return deterministic

        return CustomAnswer(
            field_key=key,
            text=None,
            selected=[],
            checked=None,
            requires_human=required,
            reason=(
                "Checkbox obligatorio sin una regla "
                "determinista defendible."
                if required
                else ""
            ),
        )


    # --------------------------------------------------------
    # MULTI CHECKBOX
    # --------------------------------------------------------

    selected = _checkbox_selected_labels(
        field
    )

    if selected:
        return CustomAnswer(
            field_key=key,
            text=None,
            selected=selected,
            checked=None,
            requires_human=False,
            reason="",
        )

    return CustomAnswer(
        field_key=key,
        text=None,
        selected=[],
        checked=None,
        requires_human=required,
        reason=(
            "Checklist obligatorio: ninguna opción pudo "
            "confirmarse con evidencia suficiente."
            if required
            else ""
        ),
    )


async def answer_custom_fields(
    fields: list[dict],
    job_text: str,
    decision,
) -> CustomAnswers:
    """
    v0.6.10:
      checkbox -> deterministic multi-select engine
      everything else -> existing v0.6.9 engine

    This prevents multi-checkbox fields from being fed to Ollama
    as if they were one boolean.
    """

    checkbox_fields = [
        field
        for field in fields
        if str(
            field.get("kind")
            or ""
        ) == "checkbox"
    ]

    legacy_fields = [
        field
        for field in fields
        if str(
            field.get("kind")
            or ""
        ) != "checkbox"
    ]


    legacy_answers = []

    if legacy_fields:

        result = await _answer_custom_fields_legacy(
            legacy_fields,
            job_text,
            decision,
        )

        legacy_answers = list(
            result.answers
        )


    checkbox_answers = [
        _checkbox_answer(
            field,
            decision,
            job_text,
        )
        for field in checkbox_fields
    ]


    if checkbox_fields:

        print(
            "☑️ CHECKBOX ENGINE v0.6.10:"
            f" groups={len(checkbox_fields)}"
        )

        for field, answer in zip(
            checkbox_fields,
            checkbox_answers,
        ):
            print(
                "   •",
                str(
                    field.get("label")
                    or field.get("field_key")
                    or ""
                )[:120],
            )

            if answer.requires_human:
                print(
                    "     → HUMAN:",
                    answer.reason,
                )
            elif answer.selected:
                print(
                    "     → CHECK:",
                    answer.selected,
                )
            elif answer.checked is not None:
                print(
                    "     → CHECKED=",
                    answer.checked,
                )
            else:
                print(
                    "     → sin selección "
                    "(grupo opcional)"
                )


    combined_answers = (
        legacy_answers
        + checkbox_answers
    )

    # v0.6.11.13 — SEMANTIC CUSTOM GATE
    #
    # Engines may be individually grounded yet still return
    # the wrong answer SHAPE for the question.  The final gate
    # validates semantic type immediately before DOM filling.

    field_by_key = {
        str(
            field.get("field_key")
            or ""
        ): field
        for field in fields
    }

    salary_usd = getattr(
        decision,
        "salary_usd_monthly",
        None,
    )

    if not salary_usd:
        try:
            salary_usd = resolve_salary(
                decision,
                job_text,
            )
        except Exception:
            salary_usd = None

    semantic_answers = []

    for answer in combined_answers:

        field = field_by_key.get(
            str(
                answer.field_key
                or ""
            )
        )

        if field is None:
            semantic_answers.append(
                answer
            )
            continue

        gated = normalize_custom_answer(
            field,
            answer,
            salary_usd=salary_usd,
        )

        if gated.get("changed"):

            print(
                "🧠 SEMANTIC GATE:"
                f" {gated.get('gate_reason')}"
                f" → "
                f"{str(field.get('label') or '')[:100]}"
            )

        semantic_answers.append(
            CustomAnswer(
                field_key=answer.field_key,
                text=gated.get("text"),
                selected=list(
                    gated.get("selected")
                    or []
                ),
                checked=gated.get(
                    "checked"
                ),
                requires_human=bool(
                    gated.get(
                        "requires_human"
                    )
                ),
                reason=str(
                    gated.get(
                        "reason"
                    )
                    or ""
                ),
            )
        )

    return CustomAnswers(
        answers=semantic_answers
    )


def _checkbox_css_attr(
    name: str,
    value: str,
) -> str:
    """
    CSS attribute selector using JSON quoting, avoiding
    hand-escaping Rails field names.
    """
    return (
        "["
        + name
        + "="
        + json.dumps(
            str(value),
            ensure_ascii=False,
        )
        + "]"
    )


async def _checkbox_locator(
    page,
    field: dict,
    option: dict,
):

    candidates = []

    option_id = str(
        option.get("id")
        or ""
    )

    option_value = str(
        option.get("value")
        or ""
    )

    option_label = _checkbox_visible_option(
        option
    )

    field_name = str(
        field.get("name")
        or ""
    )


    if option_id:
        candidates.append(
            page.locator(
                _checkbox_css_attr(
                    "id",
                    option_id,
                )
            )
        )


    if (
        field_name
        and option_value
    ):
        candidates.append(
            page.locator(
                "input[type=\"checkbox\"]"
                + _checkbox_css_attr(
                    "name",
                    field_name,
                )
                + _checkbox_css_attr(
                    "value",
                    option_value,
                )
            )
        )


    if option_label:
        try:
            candidates.append(
                page.get_by_label(
                    option_label,
                    exact=True,
                )
            )
        except Exception:
            pass


    for locator in candidates:

        try:
            if await locator.count():
                return locator.first
        except Exception:
            continue


    return None


async def _radio_locator(
    page,
    field: dict,
    option: dict,
):
    """
    Locate a radio using increasingly semantic identities:
      1. id
      2. name + value
      3. visible label
    """

    candidates = []

    option_id = str(
        option.get("id")
        or ""
    )

    option_value = str(
        option.get("value")
        or ""
    )

    option_label = (
        _checkbox_visible_option(
            option
        )
    )

    field_name = str(
        field.get("name")
        or ""
    )

    if option_id:

        candidates.append(
            page.locator(
                _checkbox_css_attr(
                    "id",
                    option_id,
                )
            )
        )

    if (
        field_name
        and option_value
    ):

        candidates.append(
            page.locator(
                'input[type="radio"]'
                + _checkbox_css_attr(
                    "name",
                    field_name,
                )
                + _checkbox_css_attr(
                    "value",
                    option_value,
                )
            )
        )

    if option_label:

        try:
            candidates.append(
                page.get_by_label(
                    option_label,
                    exact=True,
                )
            )

        except Exception:
            pass

    for locator in candidates:

        try:
            if await locator.count():
                return locator.first

        except Exception:
            continue

    return None


async def _apply_radio_group(
    page,
    field: dict,
    answer: CustomAnswer,
) -> list[tuple[str, str]]:

    blockers = []

    label = str(
        field.get("label")
        or field.get("field_key")
        or "Radio"
    )

    required = bool(
        field.get("required")
    )

    if answer.requires_human:

        blockers.append(
            (
                label,
                answer.reason
                or "Radio requiere revisión.",
            )
        )

        return blockers

    selected = [
        str(value or "").strip()
        for value in (
            answer.selected
            or []
        )
        if str(value or "").strip()
    ]

    if not selected:

        if required:

            blockers.append(
                (
                    label,
                    "Radio obligatorio sin decisión.",
                )
            )

        return blockers

    if len(selected) != 1:

        blockers.append(
            (
                label,
                "Radio inválido: se esperaba "
                "exactamente una opción.",
            )
        )

        return blockers

    selected_norm = (
        _norm_custom(
            selected[0]
        )
    )

    target_option = None

    for option in (
        field.get("options")
        or []
    ):

        visible = (
            _checkbox_visible_option(
                option
            )
        )

        value = str(
            option.get("value")
            or ""
        )

        if (
            _norm_custom(visible)
            == selected_norm
            or _norm_custom(value)
            == selected_norm
        ):
            target_option = option
            break

    if target_option is None:

        blockers.append(
            (
                label,
                "La opción radio decidida no "
                "coincide con una opción visible.",
            )
        )

        return blockers

    locator = await _radio_locator(
        page,
        field,
        target_option,
    )

    if locator is None:

        blockers.append(
            (
                label,
                "No pude localizar físicamente "
                "la opción radio elegida.",
            )
        )

        return blockers

    try:

        await locator.check(
            force=True,
            timeout=5000,
        )

        await page.wait_for_timeout(
            100
        )

        if not await locator.is_checked():

            blockers.append(
                (
                    label,
                    "El radio no conservó "
                    "el estado seleccionado.",
                )
            )

            return blockers

        field_name = str(
            field.get("name")
            or ""
        )

        if field_name:

            checked = page.locator(
                'input[type="radio"]'
                + _checkbox_css_attr(
                    "name",
                    field_name,
                )
                + ":checked"
            )

            count = await checked.count()

            if count != 1:

                blockers.append(
                    (
                        label,
                        "El grupo radio no quedó "
                        "con exactamente una "
                        "opción seleccionada.",
                    )
                )

                return blockers

        print(
            "🔘 RADIO OK: "
            f"{label[:100]} → "
            f"{_checkbox_visible_option(target_option)}"
        )

    except Exception as exc:

        blockers.append(
            (
                label,
                "Error operando radio: "
                f"{type(exc).__name__}: {exc}",
            )
        )

    return blockers


async def _apply_checkbox_group(
    page,
    field: dict,
    answer: CustomAnswer,
) -> list[tuple[str, str]]:

    blockers = []

    label = str(
        field.get("label")
        or field.get("field_key")
        or "Checkbox"
    )

    required = _checkbox_required(
        field
    )

    options = list(
        field.get("options")
        or []
    )


    if answer.requires_human:
        blockers.append(
            (
                label,
                answer.reason
                or "Checkbox requiere revisión.",
            )
        )
        return blockers


    # --------------------------------------------------------
    # SINGLE BOOLEAN
    # --------------------------------------------------------

    if len(options) <= 1:

        target_state = answer.checked

        if target_state is None:

            if required:
                blockers.append(
                    (
                        label,
                        "Checkbox obligatorio sin decisión.",
                    )
                )

            return blockers


        option = (
            options[0]
            if options
            else {
                "id": field.get("id"),
                "value": field.get("value"),
                "label": label,
            }
        )

        locator = await _checkbox_locator(
            page,
            field,
            option,
        )

        if locator is None:
            blockers.append(
                (
                    label,
                    "No pude localizar físicamente "
                    "el checkbox en el DOM.",
                )
            )
            return blockers


        if target_state:
            await locator.check(
                force=True,
                timeout=5000,
            )
        else:
            await locator.uncheck(
                force=True,
                timeout=5000,
            )


        actual = await locator.is_checked()

        if actual != bool(target_state):
            blockers.append(
                (
                    label,
                    "El checkbox no conservó el estado "
                    "solicitado después de check/uncheck.",
                )
            )
        else:
            print(
                f"☑️ CHECKBOX boolean OK: "
                f"{label[:100]} → {actual}"
            )

        return blockers


    # --------------------------------------------------------
    # MULTI CHECKBOX
    # --------------------------------------------------------

    selected_norm = {
        _norm_custom(value)
        for value in (
            answer.selected
            or []
        )
        if _norm_custom(value)
    }


    if (
        required
        and not selected_norm
    ):
        blockers.append(
            (
                label,
                "Checklist obligatorio sin ninguna "
                "experiencia confirmada.",
            )
        )

        return blockers


    checked_labels = []


    for option in options:

        visible = _checkbox_visible_option(
            option
        )

        should_check = (
            _norm_custom(
                visible
            )
            in selected_norm
        )

        locator = await _checkbox_locator(
            page,
            field,
            option,
        )

        if locator is None:

            if should_check:
                blockers.append(
                    (
                        label,
                        "No pude localizar la opción "
                        f"que debía marcar: {visible}",
                    )
                )

            continue


        try:

            current = await locator.is_checked()

            if (
                should_check
                and not current
            ):
                await locator.check(
                    force=True,
                    timeout=5000,
                )

            elif (
                not should_check
                and current
            ):
                # Revalidación:
                # limpiar respuestas antiguas no respaldadas.
                await locator.uncheck(
                    force=True,
                    timeout=5000,
                )


            actual = await locator.is_checked()


            if actual != should_check:

                blockers.append(
                    (
                        label,
                        "La opción no conservó el estado esperado: "
                        f"{visible}",
                    )
                )

            elif actual:

                checked_labels.append(
                    visible
                )

        except Exception as exc:

            blockers.append(
                (
                    label,
                    "Error operando checkbox "
                    f"{visible}: "
                    f"{type(exc).__name__}: {exc}",
                )
            )


    if (
        required
        and not checked_labels
        and not blockers
    ):
        blockers.append(
            (
                label,
                "Get on Board requiere al menos una opción "
                "y ninguna quedó marcada.",
            )
        )


    if checked_labels:
        print(
            "☑️ MULTI CHECKBOX OK:"
        )

        for value in checked_labels:
            print(
                "   ✓",
                value,
            )


    return blockers


async def fill_custom_fields(
    page,
    fields: list[dict],
    answers: CustomAnswers,
):
    """
    v0.6.11 physical form engine.

    checkbox -> v0.6.10 verified engine
    radio    -> v0.6.11 verified engine
    others   -> legacy text/select implementation
    """

    by_key = {
        answer.field_key: answer
        for answer in answers.answers
    }

    checkbox_fields = [
        field
        for field in fields
        if str(
            field.get("kind")
            or ""
        ) == "checkbox"
    ]

    radio_fields = [
        field
        for field in fields
        if str(
            field.get("kind")
            or ""
        ) == "radio"
    ]

    legacy_fields = [
        field
        for field in fields
        if str(
            field.get("kind")
            or ""
        )
        not in {
            "checkbox",
            "radio",
        }
    ]

    blockers = []

    for field in checkbox_fields:

        key = str(
            field.get("field_key")
            or ""
        )

        answer = by_key.get(
            key
        )

        if answer is None:

            blockers.append(
                (
                    str(
                        field.get("label")
                        or key
                    ),
                    "No existe respuesta estructurada "
                    "para este checkbox.",
                )
            )

            continue

        blockers.extend(
            await _apply_checkbox_group(
                page,
                field,
                answer,
            )
        )

    for field in radio_fields:

        key = str(
            field.get("field_key")
            or ""
        )

        answer = by_key.get(
            key
        )

        if answer is None:

            blockers.append(
                (
                    str(
                        field.get("label")
                        or key
                    ),
                    "No existe respuesta estructurada "
                    "para este radio.",
                )
            )

            continue

        blockers.extend(
            await _apply_radio_group(
                page,
                field,
                answer,
            )
        )

    if legacy_fields:

        legacy_keys = {
            str(
                field.get("field_key")
                or ""
            )
            for field in legacy_fields
        }

        legacy_answers = CustomAnswers(
            answers=[
                answer
                for answer
                in answers.answers
                if answer.field_key
                in legacy_keys
            ]
        )

        blockers.extend(
            await _fill_custom_fields_legacy(
                page,
                legacy_fields,
                legacy_answers,
            )
        )

    return blockers




# === v0.6.10.2 CHECKBOX SUPPORT OVERRIDE ===

_checkbox_option_supported_v0610_base = (
    _checkbox_option_supported
)


def _checkbox_option_supported(
    option_text: str,
    truth,
    candidate_corpus: str,
) -> bool:

    question = str(
        option_text or ""
    ).casefold()

    evidence = (
        _checkbox_evidence_blob(
            truth
        )
        or ""
    ).casefold()

    concepts = " ".join(
        str(value)
        for value in (
            getattr(
                truth,
                "concepts",
                [],
            )
            or []
        )
    ).casefold()

    corpus = str(
        candidate_corpus or ""
    ).casefold()

    support = " ".join(
        (
            evidence,
            concepts,
            corpus,
        )
    )

    # -----------------------------------------------
    # Python/Bash automation checklist.
    #
    # Example:
    # "scripts en Bash y/o Python para automatizar..."
    #
    # Python + automation is sufficient because the
    # statement explicitly uses y/o.
    # -----------------------------------------------

    script_automation = (
        "script" in question
        and "automat" in question
        and (
            "python" in question
            or "bash" in question
        )
    )

    if script_automation:

        python_supported = (
            "python" in question
            and "python" in support
        )

        bash_supported = (
            "bash" in question
            and "bash" in support
        )

        automation_supported = (
            "automat" in support
            or "automation" in support
        )

        # If wording requires BOTH rather than y/o, do not
        # infer Bash merely from Python.
        explicit_or = (
            "y/o" in question
            or "and/or" in question
            or " o " in question
            or " or " in question
        )

        if (
            automation_supported
            and (
                (
                    explicit_or
                    and (
                        python_supported
                        or bash_supported
                    )
                )
                or (
                    not explicit_or
                    and python_supported
                    and bash_supported
                )
            )
        ):
            return True


    return _checkbox_option_supported_v0610_base(
        option_text,
        truth,
        candidate_corpus,
    )


# === v0.6.11.1 TECHNOLOGY TRUTH REGISTRY ===

_TECHNOLOGY_TRUTH_CACHE = None

_checkbox_option_supported_v06111_base = (
    _checkbox_option_supported
)


def _technology_norm(
    value: str,
) -> str:

    raw = unicodedata.normalize(
        "NFKD",
        str(
            value or ""
        ).casefold(),
    )

    raw = "".join(
        char
        for char in raw
        if not unicodedata.combining(
            char
        )
    )

    raw = re.sub(
        r"\s+",
        " ",
        raw,
    )

    return raw.strip()


def _technology_truth_registry() -> dict:

    global _TECHNOLOGY_TRUTH_CACHE

    if _TECHNOLOGY_TRUTH_CACHE is None:

        try:
            data = load_yaml(
                ROOT
                / "config"
                / "technology_truth.yaml"
            )

        except Exception:
            data = {}

        _TECHNOLOGY_TRUTH_CACHE = (
            data
            if isinstance(
                data,
                dict,
            )
            else {}
        )

    return _TECHNOLOGY_TRUTH_CACHE


def _flatten_technology_keywords(
    value,
) -> list[str]:

    out = []

    if isinstance(
        value,
        str,
    ):

        if value.strip():
            out.append(
                value.strip()
            )

    elif isinstance(
        value,
        list,
    ):

        for item in value:
            out.extend(
                _flatten_technology_keywords(
                    item
                )
            )

    elif isinstance(
        value,
        dict,
    ):

        for item in value.values():
            out.extend(
                _flatten_technology_keywords(
                    item
                )
            )

    return out


def _technology_term_present(
    text: str,
    term: str,
) -> bool:

    blob = _technology_norm(
        text
    )

    needle = _technology_norm(
        term
    )

    if not needle:
        return False

    # Important for Go / JS / AI / ML.
    # "Go" must not match a random substring,
    # and "JS" must not turn RxJS into JavaScript.
    pattern = (
        r"(?<![a-z0-9])"
        + re.escape(
            needle
        )
        + r"(?![a-z0-9])"
    )

    return bool(
        re.search(
            pattern,
            blob,
        )
    )


def _technology_capability_supported(
    option_text: str,
) -> str | None:

    registry = (
        _technology_truth_registry()
    )

    capabilities = (
        registry.get(
            "confirmed_capabilities"
        )
        or []
    )

    blob = _technology_norm(
        option_text
    )

    for capability in capabilities:

        if not isinstance(
            capability,
            dict,
        ):
            continue

        match_all = (
            capability.get(
                "match_all"
            )
            or []
        )

        if not match_all:
            continue

        matched = True

        for alternatives in match_all:

            if isinstance(
                alternatives,
                str,
            ):
                alternatives = [
                    alternatives
                ]

            if not isinstance(
                alternatives,
                list,
            ):
                matched = False
                break

            if not any(
                _technology_norm(
                    term
                )
                in blob
                for term
                in alternatives
                if str(
                    term or ""
                ).strip()
            ):

                matched = False
                break

        if matched:

            return str(
                capability.get(
                    "id"
                )
                or "confirmed_capability"
            )

    return None


def _technology_simple_keyword_supported(
    option_text: str,
) -> str | None:
    """
    A plain confirmed technology may answer simple "used/worked with"
    statements, but MUST NOT be upgraded into leadership, ownership,
    administration, years or advanced-production claims.
    """

    registry = (
        _technology_truth_registry()
    )

    keywords = (
        _flatten_technology_keywords(
            registry.get(
                "confirmed_keywords"
            )
            or {}
        )
    )

    blob = _technology_norm(
        option_text
    )

    strong_claim_markers = (
        "administre",
        "administrado",
        "administrando",
        "managed",
        "lider",
        "led ",
        "lead ",
        "arquitect",
        "architect",
        "experto",
        "expert",
        "anos",
        "years",
        "enterprise",
        "gran escala",
        "at scale",
        "ownership",
        "responsable de",
        "responsible for",
        "migre",
        "migracion",
        "migration",
    )

    if any(
        marker in blob
        for marker
        in strong_claim_markers
    ):
        return None

    # Long descriptive claims should normally have an explicit
    # capability rule. Keywords alone are intended for simple
    # technology-use statements.
    weak_use_markers = (
        "he usado",
        "he utilizado",
        "he trabajado con",
        "experiencia con",
        "conocimiento de",
        "uso de",
        "utilice",
        "utilizando",
        "worked with",
        "used ",
        "experience with",
        "knowledge of",
        "familiar with",
    )

    simple_shape = bool(
        len(blob) <= 90
        or any(
            marker in blob
            for marker
            in weak_use_markers
        )
    )

    if not simple_shape:
        return None

    # Prefer longest aliases first:
    # "Oracle Cloud Infrastructure" before "Oracle".
    for keyword in sorted(
        set(keywords),
        key=lambda value: len(
            _technology_norm(
                value
            )
        ),
        reverse=True,
    ):

        if _technology_term_present(
            blob,
            keyword,
        ):

            return keyword

    return None


def _technology_registry_supports(
    option_text: str,
) -> bool:

    capability = (
        _technology_capability_supported(
            option_text
        )
    )

    if capability:

        print(
            "🧠 TECH TRUTH capability: "
            f"{capability}"
        )

        return True

    keyword = (
        _technology_simple_keyword_supported(
            option_text
        )
    )

    if keyword:

        print(
            "🧠 TECH TRUTH keyword: "
            f"{keyword}"
        )

        return True

    return False


def _checkbox_option_supported(
    option_text: str,
    truth,
    candidate_corpus: str,
) -> bool:
    """
    v0.6.11.1 priority:

      1. explicit Technology Truth capability
      2. conservative Technology Truth keyword use
      3. pre-existing CandidateTruth/corpus engine

    Technology keywords alone NEVER authorize stronger ownership,
    seniority, years or administration claims.
    """

    if _technology_registry_supports(
        option_text
    ):
        return True

    return (
        _checkbox_option_supported_v06111_base(
            option_text,
            truth,
            candidate_corpus,
        )
    )
