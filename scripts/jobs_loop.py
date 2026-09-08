from __future__ import annotations

import argparse
import os
import asyncio
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit, urlunsplit

from playwright.async_api import Error as PlaywrightError

from agentes.browser import BrowserSession
from agentes.config import Settings
from agentes.jobs.analyzer import (
    analyze_job,
    _central_mismatch,
    _central_qa_role,
    _internship_role,
    _role_identity,
    _strict_location_ok,
    _targeting_blob,
)
from agentes.jobs.gob_stage import repair_step_from_stage, resolve_gob_step
from agentes.jobs.cv_language_policy import resolve_cv_language
from agentes.jobs.submit_confirmation_policy import (
    is_known_privacy_submit_confirmation,
)
from agentes.jobs.application_runner import (
    answer_custom_fields,
    click_next,
    detect_stage,
    extract_custom_fields,
    fill_basic,
    fill_custom_fields,
    fill_profile,
)

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "state" / "job_loop.db"
MYJOBS = "https://www.getonbrd.com/myjobs"


def _retry_seconds_env(
    name: str,
    default: int,
    minimum: int = 60,
) -> int:
    try:
        value = int(
            os.getenv(
                name,
                str(default),
            )
        )
    except Exception:
        value = default

    return max(
        minimum,
        value,
    )


class AuthRequired(RuntimeError):
    pass


class OfferIdentityMismatch(RuntimeError):
    """The page/CTA no longer belongs to the job being processed."""
    pass


def db() -> sqlite3.Connection:
    DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS job_loop (
            url TEXT PRIMARY KEY,
            decision_json TEXT,
            decision TEXT,
            score INTEGER,
            cv_id TEXT,
            status TEXT NOT NULL,
            last_error TEXT,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    return conn


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def decision_name(decision) -> str:
    value = getattr(decision, "decision", "")
    if hasattr(value, "value"):
        value = value.value
    return str(value).upper().split(".")[-1]


def decision_dict(decision) -> dict:
    if hasattr(decision, "model_dump"):
        data = decision.model_dump(mode="json")
    else:
        data = dict(vars(decision))
    value = data.get("decision")
    if hasattr(value, "value"):
        data["decision"] = value.value
    return data


def promote_review_if_safe(decision, job_text: str, url: str):
    """
    Capa determinista posterior al LLM.

    El modelo sigue evaluando compatibilidad.
    Esta política evita ser excesivamente conservador con
    candidatos razonablemente compatibles.

    Nunca convierte SKIP en APPLY.
    """

    if decision_name(decision) != "REVIEW":
        return decision

    try:
        score = int(
            getattr(
                decision,
                "match_score",
                0,
            ) or 0
        )
    except Exception:
        score = 0

    cv_id = getattr(
        decision,
        "cv_id",
        None,
    )

    if not cv_id:
        return decision

    role_identity = _role_identity(
        job_text,
        url,
    )

    blob = _targeting_blob(
        job_text,
        url,
    )

    # --------------------------------------------------------
    # ROLE IDENTITY GATES
    # --------------------------------------------------------

    if _central_qa_role(
        job_text,
        url,
    ):
        return decision

    if _internship_role(
        role_identity
    ):
        return decision

    if _central_mismatch(
        role_identity
    ):
        return decision

    # Analyzer already catches content blockers for fresh jobs.
    # This bounded head check protects historical cached REVIEW
    # decisions without scanning unrelated recommendations.
    blocker_head = blob[:2500]

    hard_blockers = (
        "unpaid",
        "sin remuneración",
        "sin remuneracion",
        "relocation required",
        "must relocate",
        "mandatory relocation",
        "reubicación obligatoria",
        "reubicacion obligatoria",
    )

    if any(
        blocker in blocker_head
        for blocker in hard_blockers
    ):
        return decision

    if not _strict_location_ok(
        job_text,
        url,
    ):
        return decision

    # --------------------------------------------------------
    # AI / AGENTIC
    # --------------------------------------------------------

    ai_terms = (
        "ai engineer",
        "ia engineer",
        "applied ai",
        "artificial intelligence",
        "inteligencia artificial",
        "machine learning",
        "generative ai",
        "genai",
        "llm",
        "rag",
        "agentic",
        "agentes de ia",
        "agentes de ai",
        "ai agent",
        "ai automation",
        "automation engineer",
        "foco en ia",
        "foco-en-ia",
    )

    is_ai = any(
        term in blob
        for term in ai_terms
    )

    # v0.4 volume policy:
    # REVIEW >= 60 + CV válido + sin hard blockers => APPLY
    promote = score >= 60

    # AI/Agentic: 72+
    # Tenemos un proyecto real operativo que respalda este ajuste.
    if is_ai and score >= 72:
        promote = True

    if not promote:
        return decision

    data = decision_dict(
        decision
    )

    data["decision"] = "APPLY"

    promoted = SimpleNamespace(
        **data
    )

    print()
    print(
        "🚀 POLICY PROMOTION:"
        f" REVIEW {score}% → APPLY"
        + (
            " [AI/AGENTIC]"
            if is_ai
            else ""
        )
    )

    return promoted


def load_record(url: str):
    """
    Busca por URL exacta y luego por slug.

    Get on Board usa tanto /jobs/... como /empleos/...
    para el mismo cargo.
    """

    with db() as conn:

        row = conn.execute(
            """
            SELECT *
            FROM job_loop
            WHERE url = ?
            """,
            (url,),
        ).fetchone()

        if row:
            return row

        try:
            slug = (
                urlsplit(url)
                .path
                .rstrip("/")
                .split("/")[-1]
            )
        except Exception:
            slug = ""

        if not slug:
            return None

        row = conn.execute(
            """
            SELECT *
            FROM job_loop
            WHERE url LIKE ?
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (
                "%/" + slug,
            ),
        ).fetchone()

        return row


def save_record(url: str, *, status: str, decision=None, error: str | None = None):
    payload = dname = score = cv_id = None
    if decision is not None:
        data = decision_dict(decision)
        payload = json.dumps(data, ensure_ascii=False)
        dname = decision_name(decision)
        score = getattr(decision, "match_score", None)
        cv_id = getattr(decision, "cv_id", None)

    with db() as conn:
        conn.execute(
            """
            INSERT INTO job_loop
                (url, decision_json, decision, score, cv_id, status, last_error, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
                decision_json = COALESCE(excluded.decision_json, job_loop.decision_json),
                decision = COALESCE(excluded.decision, job_loop.decision),
                score = COALESCE(excluded.score, job_loop.score),
                cv_id = COALESCE(excluded.cv_id, job_loop.cv_id),
                status = excluded.status,
                last_error = excluded.last_error,
                updated_at = excluded.updated_at
            """,
            (url, payload, dname, score, cv_id, status, error, now()),
        )
        conn.commit()


def cached_decision(url: str):
    row = load_record(url)
    if not row or not row["decision_json"]:
        return None
    return SimpleNamespace(**json.loads(row["decision_json"]))


def queued_retry_urls(
    limit: int = 1000,
    submit: bool = False,
) -> list[str]:
    """
    Persistent retry queue.

    DRY RUN:
      - REQUEUE_* immediately
      - recoverable HUMAN_REVIEW after a bounded cooldown
      - CUSTOM_BLOCKER re-enters the autonomous lane
      - permanent repair/identity/safe-start blockers remain frozen
      - REVIEW after a bounded cooldown
      - ERROR after its own cooldown

    SUBMIT:
      - DRY_RUN_READY only

    REVIEW/HUMAN_REVIEW are re-evaluated only in the reversible lane.
    Re-saving either state refreshes updated_at, so unresolved jobs cannot
    hot-loop and starve discovery.
    """

    if submit:
        where = """
            status = 'DRY_RUN_READY'
        """
    else:
        error_retry = _retry_seconds_env(
            "JOB_ERROR_RETRY_SECONDS",
            900,
        )
        review_retry = _retry_seconds_env(
            "REVIEW_RETRY_SECONDS",
            21600,
        )
        human_retry = _retry_seconds_env(
            "HUMAN_REVIEW_RETRY_SECONDS",
            21600,
        )
        analyzed_retry = _retry_seconds_env(
            "ANALYZED_RETRY_SECONDS",
            900,
        )
        cta_retry = _retry_seconds_env(
            "CTA_MISSING_RETRY_SECONDS",
            21600,
        )

        where = f"""
            status LIKE 'REQUEUE_%'
            OR (
                status = 'ANALYZED'
                AND julianday(updated_at)
                    <= julianday('now', '-{analyzed_retry} seconds')
            )
            OR (
                status = 'APPLICATION_CTA_MISSING'
                AND julianday(updated_at)
                    <= julianday('now', '-{cta_retry} seconds')
            )
            OR (
                status = 'HUMAN_REVIEW'
                AND julianday(updated_at)
                    <= julianday('now', '-{human_retry} seconds')

                -- Recoverable HUMAN_REVIEW re-enters DRY_RUN.
                -- Permanent/safety blockers remain frozen.

                AND COALESCE(last_error, '')
                    NOT LIKE 'REPAIR_EXHAUSTED:%'

                AND COALESCE(last_error, '')
                    NOT LIKE '%OFFER_IDENTITY_MISMATCH%'

                AND COALESCE(last_error, '')
                    NOT LIKE '%No se encontró una forma segura%'

                -- v0.6.11.13a:
                -- A required checklist containing only
                -- unsupported positive claims is not a
                -- transient failure. Reopening it cannot
                -- produce an honest different answer.

                AND COALESCE(last_error, '')
                    NOT LIKE '%Checklist obligatorio: ninguna opción pudo confirmarse con evidencia suficiente%'

                AND COALESCE(last_error, '')
                    NOT LIKE '%Checkbox obligatorio sin una regla determinista defendible%'
            )
            OR (
                status = 'REVIEW'
                AND julianday(updated_at)
                    <= julianday('now', '-{review_retry} seconds')
            )
            OR (
                status = 'ERROR'
                AND julianday(updated_at)
                    <= julianday('now', '-{error_retry} seconds')
            )
        """

    query = f"""
        SELECT url
        FROM job_loop
        WHERE (
            {where}
        )
        ORDER BY
            CASE
                WHEN status = 'DRY_RUN_READY' THEN 0
                WHEN status = 'REQUEUE_FORM_INVALID' THEN 1
                WHEN status LIKE 'REQUEUE_V069_%' THEN 1
                WHEN status = 'REQUEUE_CV_LANGUAGE' THEN 1
                WHEN status = 'REQUEUE_V04' THEN 2
                WHEN status = 'REQUEUE_AGENTIC' THEN 3
                WHEN status = 'REQUEUE_V03' THEN 3
                WHEN status = 'REQUEUE_V04_ERROR' THEN 4
                WHEN status = 'ANALYZED' THEN 5
                WHEN status = 'APPLICATION_CTA_MISSING' THEN 6
                WHEN status = 'HUMAN_REVIEW' THEN 7
                WHEN status = 'REVIEW' THEN 8
                WHEN status = 'ERROR' THEN 9
                ELSE 10
            END,
            COALESCE(score, 0) DESC,
            julianday(updated_at) ASC,
            url ASC
        LIMIT ?
    """

    with db() as conn:
        rows = conn.execute(
            query,
            (limit,),
        ).fetchall()

    return [
        row["url"]
        for row in rows
        if row["url"]
    ]


def canonical_url(url: str) -> str:
    p = urlsplit(url)
    return urlunsplit((p.scheme, p.netloc, p.path.rstrip("/"), "", ""))


async def ensure_auth(page):
    url = page.url.lower()
    if any(x in url for x in ("/login", "/sign_in", "/signin")):
        raise AuthRequired("Get on Board requiere login.")

    if await page.locator('input[type="password"]').count():
        raise AuthRequired("Get on Board requiere login.")

    body = (await page.locator("body").inner_text()).lower()
    if any(x in body for x in (
        "código de verificación",
        "codigo de verificacion",
        "verification code",
        "two-factor",
        "two factor",
        "2fa",
    )):
        raise AuthRequired("Get on Board requiere 2FA/verificación.")


async def _safe_collect_job_links(
    page,
    attempts: int = 8,
) -> list[str]:
    """
    Get on Board puede navegar/re-renderizar mientras leemos el DOM.
    Si el execution context desaparece, esperamos y reintentamos.
    """

    last_error = None

    for attempt in range(1, attempts + 1):
        try:
            try:
                await page.wait_for_load_state(
                    "domcontentloaded",
                    timeout=10000,
                )
            except Exception:
                pass

            await page.locator("body").wait_for(
                state="attached",
                timeout=10000,
            )

            hrefs = await page.locator(
                """
                a[href*='/empleos/'],
                a[href*='/jobs/']
                """
            ).evaluate_all(
                """
                els => els.map(a => a.href || '')
                """
            )

            return hrefs

        except PlaywrightError as exc:
            last_error = exc
            msg = str(exc).lower()

            navigation_race = (
                "execution context was destroyed" in msg
                or "most likely because of a navigation" in msg
                or "cannot find context" in msg
                or "frame was detached" in msg
            )

            if not navigation_race:
                raise

            print(
                f"♻️ Navegación detectada durante discovery "
                f"({attempt}/{attempts}); reintentando..."
            )

            await page.wait_for_timeout(
                400 * attempt
            )

            # Si un redirect nos sacó de myjobs, recuperamos.
            if "/myjobs" not in page.url.lower():
                print(
                    f"↩️ Recuperando /myjobs desde: "
                    f"{page.url}"
                )

                await page.goto(
                    MYJOBS,
                    wait_until="domcontentloaded",
                    timeout=30000,
                )

                await page.wait_for_timeout(1000)
                await ensure_auth(page)

    raise RuntimeError(
        "No pude estabilizar Get on Board durante "
        f"el discovery. Último error: {last_error}"
    )


async def discover_jobs_recommended(
    page,
    scrolls: int = 8,
) -> list[str]:

    print("🔎 Descubriendo ofertas...")

    await page.goto(
        MYJOBS,
        wait_until="domcontentloaded",
        timeout=30000,
    )

    await page.wait_for_timeout(1500)

    await ensure_auth(page)

    seen: set[str] = set()
    jobs: list[str] = []

    # Recolectamos links EN CADA scroll.
    # Así no dependemos de que el DOM final conserve
    # todas las ofertas cargadas anteriormente.
    for scroll_number in range(scrolls + 1):

        hrefs = await _safe_collect_job_links(
            page
        )

        new_count = 0

        for href in hrefs:
            if not href:
                continue

            if "getonbrd.com" not in href:
                continue

            if "/applications" in href:
                continue

            if (
                "/empleos/" not in href
                and "/jobs/" not in href
            ):
                continue

            url = canonical_url(href)

            if url in seen:
                continue

            seen.add(url)
            jobs.append(url)
            new_count += 1

        print(
            f"   scroll {scroll_number}/{scrolls}: "
            f"{len(jobs)} ofertas "
            f"(+{new_count})"
        )

        if scroll_number >= scrolls:
            break

        # Usamos wheel en vez de ejecutar JS de scroll
        # para reducir dependencia del execution context.
        try:
            await page.mouse.wheel(
                0,
                5000,
            )
        except PlaywrightError:
            pass

        await page.wait_for_timeout(900)

        # Un redirect inesperado tampoco rompe el loop.
        if "/myjobs" not in page.url.lower():
            print(
                "⚠️ Get on Board navegó fuera de /myjobs; "
                "recuperando..."
            )

            await page.goto(
                MYJOBS,
                wait_until="domcontentloaded",
                timeout=30000,
            )

            await page.wait_for_timeout(1000)
            await ensure_auth(page)

    print(
        f"✅ Discovery terminado: "
        f"{len(jobs)} ofertas únicas"
    )

    return jobs




# ============================================================
# GLOBAL GET ON BOARD DISCOVERY
# ============================================================

GLOBAL_JOB_SEEDS = [
    (
        "PROGRAMMING",
        "https://www.getonbrd.com/jobs/programming",
        "programming",
    ),
    (
        "DEVOPS_QA",
        "https://www.getonbrd.com/jobs/sysadmin-devops-qa",
        "sysadmin-devops-qa",
    ),
    (
        "DATA",
        "https://www.getonbrd.com/jobs/data-science-analytics",
        "data-science-analytics",
    ),
    (
        "ML_AI",
        "https://www.getonbrd.com/jobs/machine-learning-ai",
        "machine-learning-ai",
    ),
    (
        "TECH_SUPPORT",
        "https://www.getonbrd.com/jobs/technical-support",
        "technical-support",
    ),
    (
        "CUSTOMER_SUPPORT",
        "https://www.getonbrd.com/jobs/customer-support",
        "customer-support",
    ),
    (
        "PRODUCT_AGILE",
        "https://www.getonbrd.com/jobs/innovation-agile",
        "innovation-agile",
    ),
    (
        "OPERATIONS",
        "https://www.getonbrd.com/jobs/operations-management",
        "operations-management",
    ),
    (
        "MOBILE",
        "https://www.getonbrd.com/jobs/mobile-developer",
        "mobile-developer",
    ),
    (
        "CYBERSECURITY",
        "https://www.getonbrd.com/jobs/cybersecurity",
        "cybersecurity",
    ),
]


GLOBAL_CATEGORY_SLUGS = {
    category
    for _, _, category in GLOBAL_JOB_SEEDS
}


def _job_slug_from_url(url: str) -> str:
    try:
        path = urlsplit(url).path.rstrip("/")
    except Exception:
        return ""

    parts = [
        x
        for x in path.split("/")
        if x
    ]

    if len(parts) < 3:
        return ""

    # /jobs/<category>/<job-slug>
    # /empleos/<category>/<job-slug>
    if (
        parts[0] in {"jobs", "empleos"}
        and parts[1] in GLOBAL_CATEGORY_SLUGS
        and len(parts) >= 3
    ):
        slug = parts[2]

        # Nunca confundir rutas internas.
        if slug in {
            "applications",
            "new",
            "edit",
        }:
            return ""

        return slug

    return ""


async def _collect_global_links(page):
    """
    Lee solamente URLs candidatas.
    Tolera navigations/re-renders de Get on Board.
    """

    last_error = None

    for attempt in range(1, 6):
        try:
            hrefs = await page.locator(
                "a[href]"
            ).evaluate_all(
                """
                els => els
                    .map(a => a.href || '')
                    .filter(Boolean)
                """
            )

            return hrefs

        except PlaywrightError as exc:
            last_error = exc

            print(
                f"   ♻️ DOM cambió "
                f"({attempt}/5), reintentando..."
            )

            await page.wait_for_timeout(
                300 * attempt
            )

    raise RuntimeError(
        "No pude leer links después de 5 intentos: "
        f"{last_error}"
    )


async def discover_jobs(
    page,
    scrolls: int = 8,
) -> list[str]:
    """
    Discovery GLOBAL.

    No depende de los filtros de 'Empleos para ti'.

    Recorre directamente las categorías relevantes
    de Get on Board y deduplica los cargos por slug.
    """

    print()
    print("🌎 GLOBAL DISCOVERY GET ON BOARD")
    print("=" * 72)

    jobs_by_slug = {}

    # ========================================================
    # v0.6.11.13b — BACKLOG FIRST
    #
    # Discovery must never delay hundreds of already-known
    # applications that are waiting for repair.
    #
    # Once the recoverable backlog drops below the threshold,
    # global discovery resumes automatically.
    # ========================================================

    os_mod = __import__("os")
    asyncio_mod = __import__("asyncio")
    time_mod = __import__("time")

    try:
        backlog_threshold = int(
            os_mod.getenv(
                "JOB_DISCOVERY_BACKLOG_THRESHOLD",
                "20",
            )
        )
    except Exception:
        backlog_threshold = 20

    backlog_threshold = max(
        1,
        min(
            backlog_threshold,
            5000,
        ),
    )

    try:
        backlog_probe = queued_retry_urls(
            limit=backlog_threshold,
            submit=False,
        )
    except Exception as exc:
        print(
            "⚠️ No pude medir backlog para "
            f"discovery gate: {exc}"
        )
        backlog_probe = []

    if (
        len(backlog_probe)
        >= backlog_threshold
    ):
        print()
        print(
            "⏭️ DISCOVERY DIFERIDO — BACKLOG FIRST"
        )
        print(
            "   Pendientes recuperables >= "
            f"{backlog_threshold}"
        )
        print(
            "   Primero se terminarán postulaciones "
            "ya conocidas."
        )
        print(
            "   Discovery volverá automáticamente "
            "cuando baje el backlog."
        )
        return []

    def _env_float(
        name,
        default,
        minimum,
        maximum,
    ):
        try:
            value = float(
                os_mod.getenv(
                    name,
                    str(default),
                )
            )
        except Exception:
            value = float(default)

        return max(
            minimum,
            min(
                value,
                maximum,
            ),
        )

    nav_hard_timeout = _env_float(
        "JOB_DISCOVERY_NAV_HARD_TIMEOUT",
        20,
        0.01,
        60,
    )

    dom_hard_timeout = _env_float(
        "JOB_DISCOVERY_DOM_HARD_TIMEOUT",
        10,
        0.01,
        30,
    )

    auth_hard_timeout = _env_float(
        "JOB_DISCOVERY_AUTH_HARD_TIMEOUT",
        10,
        0.01,
        30,
    )

    discovery_total_budget = _env_float(
        "JOB_DISCOVERY_TOTAL_BUDGET",
        90,
        1,
        300,
    )

    discovery_started = (
        time_mod.monotonic()
    )

    for (
        source_name,
        seed_url,
        category_slug,
    ) in GLOBAL_JOB_SEEDS:

        if (
            time_mod.monotonic()
            - discovery_started
            >= discovery_total_budget
        ):
            print()
            print(
                "⏱️ DISCOVERY BUDGET GLOBAL agotado "
                f"({discovery_total_budget:.0f}s)."
            )
            print(
                "   Continúo con las ofertas "
                "ya descubiertas."
            )
            break

        print()
        print(
            f"🔎 {source_name}"
        )

        try:
            await asyncio_mod.wait_for(
                page.goto(
                    seed_url,
                    wait_until="domcontentloaded",
                    timeout=15000,
                ),
                timeout=nav_hard_timeout,
            )

            # Plain asyncio sleep avoids another unnecessary
            # round trip through a potentially unhealthy CDP.
            await asyncio_mod.sleep(
                1.3
            )

            await asyncio_mod.wait_for(
                ensure_auth(page),
                timeout=auth_hard_timeout,
            )

        except Exception as exc:
            print(
                f"   ⚠️ No pude abrir categoría: {exc}"
            )
            continue

        found_here = set()
        stagnant = 0

        for round_no in range(
            scrolls + 1
        ):

            try:
                hrefs = await asyncio_mod.wait_for(
                    _collect_global_links(
                        page
                    ),
                    timeout=dom_hard_timeout,
                )
            except Exception as exc:
                print(
                    f"   ⚠️ lectura DOM: {exc}"
                )
                break

            before = len(found_here)

            for href in hrefs:

                if "getonbrd.com" not in href:
                    continue

                url = canonical_url(
                    href
                )

                slug = _job_slug_from_url(
                    url
                )

                if not slug:
                    continue

                found_here.add(
                    slug
                )

                # Dedupe global:
                # el mismo empleo puede aparecer
                # en distintas recomendaciones/widgets.
                if slug not in jobs_by_slug:
                    jobs_by_slug[
                        slug
                    ] = url

            gained = (
                len(found_here)
                - before
            )

            if gained:
                stagnant = 0
            else:
                stagnant += 1

            # Si durante tres scrolls no aparece nada,
            # esta categoría ya se agotó visualmente.
            if stagnant >= 3:
                break

            try:
                await asyncio_mod.wait_for(
                    page.mouse.wheel(
                        0,
                        7000,
                    ),
                    timeout=5,
                )
            except Exception:
                pass

            await asyncio_mod.sleep(
                0.7
            )

        print(
            f"   ✅ {len(found_here)} "
            "ofertas"
        )

    jobs = list(
        jobs_by_slug.values()
    )

    print()
    print("=" * 72)
    print(
        f"🌎 TOTAL GLOBAL ÚNICO: "
        f"{len(jobs)} ofertas"
    )
    print("=" * 72)

    return jobs


def job_slug_from_url(url: str) -> str:
    try:
        segments = [
            part
            for part in urlsplit(str(url or "")).path.split("/")
            if part
        ]
    except Exception:
        return ""

    if not segments:
        return ""

    if "applications" in segments:
        idx = segments.index("applications")
        return segments[idx - 1].casefold() if idx > 0 else ""

    return segments[-1].casefold()


def application_href_matches_job(href: str, expected_job_url: str) -> bool:
    expected = job_slug_from_url(expected_job_url)
    if not expected:
        return False

    try:
        segments = [
            part.casefold()
            for part in urlsplit(str(href or "")).path.split("/")
            if part
        ]
    except Exception:
        return False

    if "applications" not in segments:
        return False

    idx = segments.index("applications")
    return idx > 0 and segments[idx - 1] == expected


def safe_application_cta_text(text: str) -> bool:
    compact = " ".join(str(text or "").casefold().split())
    return compact in {
        "postular",
        "postular ahora",
        "postular a este empleo",
        "postular a este trabajo",
        "aplicar",
        "apply",
        "apply now",
        "continuar",
        "continue",
        "reanudar",
        "retomar",
        "resume application",
        "completar postulación",
        "completar postulacion",
        "continue application",
    }


async def application_page_matches_job(page, expected_job_url: str) -> bool:
    expected = job_slug_from_url(expected_job_url)
    if not expected:
        return False

    candidates = [page.url]

    try:
        canonical = page.locator('link[rel="canonical"]')
        if await canonical.count():
            href = await canonical.first.get_attribute("href")
            if href:
                candidates.append(href)
    except Exception:
        pass

    try:
        actions = await page.locator("form[action]").evaluate_all(
            "els => els.map(el => el.action || el.getAttribute('action') || '')"
        )
        candidates.extend(str(value or "") for value in actions)
    except Exception:
        pass

    return any(job_slug_from_url(value) == expected for value in candidates)


def explicit_job_slug_from_url(url: str) -> str:
    """
    Extract a job slug ONLY from URL shapes that explicitly carry
    Get on Board job identity.

    Valid examples:

      /jobs/programming/my-job
      /empleos/programacion/my-job
      /jobs/my-job/applications/<id>

    Generic internal endpoints such as:

      /applications/<id>/visible
      /user_privacy_policies
      /listening

    deliberately return an empty string.
    """

    try:
        segments = [
            part.casefold()
            for part in urlsplit(
                str(url or "")
            ).path.split("/")
            if part
        ]

    except Exception:
        return ""

    if not segments:
        return ""

    # --------------------------------------------------------
    # Explicit job-specific application route:
    #
    # /jobs/<slug>/applications/<id>
    # /jobs/<slug>/applications/new
    #
    # We require jobs/empleos somewhere before "applications".
    # --------------------------------------------------------

    if "applications" in segments:

        idx = segments.index(
            "applications"
        )

        prefix = segments[:idx]

        if (
            idx > 0
            and (
                "jobs" in prefix
                or "empleos" in prefix
            )
        ):
            candidate = segments[
                idx - 1
            ]

            if candidate not in {
                "jobs",
                "empleos",
            }:
                return candidate

        # Generic /applications/... URL carries no job identity.
        return ""

    # --------------------------------------------------------
    # Normal vacancy URL.
    #
    # /jobs/<category>/<slug>
    # /empleos/<category>/<slug>
    # --------------------------------------------------------

    if (
        segments[0] in {
            "jobs",
            "empleos",
        }
        and len(segments) >= 3
    ):
        return segments[-1]

    return ""


async def trusted_application_transition_matches(
    page,
    expected_job_url: str,
) -> bool:
    """
    Validate identity after an already trusted transition.

    A job-specific application href is checked BEFORE navigation.
    Get on Board may later redirect that draft to generic internal
    application endpoints.

    Generic endpoints are absence of identity, NOT evidence of
    another vacancy.

    Only an explicit job-shaped URL with a different slug is a
    conflict.
    """

    expected = explicit_job_slug_from_url(
        expected_job_url
    )

    if not expected:
        # Expected URL itself should always be a real vacancy.
        expected = job_slug_from_url(
            expected_job_url
        )

    if not expected:
        print(
            "🛑 OFFER IDENTITY:"
            " no pude extraer slug objetivo."
        )
        return False

    candidates = [
        page.url
    ]

    # Canonical URL.
    try:
        canonical = page.locator(
            'link[rel="canonical"]'
        )

        if await canonical.count():

            href = (
                await canonical.first
                .get_attribute("href")
            )

            if href:
                candidates.append(
                    href
                )

    except Exception:
        pass

    # Forms may contain useful explicit job routes, but most are
    # generic internal actions. The strict parser below ignores
    # the latter.
    try:
        actions = await page.locator(
            "form[action]"
        ).evaluate_all(
            """
            els => els.map(
                el =>
                    el.action ||
                    el.getAttribute('action') ||
                    ''
            )
            """
        )

        candidates.extend(
            str(value or "")
            for value in actions
        )

    except Exception:
        pass

    explicit_observed = set()

    for value in candidates:

        slug = explicit_job_slug_from_url(
            value
        )

        if slug:
            explicit_observed.add(
                slug
            )

    # Strong positive identity.
    if expected in explicit_observed:

        conflicts = {
            slug
            for slug in explicit_observed
            if slug != expected
        }

        if conflicts:
            print(
                "🛑 OFFER IDENTITY explicit conflict:"
                f" expected={expected}"
                f" observed={sorted(explicit_observed)}"
            )
            return False

        print(
            "🛡️ OFFER IDENTITY explicit match:"
            f" {expected}"
        )

        return True

    # A DIFFERENT explicitly identified vacancy is a real conflict.
    conflicts = {
        slug
        for slug in explicit_observed
        if slug != expected
    }

    if conflicts:

        print(
            "🛑 OFFER IDENTITY explicit conflict:"
            f" expected={expected}"
            f" observed={sorted(conflicts)}"
        )

        return False

    # --------------------------------------------------------
    # No explicit job identity after redirect.
    #
    # This is normal for Get on Board generic application
    # internals. The transition that brought us here was already
    # validated using application_href_matches_job() or an exact
    # CTA from the target vacancy.
    # --------------------------------------------------------

    print(
        "🛡️ OFFER IDENTITY generic redirect:"
        f" expected={expected};"
        " no explicit competing job identity."
    )

    return True


async def already_applied(page) -> bool:
    body = (await page.locator("body").inner_text()).lower()
    return any(marker in body for marker in (
        "ver tu postulación",
        "ver tu postulacion",
        "view your application",
        "ya postulaste",
        "application submitted",
    ))


def _resolve_cached_cv_policy(
    decision,
    job_text: str,
) -> tuple[str | None, str | None, str | None]:
    """
    v0.6.11.5 CACHED CV POLICY MIGRATION.

    Recover only the deterministic family persisted in ``why``
    and resolve the CURRENT CV id for that same family/language.

    This helper intentionally supports only ``data`` and ``ops``,
    because those are the two families whose IDs were historically
    swapped.  It must never reinterpret AI/Python/Software decisions.
    """

    import re as _re

    from agentes.jobs.analyzer import FAMILIES
    from agentes.jobs.job_language_policy import (
        detect_job_language,
    )

    why = str(
        getattr(
            decision,
            "why",
            "",
        )
        or ""
    ).casefold()

    match = _re.search(
        r"\bfamily=(data|ops)\b",
        why,
    )

    if not match:
        return None, None, None

    family = match.group(1)

    language = detect_job_language(
        job_text
    )

    family_data = FAMILIES.get(
        family
    )

    if not isinstance(
        family_data,
        dict,
    ):
        return None, family, language

    expected = str(
        family_data.get(
            language,
            "",
        )
        or ""
    ).strip()

    if not expected:
        return None, family, language

    return expected, family, language


async def classify_application_entry_failure(
    page,
    expected_job_url: str,
) -> tuple[str, str]:
    """
    v0.6.11.6 APPLICATION ENTRY CLASSIFICATION.

    Do not send every missing CTA to HUMAN_REVIEW.

    JOB_UNAVAILABLE requires explicit page evidence.
    Otherwise a missing safe entry point is classified as
    APPLICATION_CTA_MISSING instead of pretending a human
    can necessarily resolve it.
    """

    try:
        body = await page.locator(
            "body"
        ).inner_text()
    except Exception:
        body = ""

    blob = " ".join(
        str(body or "").casefold().split()
    )

    current = str(
        getattr(
            page,
            "url",
            "",
        )
        or ""
    )

    closed_markers = (
        "esta oferta ya no está disponible",
        "esta oferta ya no esta disponible",
        "esta oferta no está disponible",
        "esta oferta no esta disponible",
        "esta vacante ya no está disponible",
        "esta vacante ya no esta disponible",
        "oferta cerrada",
        "vacante cerrada",
        "oferta finalizada",
        "proceso cerrado",
        "postulaciones cerradas",
        "ya no acepta postulaciones",
        "ya no se aceptan postulaciones",
        "job is no longer available",
        "job no longer available",
        "this job is no longer available",
        "position is no longer available",
        "applications are closed",
        "applications closed",
        "job has expired",
        "job expired",
        "position has been filled",
    )

    matched = next(
        (
            marker
            for marker in closed_markers
            if marker in blob
        ),
        None,
    )

    if matched:
        return (
            "JOB_UNAVAILABLE",
            (
                "JOB_UNAVAILABLE: la página indica "
                f"explícitamente cierre/no disponibilidad "
                f"({matched!r}). url={current}"
            ),
        )

    return (
        "APPLICATION_CTA_MISSING",
        (
            "APPLICATION_CTA_MISSING: no se encontró "
            "CTA ni ruta de aplicación segura para la "
            "oferta objetivo. "
            f"url={current}; expected={expected_job_url}"
        ),
    )


async def open_or_resume_application(page, expected_job_url: str) -> bool:
    """
    Inicia una postulación nueva o intenta reanudar un draft.
    Nunca realiza el submit final.
    """

    print("🔎 Buscando entrada a la postulación...")

    current = page.url.lower()

    # --------------------------------------------------------
    # 1. YA ESTAMOS DENTRO
    # --------------------------------------------------------

    if (
        "/applications/new" in current
        or "/applications/" in current
        or "job_application_preview=true" in current
    ):
        if not await trusted_application_transition_matches(
            page,
            expected_job_url,
        ):
            raise OfferIdentityMismatch(
                "La postulación abierta expone identidad de otra oferta."
            )
        print("♻️ Ya estamos dentro de una postulación.")
        return True

    # --------------------------------------------------------
    # 2. REVISAR LINKS DEL DOM
    # --------------------------------------------------------

    links = await page.locator("a[href]").evaluate_all(
        """
        els => els.map(a => ({
            href: a.href || '',
            text: (
                a.innerText ||
                a.textContent ||
                ''
            ).trim()
        }))
        """
    )

    application_links = []

    for link in links:
        href = link.get("href", "")
        text = link.get("text", "")

        if not href:
            continue

        low = href.lower()

        if "getonbrd.com" not in low:
            continue

        clean = (
            low
            .split("?")[0]
            .split("#")[0]
            .rstrip("/")
        )

        # Página genérica "Tus postulaciones".
        if clean == "https://www.getonbrd.com/applications":
            continue

        if (
            "/applications/new" in low
            or "/applications/" in low
            or "job_application_preview=true" in low
        ):
            if application_href_matches_job(href, expected_job_url):
                application_links.append({
                    "href": href,
                    "text": text,
                })

    if application_links:

        def priority(item):
            href = item["href"].lower()

            if "/edit" in href:
                return 0

            if "/applications/new" in href:
                return 1

            if "job_application_preview=true" in href:
                return 3

            return 2

        application_links.sort(
            key=priority
        )

        target = application_links[0]

        print(
            f"♻️ Reanudando draft/ruta existente:"
        )
        print(
            f"   {target['text'] or '(sin texto)'}"
        )
        print(
            f"   {target['href']}"
        )

        await page.goto(
            target["href"],
            wait_until="domcontentloaded",
            timeout=30000,
        )

        await page.wait_for_timeout(1200)

        await ensure_auth(page)

        if not await trusted_application_transition_matches(
            page,
            expected_job_url,
        ):
            raise OfferIdentityMismatch(
                "La ruta seleccionada expone identidad de otra oferta."
            )

        return True

    # --------------------------------------------------------
    # 3. BUSCAR CTA VISIBLE
    # --------------------------------------------------------

    controls = page.locator(
        "a, button"
    )

    positives = (
        "postular",
        "postula ahora",
        "aplicar",
        "apply",
        "apply now",
        "continuar",
        "continue",
        "reanudar",
        "retomar",
        "resume application",
        "completar postulación",
        "completar postulacion",
    )

    negatives = (
        "ver tu postulación",
        "ver tu postulacion",
        "view your application",
        "tus postulaciones",
    )

    for i in range(
        await controls.count()
    ):
        el = controls.nth(i)

        if not await el.is_visible():
            continue

        try:
            text = (
                await el.inner_text()
            ).strip()
        except Exception:
            continue

        compact = " ".join(
            text.split()
        )

        low = compact.lower()

        if not low:
            continue

        if any(
            x in low
            for x in negatives
        ):
            continue

        try:
            tag = (await el.evaluate("e => e.tagName.toLowerCase()"))
            href = (await el.get_attribute("href")) or ""
        except Exception:
            tag = ""
            href = ""

        # Anchors are safe only when their application URL belongs to the
        # current job. Buttons without an application href must use an exact,
        # short application CTA. This rejects job cards such as
        # "UX Engineer ... Postular".
        safe_cta = (
            application_href_matches_job(href, expected_job_url)
            if href
            else (tag == "button" and safe_application_cta_text(compact))
        )

        if safe_cta:
            print(
                f"🖱️ CTA: {compact}"
            )

            await el.scroll_into_view_if_needed()

            await el.click(
                timeout=10000
            )

            await page.wait_for_timeout(
                1200
            )

            await ensure_auth(page)

            if not await trusted_application_transition_matches(
                page,
                expected_job_url,
            ):
                raise OfferIdentityMismatch(
                    "El CTA expone identidad de otra oferta."
                )

            return True

    # --------------------------------------------------------
    # 4. CASO: "VER TU POSTULACIÓN"
    # --------------------------------------------------------

    for i in range(
        await controls.count()
    ):
        el = controls.nth(i)

        if not await el.is_visible():
            continue

        try:
            text = (
                await el.inner_text()
            ).strip()
        except Exception:
            continue

        low = " ".join(
            text.lower().split()
        )

        if (
            "ver tu postulación" in low
            or "ver tu postulacion" in low
            or "view your application" in low
        ):
            print(
                "ℹ️ Get on Board muestra "
                "'Ver tu postulación'."
            )

            print(
                "   Puede ser una postulación ya enviada "
                "o un draft sin CTA editable."
            )

            return False

    # --------------------------------------------------------
    # 5. DIAGNÓSTICO
    # --------------------------------------------------------

    print()
    print(
        "⚠️ No encontré CTA ni ruta segura "
        "para iniciar/reanudar."
    )

    interesting = []

    for link in links:
        text = " ".join(
            link.get(
                "text",
                "",
            ).split()
        )

        href = link.get(
            "href",
            "",
        )

        blob = (
            text + " " + href
        ).lower()

        if any(
            word in blob
            for word in (
                "postul",
                "application",
                "apply",
                "resume",
            )
        ):
            interesting.append(
                (text, href)
            )

    if interesting:
        print(
            "🔍 Links relacionados:"
        )

        for text, href in interesting[:20]:
            print(
                f"   • {text or '(sin texto)'}"
            )
            print(
                f"     {href}"
            )

    return False


async def final_audit(page, decision):
    if decision_name(decision) != "APPLY":
        raise RuntimeError("AUDIT: decision != APPLY")

    unsupported = getattr(decision, "unsupported_claims", []) or []
    if unsupported:
        print("⚠️ AUDIT WARNING: unsupported_claims reportados:")
        for claim in unsupported:
            print(f"   • {claim}")
        print(
            "   Se mantienen los guardrails de evidencia; "
            "unsupported_claims por sí solo no bloquea el submit."
        )

    if await detect_stage(page) != "REVIEW":
        raise RuntimeError("AUDIT: no estamos en REVIEW")

    print("🛡️ Final audit: PASS")


async def resolve_repair_step(page) -> str | None:
    """Resolve the editable step that must be repaired.

    Canonical Get on Board step wins.  Agent stage detection is only a
    fallback for pages where the server does not expose the step directly.
    """

    repair_step = await resolve_gob_step(page)

    if repair_step:
        return repair_step

    return repair_step_from_stage(
        await detect_stage(page)
    )


async def learn_form_constraints(
    page,
    decision,
) -> dict:
    """
    Learn server-side form restrictions after Get on Board
    rejects a submit.

    These restrictions are persisted with the JobDecision and
    reused by REPAIR MODE.
    """

    body = (
        await page.locator(
            "body"
        ).inner_text()
    ).casefold()

    current = getattr(
        decision,
        "form_constraints",
        {},
    ) or {}

    # --------------------------------------------------------
    # Recordar la etapa exacta a la que GOB devolvió el
    # formulario después de rechazar el submit.
    # --------------------------------------------------------

    learned_repair_step = await resolve_repair_step(
        page
    )

    constraints = (
        dict(current)
        if isinstance(
            current,
            dict,
        )
        else {}
    )

    if learned_repair_step:

        constraints[
            "repair_step"
        ] = learned_repair_step

        print(
            "🧭 Repair step aprendido: "
            f"{learned_repair_step}"
        )

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
        x in body
        for x in english_markers
    ):
        constraints[
            "motivation_language"
        ] = "en"

    elif any(
        x in body
        for x in spanish_markers
    ):
        constraints[
            "motivation_language"
        ] = "es"

    reason = page.locator(
        "#reason-to-apply"
    )

    if await reason.count():

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

        try:
            if min_attr:
                constraints[
                    "motivation_min_chars"
                ] = int(min_attr)
        except Exception:
            pass

        try:
            if max_attr:
                constraints[
                    "motivation_max_chars"
                ] = int(max_attr)
        except Exception:
            pass

    setattr(
        decision,
        "form_constraints",
        constraints,
    )

    print(
        "🧠 Restricciones de formulario aprendidas:"
    )
    print(
        f"   {constraints}"
    )

    return constraints


async def verify_submit_externally(
    page,
    decision,
    *,
    attempts: int = 3,
) -> str:
    """Read-only, eventually-consistent verification of the final submit.

    The irreversible submit click is never retried. Only the original job
    page is re-read because Get on Board can take a few seconds to expose
    the final "Ver tu postulación" state.
    """
    job = getattr(decision, "job", None)
    if isinstance(job, dict):
        job_url = str(job.get("url") or "")
    else:
        job_url = str(getattr(job, "url", "") or "")

    if not job_url:
        print("⚠️ Verificación externa: JobDecision no contiene job.url")
        return "UNKNOWN"

    attempts = max(1, min(int(attempts or 1), 5))
    waits_ms = (1500, 2500, 4000, 5000, 5000)

    success_markers = (
        "ver tu postulación",
        "ver tu postulacion",
        "view your application",
        "ya postulaste",
        "application submitted",
        "postulación enviada",
        "postulacion enviada",
    )
    draft_markers = (
        "tienes una postulación por enviar",
        "tienes una postulacion por enviar",
        "resume application",
        "continuar postulación",
        "continuar postulacion",
        "aún no ha sido enviada",
        "aun no ha sido enviada",
        "aún sin enviar",
        "aun sin enviar",
    )

    verifier = await page.context.new_page()
    last_state = "UNKNOWN"
    print()
    print("🔍 Verificación externa post-submit (read-only):")

    try:
        for attempt in range(1, attempts + 1):
            try:
                await verifier.goto(
                    job_url,
                    wait_until="domcontentloaded",
                    timeout=30000,
                )
                await verifier.wait_for_timeout(waits_ms[attempt - 1])
                body = (await verifier.locator("body").inner_text()).casefold()

                success = any(marker in body for marker in success_markers)
                draft = any(marker in body for marker in draft_markers)

                if success and not draft:
                    last_state = "SUBMITTED"
                elif draft:
                    last_state = "DRAFT"
                else:
                    last_state = "UNKNOWN"

                print(
                    f"   intento {attempt}/{attempts}: "
                    f"success={success} draft={draft} state={last_state}"
                )

                if last_state == "SUBMITTED":
                    print("✅ Get on Board confirma 'Ver tu postulación'.")
                    return "SUBMITTED"
            except Exception as exc:
                last_state = "UNKNOWN"
                print(
                    f"   intento {attempt}/{attempts}: "
                    f"probe_error={type(exc).__name__}: {exc}"
                )

        if last_state == "DRAFT":
            print(
                "⚠️ Get on Board siguió reportando un draft "
                "después de todos los probes read-only."
            )
            return "DRAFT"

        print(
            "⚠️ La verificación externa siguió ambigua después "
            "de todos los probes read-only."
        )
        return "UNKNOWN"
    finally:
        await verifier.close()


def validation_reject_result(
    decision,
    post_click_stage: str,
) -> str:
    """
    Allow one repair cycle for a server-side validation rejection.

    A second rejection at the same editable step is quarantined
    as HUMAN_REVIEW. There is never a third automatic submit.
    """

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

    reject_step = str(
        constraints.get(
            "repair_step",
            "",
        )
        or repair_step_from_stage(
            post_click_stage
        )
        or "unknown"
    ).casefold()

    previous_step = str(
        constraints.get(
            "last_validation_reject_step",
            "",
        )
        or ""
    ).casefold()

    try:
        previous_count = int(
            constraints.get(
                "validation_reject_count",
                0,
            )
            or 0
        )

    except Exception:
        previous_count = 0

    if previous_step == reject_step:
        count = previous_count + 1

    else:
        count = 1

    constraints[
        "last_validation_reject_step"
    ] = reject_step

    constraints[
        "validation_reject_count"
    ] = count

    setattr(
        decision,
        "form_constraints",
        constraints,
    )

    try:
        max_rejects = int(
            __import__("os").getenv(
                "JOB_MAX_VALIDATION_REPAIRS",
                "5",
            )
        )
    except Exception:
        max_rejects = 5

    max_rejects = max(
        2,
        min(
            max_rejects,
            8,
        ),
    )

    print(
        "🧯 VALIDATION CIRCUIT: "
        f"step={reject_step} "
        f"count={count}/{max_rejects}"
    )

    if count >= max_rejects:

        constraints[
            "human_review_reason"
        ] = (
            "REPAIR_EXHAUSTED: "
            "Get on Board rechazó "
            f"{count} veces la postulación "
            "en "
            f"step={reject_step}; "
            "se agotó el presupuesto "
            "de reparación automática."
        )

        setattr(
            decision,
            "form_constraints",
            constraints,
        )

        print(
            "🛑 REPAIR_EXHAUSTED → "
            "HUMAN_REVIEW"
        )

        return "HUMAN_REVIEW"

    return "REQUEUE_FORM_INVALID"


async def submit_review(page, decision) -> str:
    """
    Envía una postulación que ya pasó todos los guardrails y se
    encuentra en REVIEW.

    Nunca reintenta el submit automáticamente. Si Get on Board abre
    su confirm() nativo estándar de Política de Privacidad, se acepta
    una sola vez dentro de la misma intención de submit. Cualquier
    diálogo desconocido se descarta y devuelve CONFIRMATION_REQUIRED.
    """

    # --------------------------------------------------------
    # 1. Evidencia previa
    # --------------------------------------------------------

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    shot = (
        ROOT
        / "logs"
        / f"pre-submit-{stamp}.png"
    )

    await page.screenshot(
        path=str(shot),
        full_page=True,
    )

    print(f"📸 {shot}")

    # --------------------------------------------------------
    # 2. Selector EXACTO observado en Get on Board
    #
    # Preferimos el botón del cuerpo (#1).
    # #2 es el duplicado del sidebar.
    # --------------------------------------------------------

    target = page.locator(
        "#send-application-btn-1"
    )

    if (
        await target.count() == 0
        or not await target.is_visible()
    ):
        print(
            "ℹ️ #send-application-btn-1 "
            "no disponible; probando sidebar."
        )

        target = page.locator(
            "#send-application-btn-2"
        )

    if await target.count() == 0:
        raise RuntimeError(
            "No existe ninguno de los botones "
            "finales conocidos de Get on Board."
        )

    if not await target.is_visible():
        raise RuntimeError(
            "El botón final existe pero no está visible."
        )

    if not await target.is_enabled():
        raise RuntimeError(
            "El botón final está deshabilitado."
        )

    # --------------------------------------------------------
    # 3. Guardrail del texto/value
    # --------------------------------------------------------

    value = (
        await target.get_attribute("value")
        or ""
    ).strip()

    normalized = (
        value
        .lower()
        .replace("ó", "o")
    )

    allowed = {
        "enviar postulacion ahora",
        "submit application now",
        "send application now",
    }

    if normalized not in allowed:
        raise RuntimeError(
            "SUBMIT GUARDRAIL: "
            f"value inesperado: {value!r}"
        )

    print()
    print(
        f"🚀 SUBMIT ÚNICO PREPARADO: {value}"
    )

    # --------------------------------------------------------
    # 4. ÚNICA INTENCIÓN DE SUBMIT + diálogo nativo conocido
    #
    # Get on Board puede abrir un window.confirm() con su aviso
    # estándar de Política de Privacidad. Playwright descarta los
    # dialogs automáticamente si no hay listener, lo que deja el
    # draft "Aún no enviado". Por eso instalamos el listener ANTES
    # del click.
    #
    # Sólo se acepta el texto de privacidad conocido. Cualquier
    # diálogo distinto se descarta y bloquea la ejecución.
    # --------------------------------------------------------

    dialog_state = {
        "seen": False,
        "accepted": False,
        "unknown": None,
    }

    async def _submit_dialog_guard(dialog):
        message = (dialog.message or "").strip()
        dialog_state["seen"] = True

        if is_known_privacy_submit_confirmation(message):
            dialog_state["accepted"] = True
            print()
            print(
                "🛡️ Confirmación nativa estándar de "
                "Política de Privacidad reconocida."
            )
            await dialog.accept()
            print(
                "✅ Confirmación de privacidad aceptada "
                "UNA sola vez."
            )
            return

        dialog_state["unknown"] = message or "<sin texto>"
        print()
        print(
            "⛔ Diálogo nativo desconocido: NO se acepta."
        )
        print(
            "   " + dialog_state["unknown"][:500].replace("\n", " | ")
        )
        await dialog.dismiss()

    page.on("dialog", _submit_dialog_guard)

    try:
        await target.scroll_into_view_if_needed()

        await target.click(
            timeout=10000
        )

        print(
            "🖱️ Intención de submit ejecutada UNA sola vez."
        )

        # IMPORTANTE:
        # desde este punto JAMÁS hacemos retry automático.
        await page.wait_for_timeout(
            3000
        )
    finally:
        page.remove_listener("dialog", _submit_dialog_guard)

    if dialog_state["unknown"]:
        return "CONFIRMATION_REQUIRED"

    # --------------------------------------------------------
    # 5. Confirmación posterior
    # --------------------------------------------------------

    body = (
        await page.locator("body").inner_text()
    ).lower()

    success_markers = (
        "postulación enviada",
        "postulacion enviada",
        "postulación recibida",
        "postulacion recibida",
        "application submitted",
        "application sent",
        "postulación fue enviada",
        "postulacion fue enviada",
    )

    if any(
        marker in body
        for marker in success_markers
    ):
        return "SUBMITTED"

    # --------------------------------------------------------
    # VALIDATION FAILURE
    #
    # El servidor puede aceptar el click pero rechazar la
    # postulación por campos incompletos y devolvernos a
    # PROFILE/BASIC/CUSTOM.
    #
    # Esto NO es un submit ambiguo: sabemos que NO se envió.
    # --------------------------------------------------------

    validation_markers = (
        "tu postulación tiene errores",
        "tu postulacion tiene errores",
        "revisa los campos marcados",
        "your application has errors",
        "please review the fields",
        "debe tener entre 50 y 1000 caracteres",
        "must be between 50 and 1000 characters",
    )

    post_click_stage = await detect_stage(
        page
    )

    validation_failed = (
        post_click_stage
        in {
            "PROFILE",
            "BASIC",
            "CUSTOM",
        }
        or any(
            marker in body
            for marker in validation_markers
        )
    )

    if validation_failed:

        await learn_form_constraints(
            page,
            decision,
        )

        print()
        print(
            "🧰 SUBMIT rechazado por validación "
            "del formulario."
        )
        print(
            f"↩️ Get on Board devolvió a: "
            f"{post_click_stage}"
        )
        print(
            "🔁 Se envía a la cola de reparación "
            "DRY RUN; NO se repite el submit."
        )

        return validation_reject_result(
            decision,
            post_click_stage,
        )

    # --------------------------------------------------------
    # VERIFICACIÓN EXTERNA READ-ONLY
    # --------------------------------------------------------

    external = await verify_submit_externally(
        page,
        decision,
    )

    if external == "SUBMITTED":
        return "SUBMITTED"

    # Si la oferta original aún reporta un draft pero no
    # vimos una validación explícita, mantenemos ambigüedad.
    # Nunca hacemos un segundo click automáticamente.
    if external == "DRAFT":
        print(
            "🛑 El submit no pudo confirmarse y "
            "la oferta todavía expone un draft."
        )
        return "SUBMIT_UNKNOWN"

    # También es una señal fuerte que desaparezcan
    # ambos botones de envío.
    send1 = page.locator(
        "#send-application-btn-1"
    )

    send2 = page.locator(
        "#send-application-btn-2"
    )

    visible1 = (
        await send1.count() > 0
        and await send1.is_visible()
    )

    visible2 = (
        await send2.count() > 0
        and await send2.is_visible()
    )

    if not visible1 and not visible2:
        print(
            "⚠️ Los controles de envío desaparecieron, "
            "pero no encontré una confirmación textual "
            "inequívoca."
        )
        print(
            "🛑 Se conserva estado ambiguo para evitar "
            "un falso SUBMITTED."
        )

        return "SUBMIT_UNKNOWN"

    # Puede haberse abierto una confirmación/modal.
    modal_texts = []

    modals = page.locator(
        """
        .modal:visible,
        [role='dialog']:visible
        """
    )

    for i in range(
        await modals.count()
    ):
        try:
            text = (
                await modals.nth(i).inner_text()
            ).strip()

            if text:
                modal_texts.append(text)

        except Exception:
            pass

    if modal_texts:
        print()
        print(
            "⚠️ Apareció una confirmación/modal "
            "después del click:"
        )

        for text in modal_texts:
            print(
                "   "
                + text[:1000].replace(
                    "\n",
                    " | ",
                )
            )

        # NO pulsamos nada más automáticamente.
        return "CONFIRMATION_REQUIRED"

    # El click pudo funcionar aunque el frontend
    # no entregue una señal conocida.
    return "SUBMIT_UNKNOWN"


async def safe_click_next(page):
    """
    Usa click_next normal.

    Si Get on Board mantiene el botón animándose/re-renderizándose
    y Playwright no logra scroll_into_view_if_needed(), usamos
    un click DOM como fallback.

    Esta función NUNCA se utiliza para el submit final.
    """

    try:
        return await click_next(
            page
        )

    except Exception as exc:

        msg = str(exc).lower()

        recoverable = (
            "scroll_into_view_if_needed" in msg
            or "waiting for element to be stable" in msg
            or "timeout" in msg
        )

        if not recoverable:
            raise

        print()
        print(
            "♻️ NEXT inestable; activando fallback DOM seguro"
        )

        controls = page.locator(
            "button[type='submit'], input[type='submit']"
        )

        target = None

        for i in range(
            await controls.count()
        ):
            el = controls.nth(i)

            try:
                if not await el.is_visible():
                    continue

                if not await el.is_enabled():
                    continue

                try:
                    label = (
                        await el.inner_text()
                    ).strip()
                except Exception:
                    label = (
                        await el.get_attribute(
                            "value"
                        )
                        or ""
                    ).strip()

                low = " ".join(
                    label.lower().split()
                )

                expected = (
                    "siguiente",
                    "next",
                    "continuar",
                    "continue",
                    "revisar",
                    "review",
                )

                if any(
                    x in low
                    for x in expected
                ):
                    target = el
                    break

            except Exception:
                continue

        # En PROFILE/BASIC/CUSTOM normalmente hay un único
        # submit. Si no reconocimos el texto, aceptamos el
        # único submit visible.
        if target is None:

            visible = []

            for i in range(
                await controls.count()
            ):
                el = controls.nth(i)

                try:
                    if (
                        await el.is_visible()
                        and await el.is_enabled()
                    ):
                        visible.append(
                            el
                        )
                except Exception:
                    pass

            if len(visible) == 1:
                target = visible[0]

        if target is None:
            raise RuntimeError(
                "NEXT fallback: no encontré "
                "un control de avance seguro."
            )

        print(
            "🖱️ NEXT fallback DOM"
        )

        # Evita la espera de estabilidad que provocó
        # el fallo en GeoVictoria.
        await target.evaluate(
            "(el) => el.click()"
        )

        await page.wait_for_timeout(
            1200
        )


async def enter_form_repair_mode(
    page,
    repair_step: str = "basic",
    allow_profile_fallback: bool = False,
) -> str:
    """
    Force an existing Get on Board draft back into an
    editable form step.

    Used only for REQUEUE_FORM_INVALID.

    Priority:
      1. explicit edit link already present in DOM
      2. construct /edit from the current application URL
      3. force the requested editable ?step=...

    Never submits anything.
    """

    repair_step = str(
        repair_step
        or "basic"
    ).strip().casefold()

    if repair_step not in {
        "experience",
        "basic",
        "custom",
    }:
        print(
            "⚠️ repair_step desconocido: "
            f"{repair_step!r}; usando basic."
        )
        repair_step = "basic"

    print()
    print(
        "🧰 REPAIR MODE: "
        f"step={repair_step}"
    )
    print(
        "🔎 Buscando formulario editable..."
    )

    # --------------------------------------------------------
    # 1. Prefer an explicit edit/basic URL from the DOM.
    # --------------------------------------------------------

    links = await page.locator(
        "a[href]"
    ).evaluate_all(
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

    candidates = []

    for item in links:

        href = str(
            item.get("href")
            or ""
        )

        low = href.casefold()

        if (
            "/applications/" in low
            and "/edit" in low
        ):
            candidates.append(
                href
            )

    # Prefer an edit URL that already points to the requested step.
    repair_url = next(
        (
            href
            for href in candidates
            if f"step={repair_step}" in href.casefold()
        ),
        None,
    )

    if repair_url is None and candidates:
        repair_url = candidates[0]

    # --------------------------------------------------------
    # 2. Construct from current application URL.
    # --------------------------------------------------------

    if repair_url is None:

        current = page.url.split(
            "#",
            1,
        )[0]

        current = current.split(
            "?",
            1,
        )[0]

        if "/applications/" not in current:
            raise RuntimeError(
                "REPAIR MODE: no estoy en una URL "
                "de aplicación."
            )

        # v0.6.11.4:
        # /applications/new already is the editable endpoint.
        # Appending /edit creates an invalid phantom route.
        if current.endswith(
            "/applications/new"
        ):
            repair_url = current

        elif current.endswith(
            "/edit"
        ):
            repair_url = current

        else:
            repair_url = (
                current
                + "/edit"
            )

    # v0.6.11.4:
    # Never navigate to the invalid /applications/new/edit shape.
    if "/applications/new/edit" in repair_url.casefold():

        repair_url = repair_url.replace(
            "/applications/new/edit",
            "/applications/new",
        )

        print(
            "🧹 LEGACY ROUTE FIX: "
            "/applications/new/edit → /applications/new"
        )

    # --------------------------------------------------------
    # 3. ALWAYS force the requested editable step.
    #
    # An /edit URL without ?step=... can render a generic
    # edit/preview state that detect_stage cannot classify.
    # --------------------------------------------------------

    repair_url = repair_url.split(
        "#",
        1,
    )[0]

    if "?" in repair_url:

        base, query = repair_url.split(
            "?",
            1,
        )

        parts = [
            part
            for part in query.split("&")
            if part
            and not part.casefold().startswith(
                "step="
            )
        ]

        parts.insert(
            0,
            f"step={repair_step}",
        )

        repair_url = (
            base
            + "?"
            + "&".join(parts)
        )

    else:
        repair_url = (
            repair_url
            + f"?step={repair_step}"
        )

    print(
        "🔧 Abriendo formulario reparable:"
    )
    print(
        f"   {repair_url}"
    )

    await page.goto(
        repair_url,
        wait_until="domcontentloaded",
        timeout=30000,
    )

    await page.wait_for_timeout(
        1200
    )

    stage = await detect_stage(
        page
    )

    print(
        f"🔎 Stage tras entrar a REPAIR MODE: "
        f"{stage}"
    )

    # --------------------------------------------------------
    # v0.6.11.3 LEGACY PROFILE FALLBACK.
    #
    # Some historical drafts accept ?step=experience while no
    # longer exposing an editable PROFILE DOM.  For a pure
    # CV-language repair we may safely continue from BASIC,
    # because BASIC is where the actual CV selection is changed.
    #
    # Revalidation does NOT get this exception: if PROFILE must
    # be revalidated, absence of that form remains a blocker.
    # --------------------------------------------------------

    if (
        repair_step == "experience"
        and stage != "PROFILE"
        and allow_profile_fallback
    ):
        print(
            "🧭 LEGACY PROFILE: "
            "experience no es editable; "
            "fallback seguro a BASIC para reparar CV."
        )

        base = repair_url.split(
            "?",
            1,
        )[0]

        query = (
            repair_url.split(
                "?",
                1,
            )[1]
            if "?" in repair_url
            else ""
        )

        parts = [
            part
            for part in query.split("&")
            if part
            and not part.casefold().startswith(
                "step="
            )
        ]

        parts.insert(
            0,
            "step=basic",
        )

        basic_url = (
            base
            + "?"
            + "&".join(parts)
        )

        print(
            "🔧 Legacy fallback:"
        )
        print(
            f"   {basic_url}"
        )

        await page.goto(
            basic_url,
            wait_until="domcontentloaded",
            timeout=30000,
        )

        await page.wait_for_timeout(
            1200
        )

        stage = await detect_stage(
            page
        )

        print(
            "🔎 Stage tras fallback BASIC: "
            f"{stage}"
        )

    if stage not in {
        "PROFILE",
        "BASIC",
        "CUSTOM",
    }:
        raise RuntimeError(
            "REPAIR_MODE_UNEDITABLE: "
            f"requested={repair_step}; "
            f"stage={stage}; "
            f"url={page.url}"
        )

    return stage


async def wait_for_custom_fields_settle(
    page,
    timeout_ms: int = 5000,
    interval_ms: int = 300,
    stable_samples: int = 3,
):
    """
    v0.6.11.

    A CUSTOM page may initially expose zero controls while
    client-side rendering is still mounting the real questions.
    Never trust the first zero-field extraction.
    """

    rounds = max(
        1,
        timeout_ms // max(
            interval_ms,
            1,
        ),
    )

    previous = None
    stable = 0
    last_fields = []

    for index in range(
        rounds
    ):

        fields = await extract_custom_fields(
            page
        )

        last_fields = fields

        signature = tuple(
            (
                str(
                    field.get("field_key")
                    or ""
                ),
                str(
                    field.get("kind")
                    or ""
                ),
                bool(
                    field.get("required")
                ),
                tuple(
                    (
                        str(
                            option.get("id")
                            or ""
                        ),
                        str(
                            option.get("value")
                            or ""
                        ),
                        str(
                            option.get("label")
                            or ""
                        ),
                    )
                    for option in (
                        field.get("options")
                        or []
                    )
                    if isinstance(
                        option,
                        dict,
                    )
                ),
            )
            for field in fields
        )

        if signature == previous:
            stable += 1

        else:
            previous = signature
            stable = 1

        elapsed = (
            (index + 1)
            * interval_ms
        )

        if (
            fields
            and stable >= stable_samples
        ):

            print(
                "🧩 CUSTOM DOM estable: "
                f"{len(fields)} campo(s) "
                f"tras ~{elapsed}ms"
            )

            return fields

        if (
            not fields
            and stable >= stable_samples
            and elapsed >= 3600
        ):

            print(
                "🧩 CUSTOM DOM estable "
                "sin campos tras "
                f"~{elapsed}ms"
            )

            return []

        await page.wait_for_timeout(
            interval_ms
        )

    print(
        "⚠️ CUSTOM DOM settle agotado; "
        "uso última extracción: "
        f"{len(last_fields)} campo(s)"
    )

    return last_fields


async def complete_application(
    page,
    job_text: str,
    decision,
    submit: bool,
    repair_mode: bool = False,
) -> str:

    editable_stage_seen = False

    for step in range(1, 61):

        stage = await detect_stage(
            page
        )

        print(
            f"\n──────── FORM STEP {step}: "
            f"{stage} ────────"
        )

        if stage == "PROFILE":

            editable_stage_seen = True

            await fill_profile(
                page,
                job_text,
            )

            await safe_click_next(
                page
            )

            continue

        if stage == "BASIC":

            editable_stage_seen = True

            await fill_basic(
                page,
                job_text,
                decision,
            )

            await safe_click_next(
                page
            )

            continue

        if stage == "CUSTOM":

            editable_stage_seen = True

            fields = (
                await wait_for_custom_fields_settle(
                    page
                )
            )

            print(
                f"🧩 {len(fields)} campo(s) extra"
            )

            answers = await answer_custom_fields(
                fields,
                job_text,
                decision,
            )

            blockers = await fill_custom_fields(
                page,
                fields,
                answers,
            )

            if blockers:

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

                details = " | ".join(
                    (
                        f"{str(question or 'CUSTOM')[:240]}: "
                        f"{str(reason or 'sin razón')[:500]}"
                    )
                    for question, reason
                    in blockers
                )

                constraints[
                    "repair_step"
                ] = "custom"

                constraints[
                    "repair_step_source"
                ] = "human_blocker"

                constraints[
                    "human_review_reason"
                ] = (
                    "CUSTOM_BLOCKER: "
                    + details[:1800]
                )

                setattr(
                    decision,
                    "form_constraints",
                    constraints,
                )

                print(
                    "🧭 repair_step actualizado "
                    "por HUMAN_REVIEW: custom"
                )

                print(
                    "🛑 HUMAN_REVIEW"
                )

                for question, reason in blockers:

                    print(
                        f"• {question}\n  {reason}"
                    )

                return "HUMAN_REVIEW"

            await safe_click_next(
                page
            )

            continue

        if stage == "REVIEW":

            if (
                repair_mode
                and not editable_stage_seen
            ):

                raise RuntimeError(
                    "REPAIR MODE llegó a REVIEW "
                    "sin haber reparado ninguna "
                    "etapa editable."
                )

            if not submit:

                print(
                    "🛑 DRY RUN: REVIEW listo, "
                    "no se envía."
                )

                if repair_mode:

                    print(
                        "✅ REPAIR MODE completado: "
                        "se recorrió al menos una "
                        "etapa editable."
                    )

                return "DRY_RUN_READY"

            await final_audit(
                page,
                decision,
            )

            submit_result = await submit_review(
                page,
                decision,
            )

            # v0.6.11.13 — STICKY APPLICATION SOLVER
            #
            # REQUEUE_FORM_INVALID means we KNOW the submit did
            # NOT happen: Get on Board explicitly rejected the
            # form and returned to an editable stage.
            #
            # In that one reversible case, stay on THIS
            # application instead of closing it and waiting for
            # a later daemon cycle.
            #
            # SUBMIT_UNKNOWN / CONFIRMATION_REQUIRED are NOT
            # retried here.

            if (
                submit_result
                == "REQUEUE_FORM_INVALID"
            ):

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

                repair_step = str(
                    constraints.get(
                        "repair_step",
                        "",
                    )
                    or constraints.get(
                        "last_validation_reject_step",
                        "",
                    )
                    or "custom"
                ).casefold()

                count = int(
                    constraints.get(
                        "validation_reject_count",
                        1,
                    )
                    or 1
                )

                print()
                print(
                    "🧲 STICKY REPAIR:"
                    f" intento={count}"
                    f" step={repair_step}"
                )
                print(
                    "   Mantengo esta misma postulación "
                    "abierta y la reparo ahora."
                )

                await enter_form_repair_mode(
                    page,
                    repair_step=repair_step,
                )

                repair_mode = True
                editable_stage_seen = False

                continue

            return submit_result

        raise RuntimeError(
            f"Stage desconocido: {stage}"
        )

    raise RuntimeError(
        "Máximo de pasos del formulario "
        "alcanzado."
    )



def should_skip_record(
    row,
    submit: bool,
    targeted: bool = False,
    revalidate: bool = False,
) -> bool:
    if not row:
        return False

    status = row["status"]

    # Terminal/safety states are never reopened implicitly.
    if status in {
        "SUBMITTED",
        "ALREADY_APPLIED",
        "SKIP",

        # Irreversible/safety quarantine.
        #
        # The final submit may already have happened. These rows
        # MUST NOT be reopened by discovery, repair or dry-run.
        "SUBMIT_UNKNOWN",
        "CONFIRMATION_REQUIRED",
        "AUTH_REQUIRED",
    }:
        return True

    # v0.6.11.10 — SELECTIVE HUMAN_REVIEW RE-EVALUATION
    #
    # REVIEW remains periodically reversible.
    #
    # HUMAN_REVIEW is selected by queued_retry_urls() only when its
    # last_error explicitly identifies a retryable technical condition
    # such as NEXT_TRANSITION_STALLED.
    #
    # CUSTOM_BLOCKER / REPAIR_EXHAUSTED / factual unknowns remain frozen
    # until CandidateTruth/policy changes or an explicit targeted
    # revalidation is requested.
    #
    # The irreversible lane still accepts DRY_RUN_READY only.
    if status in {
        "REVIEW",
        "HUMAN_REVIEW",
    }:
        return bool(submit)

    if status == "DRY_RUN_READY" and not submit:
        # A READY row is normally stable and skipped in dry-run.
        # Explicit --url --revalidate is the one safe exception: it
        # forces the existing draft back through editable stages before
        # it may remain READY.
        return not (targeted and revalidate)

    return False


async def run_loop(
    limit: int,
    submit: bool,
    scrolls: int,
    target_url: str | None = None,
    revalidate: bool = False,
):

    if revalidate and (submit or not target_url):
        raise RuntimeError(
            "--revalidate requiere --dry-run y --url. "
            "Nunca se ejecuta en submit ni sobre backlog masivo."
        )

    # ========================================================
    # IRREVERSIBLE ACTION GATE
    #
    # --submit by itself is NOT sufficient.
    # The caller must explicitly arm the run.
    # ========================================================

    if submit:

        armed = (
            os.environ
            .get(
                "AGENT_SUBMIT_ARMED",
                "",
            )
            .strip()
            .upper()
        )

        if armed != "YES":
            raise RuntimeError(
                "SUBMIT bloqueado: falta "
                "AGENT_SUBMIT_ARMED=YES"
            )

        print()
        print(
            "🔐 SUBMIT ARMADO explícitamente"
        )
        print(
            "🛡️ Sólo DRY_RUN_READY pueden enviarse"
        )

    settings = Settings()
    session = await BrowserSession.connect_cdp(settings.brave_cdp_url)

    try:
        # El loop usa SU PROPIA pestaña.
        # Así tus clicks manuales en Brave no destruyen
        # el contexto que está usando el agente.
        browser = getattr(
            session,
            "browser",
            None,
        )

        if (
            not browser
            or not browser.contexts
        ):
            raise RuntimeError(
                "No encontré un BrowserContext de Brave."
            )

        context = browser.contexts[0]

        page = await context.new_page()

        print(
            "🧠 Pestaña dedicada del Job Agent creada"
        )

        # ----------------------------------------------------
        # v0.4.1 — COLA PERSISTENTE PRIMERO
        # ----------------------------------------------------

        if target_url:
            target_row = load_record(target_url)
            selected_url = (
                target_row["url"]
                if target_row
                else canonical_url(target_url)
            )
            jobs = [selected_url]

            print()
            print("🎯 TARGET EXPLÍCITO")
            print("=" * 72)
            print(selected_url)
            print(
                "⏩ Backlog/discovery omitidos para esta prueba."
            )

        else:
            queued = queued_retry_urls(
                submit=submit,
            )

            if submit:
                # Irreversible lane consumes only the READY queue.
                jobs = queued[:limit]

                if queued:
                    print()
                    print("📦 READY PARA SUBMIT")
                    print("=" * 72)
                    print(f"DRY_RUN_READY pendientes: {len(queued)}")
                    print(f"Procesaremos ahora: {len(jobs)}")

            else:
                # PREP must never be starved by a historical ERROR backlog.
                # Spend at most half the lane repairing and reserve the rest
                # for genuinely new, unseen jobs discovered right now.
                repair_budget = min(
                    len(queued),
                    max(1, limit // 2),
                ) if queued else 0

                jobs = list(queued[:repair_budget])
                seen = {canonical_url(value) for value in jobs}

                if queued:
                    print()
                    print("📦 PREP MIXTO: REPAIR + DISCOVERY")
                    print("=" * 72)
                    print(f"Pendientes recuperables elegibles: {len(queued)}")
                    print(f"Presupuesto de reparación: {repair_budget}/{limit}")

                discovered = await discover_jobs(
                    page,
                    scrolls=scrolls,
                )

                for candidate in discovered:
                    if len(jobs) >= limit:
                        break

                    canonical = canonical_url(candidate)
                    if canonical in seen:
                        continue

                    # Existing rows are handled by their persistent queue or
                    # are terminal. Discovery capacity is reserved for unseen
                    # jobs, preventing fresh ERROR rows from bypassing cooldown.
                    if load_record(candidate) is not None:
                        continue

                    jobs.append(candidate)
                    seen.add(canonical)

                if queued:
                    print(
                        f"🆕 Nuevas ofertas añadidas al ciclo: "
                        f"{max(0, len(jobs) - repair_budget)}"
                    )

        print()
        print("🤖 JOB LOOP")
        print("=" * 72)
        print(f"Modo: {'SUBMIT' if submit else 'DRY_RUN'}")
        print(f"Ofertas descubiertas: {len(jobs)}")
        print(f"Límite de esta pasada: {limit}")

        handled = 0

        for index, url in enumerate(jobs, 1):
            if handled >= limit:
                break

            row = load_record(url)

            if (
                submit
                and (
                    not row
                    or row["status"]
                    != "DRY_RUN_READY"
                )
            ):
                print(
                    "\n🛑 SUBMIT GUARDRAIL: "
                    "registro no es DRY_RUN_READY"
                )
                print(url)
                continue

            if should_skip_record(
                row,
                submit,
                targeted=bool(target_url),
                revalidate=revalidate,
            ):
                print(f"\n[{index}] ♻️ {row['status']} → siguiente\n{url}")
                continue

            handled += 1

            print()
            print("=" * 72)
            print(f"[{handled}/{limit}] {url}")
            print("=" * 72)

            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(1000)
                await ensure_auth(page)

                expected_slug = job_slug_from_url(url)
                loaded_slug = job_slug_from_url(page.url)
                if (
                    expected_slug
                    and loaded_slug
                    and expected_slug != loaded_slug
                    and "/applications" not in page.url.casefold()
                ):
                    raise OfferIdentityMismatch(
                        f"URL objetivo={expected_slug} pero la página cargó={loaded_slug}."
                    )

                if await already_applied(page):
                    print("✅ ALREADY_APPLIED")
                    save_record(url, status="ALREADY_APPLIED")
                    continue

                text = await page.locator("body").inner_text()

                decision = cached_decision(url)
                decision_was_cached = decision is not None

                if decision is None:
                    print("🧠 Analizando UNA vez...")
                    decision = await analyze_job(text, url)
                    save_record(url, status="ANALYZED", decision=decision)
                else:
                    print("♻️ Reutilizando JobDecision desde SQLite")

                decision = promote_review_if_safe(
                    decision,
                    text,
                    url,
                )

                # ------------------------------------------------
                # v0.6.11.5 CACHED CV POLICY MIGRATION
                # ------------------------------------------------

                cv_policy_migration_required = False

                if decision_was_cached:

                    (
                        policy_cv,
                        policy_family,
                        policy_language,
                    ) = _resolve_cached_cv_policy(
                        decision,
                        text,
                    )

                    current_cv = str(
                        getattr(
                            decision,
                            "cv_id",
                            "",
                        )
                        or ""
                    ).strip()

                    stale_family_ids = {
                        "data": {
                            "05_ES",
                            "06_EN",
                        },
                        "ops": {
                            "07_ES",
                            "08_EN",
                        },
                    }

                    stale_ids = (
                        stale_family_ids.get(
                            policy_family,
                            set(),
                        )
                    )

                    if (
                        policy_cv
                        and current_cv in stale_ids
                        and current_cv != policy_cv
                    ):

                        if submit:

                            print(
                                "🛑 CV POLICY GUARDRAIL: "
                                f"family={policy_family} "
                                f"cached={current_cv} "
                                f"expected={policy_cv}."
                            )

                            print(
                                "   No se hará click. "
                                "Se encola reparación DRY RUN."
                            )

                            save_record(
                                url,
                                status="REQUEUE_CV_LANGUAGE",
                                decision=decision,
                                error=(
                                    "CV_POLICY_MISMATCH: "
                                    f"family={policy_family}; "
                                    f"language={policy_language}; "
                                    f"cached={current_cv}; "
                                    f"expected={policy_cv}. "
                                    "Reparación DRY RUN obligatoria."
                                ),
                            )

                            continue

                        setattr(
                            decision,
                            "cv_id",
                            policy_cv,
                        )

                        cv_policy_migration_required = True

                        print(
                            "🧭 CV POLICY MIGRATION: "
                            f"{current_cv} → {policy_cv} "
                            f"(family={policy_family}, "
                            f"lang={policy_language.upper()})"
                        )

                dname = decision_name(decision)
                score = getattr(decision, "match_score", None)
                cv = getattr(decision, "cv_id", None)

                cv_alignment = resolve_cv_language(
                    cv,
                    text,
                )

                cv_language_repair_required = bool(
                    dname == "APPLY"
                    and cv_alignment.changed
                )

                if cv_language_repair_required and submit:
                    print(
                        "🛑 CV LANGUAGE GUARDRAIL: "
                        f"oferta={cv_alignment.job_language.upper()} "
                        f"pero decision={cv_alignment.original_cv_id}."
                    )
                    print(
                        "   CV esperado para la misma familia: "
                        f"{cv_alignment.resolved_cv_id}"
                    )
                    print(
                        "   No se hará click. Se encola reparación automática "
                        "para el próximo carril DRY RUN."
                    )
                    save_record(
                        url,
                        status="REQUEUE_CV_LANGUAGE",
                        decision=decision,
                        error=(
                            "CV_LANGUAGE_MISMATCH: "
                            f"job={cv_alignment.job_language}; "
                            f"current={cv_alignment.original_cv_id}; "
                            f"expected={cv_alignment.resolved_cv_id}. "
                            "Revalidación automática pendiente."
                        ),
                    )
                    continue

                if cv_language_repair_required:
                    setattr(
                        decision,
                        "cv_id",
                        cv_alignment.resolved_cv_id,
                    )
                    cv = cv_alignment.resolved_cv_id
                    print(
                        "🌐 CV LANGUAGE ALIGNMENT: "
                        f"{cv_alignment.original_cv_id} → {cv} "
                        f"({cv_alignment.job_language.upper()})"
                    )

                print(f"🎯 {dname} {score}% · CV {cv}")

                if dname == "SKIP":
                    save_record(url, status="SKIP", decision=decision)
                    print("⏭️ SKIP")
                    continue

                if dname == "REVIEW":
                    save_record(url, status="REVIEW", decision=decision)
                    print("⚠️ REVIEW → no se postula automáticamente")
                    continue

                if dname != "APPLY":
                    save_record(
                        url,
                        status="HUMAN_REVIEW",
                        decision=decision,
                        error=f"Decisión desconocida: {dname}",
                    )
                    continue

                if not await open_or_resume_application(page, url):

                    if await already_applied(page):
                        save_record(
                            url,
                            status="ALREADY_APPLIED",
                            decision=decision,
                        )
                        continue

                    (
                        entry_status,
                        entry_reason,
                    ) = await classify_application_entry_failure(
                        page,
                        url,
                    )

                    print(
                        "⚠️ No pude iniciar/reanudar esta postulación."
                    )

                    print(
                        f"→ {entry_status}: {entry_reason}"
                    )

                    save_record(
                        url,
                        status=entry_status,
                        decision=decision,
                        error=entry_reason,
                    )

                    continue

                repair_mode = bool(
                    revalidate
                    or cv_language_repair_required
                    or cv_policy_migration_required
                    or (
                        row
                        and (
                            str(row["status"] or "").startswith("REQUEUE_")
                            or (
                                not submit
                                and row["status"]
                                == "HUMAN_REVIEW"
                            )
                        )
                    )
                )

                if (
                    repair_mode
                    and row
                    and row["status"] == "HUMAN_REVIEW"
                ):
                    print(
                        "🧑‍🔧 HUMAN_REVIEW dirigido: "
                        "reintentando en REPAIR MODE seguro."
                    )

                if repair_mode:

                    if submit:
                        raise RuntimeError(
                            "REQUEUE_FORM_INVALID sólo puede "
                            "repararse primero en DRY RUN."
                        )

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

                    repair_step = str(
                        constraints.get(
                            "repair_step",
                            "",
                        )
                        or ""
                    ).casefold()

                    if (
                        revalidate
                        or cv_language_repair_required
                        or cv_policy_migration_required
                    ):
                        # Legacy drafts can already be sitting at REVIEW with
                        # answers generated by an older pipeline.  A CV-language
                        # correction also has to traverse BASIC so the actual
                        # selected document changes before REVIEW.
                        repair_step = "experience"

                        if revalidate:
                            print(
                                "🔄 REVALIDATE: draft antiguo será "
                                "recorrido desde experience con "
                                "CandidateTruth actual."
                            )

                        if cv_language_repair_required:
                            print(
                                "🌐 CV LANGUAGE REPAIR: recorrido "
                                "editable obligatorio para aplicar "
                                f"{getattr(decision, 'cv_id', '')}."
                            )

                    # HUMAN_REVIEW with an empty last_error is produced by
                    # a required CUSTOM-field blocker inside
                    # complete_application().  This is stronger evidence
                    # than a legacy fallback such as repair_step=basic.
                    # It lets an explicit targeted DRY RUN resume exactly
                    # at CUSTOM without any manual SQLite edit.
                    human_custom_blocker = bool(
                        not revalidate
                        and row
                        and row["status"] == "HUMAN_REVIEW"
                        and (
                            not str(
                                row["last_error"]
                                or ""
                            ).strip()
                            or str(
                                row["last_error"]
                                or ""
                            ).startswith(
                                "CUSTOM_BLOCKER:"
                            )
                        )
                    )

                    if human_custom_blocker:
                        repair_step = "custom"
                        constraints[
                            "repair_step"
                        ] = "custom"
                        constraints[
                            "repair_step_source"
                        ] = "human_review_blocker"

                        setattr(
                            decision,
                            "form_constraints",
                            constraints,
                        )

                        save_record(
                            url,
                            status="HUMAN_REVIEW",
                            decision=decision,
                        )

                        print(
                            "🧭 HUMAN_REVIEW identifica "
                            "bloqueo CUSTOM; repair_step=custom"
                        )

                    current_gob_step = await resolve_gob_step(
                        page
                    )
                    current_stage = await detect_stage(
                        page
                    )

                    print(
                        "🔬 REPAIR DIAGNÓSTICO:"
                    )
                    print(
                        f"   URL={page.url}"
                    )
                    print(
                        f"   GOB STEP={current_gob_step or '-'}"
                    )
                    print(
                        f"   AGENT STAGE={current_stage}"
                    )

                    if not repair_step:
                        live_repair_step = (
                            current_gob_step
                            or repair_step_from_stage(
                                current_stage
                            )
                        )

                        if live_repair_step:
                            repair_step = live_repair_step
                            constraints[
                                "repair_step"
                            ] = repair_step
                            constraints[
                                "repair_step_source"
                            ] = "live_page"

                            setattr(
                                decision,
                                "form_constraints",
                                constraints,
                            )

                            # Persist only when the current page provides
                            # actual editable-step evidence. REVIEW does not
                            # tell us which old step the server rejected.
                            save_record(
                                url,
                                status=row["status"],
                                decision=decision,
                            )

                            print(
                                "🧭 repair_step recuperado "
                                "automáticamente: "
                                f"{repair_step}"
                            )

                        else:
                            # Legacy rows created before v0.5.29 may have
                            # lost the exact rejected step. Starting from
                            # BASIC is conservative because it traverses the
                            # remaining editable flow, but we do NOT label
                            # this fallback as a learned server constraint.
                            repair_step = "basic"
                            print(
                                "🧭 Sin step canónico recuperable; "
                                "entrada conservadora desde basic "
                                "(no persistida como aprendizaje)."
                            )

                    print(
                        "🧭 Repair solicitado desde: "
                        f"{repair_step}"
                    )

                    try:

                        await enter_form_repair_mode(
                            page,
                            repair_step=repair_step,
                            allow_profile_fallback=bool(
                                (
                                    cv_language_repair_required
                                    or cv_policy_migration_required
                                )
                                and not revalidate
                            ),
                        )

                    except RuntimeError as exc:

                        if (
                            "REPAIR_MODE_UNEDITABLE:"
                            not in str(exc)
                        ):
                            raise

                        reason = (
                            "LEGACY_REPAIR_BLOCKER: "
                            + str(exc)
                        )[:1800]

                        constraints[
                            "repair_step"
                        ] = repair_step

                        constraints[
                            "repair_step_source"
                        ] = "legacy_uneditable"

                        constraints[
                            "human_review_reason"
                        ] = reason

                        setattr(
                            decision,
                            "form_constraints",
                            constraints,
                        )

                        save_record(
                            url,
                            status="HUMAN_REVIEW",
                            decision=decision,
                            error=reason,
                        )

                        print(
                            "🛑 HUMAN_REVIEW: "
                            "draft legacy no expone "
                            "una etapa editable segura."
                        )

                        print(
                            "✅ RESULTADO: HUMAN_REVIEW"
                        )

                        continue

                result = await complete_application(
                    page,
                    text,
                    decision,
                    submit=submit,
                    repair_mode=repair_mode,
                )

                result_error = None

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

                if result == "HUMAN_REVIEW":

                    result_error = str(
                        constraints.get(
                            "human_review_reason",
                            "",
                        )
                        or (
                            "HUMAN_REVIEW: "
                            "revisión manual requerida."
                        )
                    )

                else:

                    # v0.6.11.2c
                    # A successfully repaired application must not
                    # retain a HUMAN_REVIEW reason from an older run.
                    stale_reason = constraints.pop(
                        "human_review_reason",
                        None,
                    )

                    if stale_reason:

                        print(
                            "🧹 STALE HUMAN_REVIEW "
                            "reason eliminado tras "
                            f"resultado={result}"
                        )

                    setattr(
                        decision,
                        "form_constraints",
                        constraints,
                    )

                save_record(
                    url,
                    status=result,
                    decision=decision,
                    error=result_error,
                )

                print(
                    f"✅ RESULTADO: {result}"
                )

                if result == "REQUEUE_FORM_INVALID":
                    print(
                        "↪️ Formulario enviado a reparación DRY RUN; "
                        "continúo con la siguiente READY sin repetir este submit."
                    )
                    continue

                if result in {
                    "SUBMIT_UNKNOWN",
                    "CONFIRMATION_REQUIRED",
                }:

                    if result == "SUBMIT_UNKNOWN":
                        message = (
                            "Estado posterior al submit desconocido."
                        )
                    else:
                        message = (
                            "Get on Board solicita una "
                            "confirmación adicional."
                        )

                    print(
                        "🧊 "
                        + message
                        + " La oferta queda en CUARENTENA; "
                        + "NO se repetirá el click final. "
                        + "Continúo con la siguiente READY."
                    )

                    # Critical invariant:
                    # save_record() already persisted the irreversible
                    # state above. should_skip_record() treats it as
                    # terminal, so this URL can never be reopened
                    # implicitly.
                    continue

            except OfferIdentityMismatch as exc:
                print(f"🛑 OFFER IDENTITY GUARDRAIL: {exc}")
                save_record(
                    url,
                    status="HUMAN_REVIEW",
                    error=f"OFFER_IDENTITY_MISMATCH: {exc}",
                )
                continue

            except AuthRequired:
                save_record(url, status="AUTH_REQUIRED")
                raise

            except Exception as exc:
                error_name = type(exc).__name__
                error_text = f"{error_name}: {exc}"

                print(f"❌ {error_text}")

                # -------------------------------------------------
                # JOB-SPECIFIC NEXT/PERSISTENCE STALL
                # -------------------------------------------------
                # A NEXT click that never settles is deliberately not
                # hammered every generic ERROR cycle.  Put it in the
                # reversible HUMAN_REVIEW lane; that lane is automatically
                # re-evaluated after its longer cooldown.
                if "NEXT_TRANSITION_STALLED:" in str(exc):
                    save_record(
                        url,
                        status="HUMAN_REVIEW",
                        error=error_text,
                    )
                    print(
                        "🟡 NEXT stall aislado → HUMAN_REVIEW; "
                        "reintento autónomo después del cooldown."
                    )
                    continue

                # -------------------------------------------------
                # TRANSIENT LLM FAILURE
                # -------------------------------------------------
                #
                # Never burn the rest of a batch when the local LLM
                # is unhealthy. ERROR remains a recoverable backlog
                # state in this loop, but the explicit prefix lets
                # the daemon distinguish infrastructure failure from
                # a job-specific failure.
                if (
                    "LLM_TRANSIENT:" in str(exc)
                    or "LLM_OUTPUT_INVALID:" in str(exc)
                    or error_name == "APITimeoutError"
                ):
                    save_record(
                        url,
                        status="ERROR",
                        error=f"TRANSIENT_LLM: {error_text}",
                    )

                    print(
                        "🛑 LLM TRANSIENT FAILURE → "
                        "aborto este batch para recuperar infraestructura."
                    )
                    break

                # -------------------------------------------------
                # TRANSIENT BROWSER FAILURE
                # -------------------------------------------------
                if isinstance(exc, PlaywrightError):
                    save_record(
                        url,
                        status="ERROR",
                        error=f"TRANSIENT_BROWSER: {error_text}",
                    )

                    print(
                        "🛑 BROWSER TRANSIENT FAILURE → "
                        "aborto este batch para recrear CDP."
                    )
                    break

                # Unknown/job-specific failures remain ordinary ERROR
                # and can be retried by the existing cooldown policy.
                save_record(
                    url,
                    status="ERROR",
                    error=error_text,
                )

                try:
                    stamp = datetime.now().strftime(
                        "%Y%m%d-%H%M%S"
                    )
                    await page.screenshot(
                        path=str(
                            ROOT
                            / "logs"
                            / f"error-{stamp}.png"
                        ),
                        full_page=True,
                    )
                except Exception:
                    pass

        print()
        print("=" * 72)
        print(f"🏁 Pasada terminada. Procesadas: {handled}")
        print(f"DB: {DB}")
        print("=" * 72)

    finally:
        try:
            if "page" in locals() and page:
                await page.close()
        except Exception:
            pass

        await session.close()


def main():
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--submit", action="store_true")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument(
        "--url",
        dest="target_url",
        help=(
            "Procesa sólo esta oferta. Omite backlog y discovery; "
            "mantiene todos los guardrails de estado/submit."
        ),
    )
    parser.add_argument(
        "--revalidate",
        action="store_true",
        help=(
            "Sólo con --dry-run --url: fuerza un draft existente "
            "a recorrer etapas editables con CandidateTruth actual "
            "antes de conservar DRY_RUN_READY."
        ),
    )
    parser.add_argument("--scrolls", type=int, default=8)
    args = parser.parse_args()

    try:
        asyncio.run(
            run_loop(
                limit=args.limit,
                submit=args.submit,
                scrolls=args.scrolls,
                target_url=args.target_url,
                revalidate=args.revalidate,
            )
        )
    except AuthRequired as exc:
        print(f"\n🔐 AUTH_REQUIRED: {exc}")
        raise SystemExit(42)


if __name__ == "__main__":
    main()
