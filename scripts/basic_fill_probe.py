from __future__ import annotations

import asyncio
import os
import re

from agents import Agent, Runner
from pydantic import BaseModel

from agentes.browser import BrowserSession
from agentes.config import Settings
from agentes.jobs.analyzer import analyze_job
from agentes.jobs.cv_selector import select_cv, assert_cv_selected


class Motivation(BaseModel):
    language: str
    text: str


async def get_job(page):
    links = await page.locator("a").evaluate_all(
        """
        els => els.map(a => ({
            text: (a.innerText || a.textContent || '').trim(),
            href: a.href || ''
        }))
        """
    )

    job_url = None

    for link in links:
        href = link.get("href", "")
        text = link.get("text", "")

        if (
            "getonbrd.com" in href
            and "/applications/" not in href
            and ("/jobs/" in href or "/empleos/" in href)
            and text
        ):
            if text.lower() not in {
                "empleos para ti",
                "tus postulaciones",
                "invitaciones",
            }:
                job_url = href
                break

    if not job_url:
        raise RuntimeError(
            "No pude encontrar el link de la oferta original."
        )

    print(f"✅ Oferta: {job_url}")

    tmp = await page.context.new_page()

    try:
        await tmp.goto(
            job_url,
            wait_until="domcontentloaded",
            timeout=30000,
        )

        await tmp.wait_for_timeout(1200)

        text = await tmp.locator("body").inner_text()

    finally:
        await tmp.close()

    return job_url, text


async def generate_motivation(
    job_text: str,
    job_url: str,
    decision,
):
    agent = Agent(
        name="Application Motivation Writer",
        model=os.getenv(
            "AGENT_MODEL",
            "gpt-5.6-terra"
        ),
        output_type=Motivation,
        instructions="""
Write the answer to the job-application question asking
why the candidate wants to work at this company.

Rules:
- Use the language of the job posting.
- 2 to 4 sentences.
- Natural and credible.
- Tailor it to the real role and company.
- Never invent experience.
- Do not mention match percentages.
- Do not mention gaps.
- Do not sound desperate.
- Do not use generic phrases such as
  "prestigious company" unless supported.
- Focus on the role's function, technologies,
  learning opportunity and contribution.
""",
    )

    prompt = f"""
JOB URL
{job_url}

JOB
{job_text[:25000]}

EXISTING ANALYSIS
Title: {decision.job.title}
Company: {decision.job.company}
Match: {decision.match_score}
CV: {decision.cv_id}
Why: {decision.why}
Gaps: {decision.hard_gaps}

Write the motivation answer.
"""

    result = await Runner.run(
        agent,
        prompt,
        max_turns=3,
    )

    return result.final_output


async def inspect_cv_area(page):
    print()
    print("📄 BUSCANDO SELECTOR DE CV")
    print("-" * 70)

    data = await page.locator(
        """
        input,
        select,
        button,
        [role='radio'],
        [role='option'],
        [role='button'],
        a
        """
    ).evaluate_all(
        """
        els => els
          .filter(el => {
            const s = window.getComputedStyle(el);
            const r = el.getBoundingClientRect();

            return s.display !== 'none'
                && s.visibility !== 'hidden'
                && r.width > 0
                && r.height > 0;
          })
          .map((el, i) => ({
            i,
            tag: el.tagName.toLowerCase(),
            type: el.getAttribute('type') || '',
            id: el.id || '',
            name: el.getAttribute('name') || '',
            role: el.getAttribute('role') || '',
            text: (
                el.innerText ||
                el.value ||
                el.getAttribute('aria-label') ||
                ''
            ).trim().slice(0, 300)
          }))
        """
    )

    found = False

    for el in data:
        blob = " ".join([
            el["id"],
            el["name"],
            el["role"],
            el["text"],
        ]).lower()

        if any(x in blob for x in [
            "cv",
            "curriculum",
            "currículum",
            "resume",
        ]):
            found = True

            print(
                f"[{el['i']}] "
                f"{el['tag']} "
                f"type={el['type'] or '—'} "
                f"role={el['role'] or '—'}"
            )
            print(f"    id={el['id'] or '—'}")
            print(f"    name={el['name'] or '—'}")
            print(f"    text={el['text'] or '—'}")

    if not found:
        print(
            "ℹ️ No aparece un selector de CV "
            "como control HTML visible en esta pantalla."
        )


async def detect_stage(page):
    await page.wait_for_timeout(1300)

    url = page.url
    body = (
        await page.locator("body").inner_text()
    ).lower()

    # Primero URL, que es mucho más fiable.
    if "step=basic" in url:
        stage = "BASIC_INFO"

    elif any(x in url.lower() for x in [
        "preview",
        "review",
    ]):
        stage = "REVIEW"

    elif any(x in body for x in [
        "enviar postulación",
        "enviar postulacion",
        "submit application",
        "confirmar postulación",
        "confirmar postulacion",
    ]):
        stage = "REVIEW"

    elif any(x in body for x in [
        "cuéntanos sobre tu experiencia",
        "cuentanos sobre tu experiencia",
        "professional experience",
    ]):
        stage = "PROFILE"

    else:
        stage = "CUSTOM_OR_UNKNOWN"

    print()
    print("=" * 80)
    print(f"🧭 NUEVO STAGE: {stage}")
    print(f"🌐 {url}")
    print("=" * 80)

    return stage


async def probe_current_fields(page):
    fields = await page.locator(
        """
        input,
        textarea,
        select,
        trix-editor,
        [role='textbox'],
        [role='radio'],
        [role='checkbox']
        """
    ).evaluate_all(
        """
        els => els
          .filter(el => {
            const s = window.getComputedStyle(el);
            const r = el.getBoundingClientRect();

            return s.display !== 'none'
                && s.visibility !== 'hidden'
                && r.width > 0
                && r.height > 0;
          })
          .map((el, i) => {
            let label = '';

            if (el.labels && el.labels.length) {
                label = Array.from(el.labels)
                    .map(x => (
                        x.innerText ||
                        x.textContent ||
                        ''
                    ).trim())
                    .join(' ');
            }

            if (!label && el.id) {
                const lab = document.querySelector(
                    `label[for="${CSS.escape(el.id)}"]`
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
                let p = el.parentElement;

                for (let depth = 0; depth < 4 && p; depth++, p = p.parentElement) {
                    const txt = (
                        p.innerText ||
                        p.textContent ||
                        ''
                    ).trim();

                    if (txt && txt.length < 600) {
                        label = txt;
                        break;
                    }
                }
            }

            let options = [];

            if (el.tagName === 'SELECT') {
                options = Array.from(
                    el.options
                ).map(o => (
                    o.textContent || ''
                ).trim());
            }

            return {
                i,
                tag: el.tagName.toLowerCase(),
                type: el.getAttribute('type') || '',
                id: el.id || '',
                name: el.getAttribute('name') || '',
                role: el.getAttribute('role') || '',
                label: label.slice(0, 400),
                value: el.value || '',
                checked: !!el.checked,
                options
            };
          })
        """
    )

    print()
    print("🧩 CAMPOS DE LA NUEVA PÁGINA")
    print("-" * 80)

    if not fields:
        print("No se detectaron campos.")

    for f in fields:
        print()
        print(
            f"[{f['i']}] "
            f"{f['tag']} "
            f"type={f['type'] or '—'}"
        )

        print(
            f"    id={f['id'] or '—'}"
        )

        print(
            f"    name={f['name'] or '—'}"
        )

        print(
            f"    role={f['role'] or '—'}"
        )

        print(
            f"    label={f['label'] or '—'}"
        )

        if f["type"] in [
            "checkbox",
            "radio",
        ]:
            print(
                f"    checked={f['checked']}"
            )

        if f["options"]:
            print(
                "    options="
                + " | ".join(f["options"])
            )


async def click_next(page):
    submits = page.locator(
        "button[type='submit'], input[type='submit']"
    )

    candidates = []

    for i in range(await submits.count()):
        el = submits.nth(i)

        if not await el.is_visible():
            continue

        try:
            text = (
                await el.inner_text()
            ).strip()
        except Exception:
            text = (
                await el.get_attribute("value")
                or ""
            ).strip()

        print(
            f"🔘 submit #{i}: {text!r}"
        )

        candidates.append(
            (el, text)
        )

    for el, text in candidates:
        if re.search(
            r"(siguiente|next|revisar|review|continue)",
            text,
            re.I,
        ):
            print(
                f"➡️ Avanzando con {text!r}"
            )

            await el.scroll_into_view_if_needed()
            await el.click(timeout=10000)

            return

    if len(candidates) == 1:
        print(
            "➡️ Avanzando con único submit visible"
        )

        await candidates[0][0].click(
            timeout=10000
        )

        return

    raise RuntimeError(
        "No pude identificar el botón de avance."
    )


async def main():
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
                "No encontré Get on Board."
            )

        print()
        print("🤖 BASIC PAGE AGENT")
        print("=" * 70)
        print(page.url)

        if "step=basic" not in page.url:
            raise RuntimeError(
                "No estamos en step=basic."
            )

        job_url, job_text = await get_job(
            page
        )

        print()
        print("🧠 Analizando oferta nuevamente...")

        decision = await analyze_job(
            job_text,
            job_url
        )

        print()
        print(
            f"🎯 Decision: "
            f"{decision.decision} "
            f"{decision.match_score}%"
        )

        print(
            f"📄 CV recomendado: "
            f"{decision.cv_id}"
        )

        print(
            f"💰 Salary USD/month: "
            f"{decision.salary_usd_monthly}"
        )

        motivation = await generate_motivation(
            job_text,
            job_url,
            decision,
        )

        print()
        print("❤️ MOTIVACIÓN")
        print("-" * 70)
        print(motivation.text)

        salary = page.locator(
            "#job_application_expected_salary"
        )

        if await salary.count():
            if decision.salary_usd_monthly:
                await salary.fill(
                    str(
                        decision.salary_usd_monthly
                    )
                )

                print()
                print(
                    "✅ Renta rellenada: "
                    f"{decision.salary_usd_monthly} USD"
                )
            else:
                print(
                    "⚠️ El análisis no devolvió renta."
                )

        reason = page.locator(
            "#reason-to-apply"
        )

        if await reason.count():
            await reason.fill(
                motivation.text
            )

            print(
                "✅ Motivación rellenada"
            )

        residency = page.locator(
            "#confirm_residency"
        )

        if await residency.count():
            if not await residency.is_checked():
                await residency.check()

            print(
                "✅ Residencia Chile confirmada"
            )

        # ================================================
        # CV SELECTION
        # ================================================

        if not decision.cv_id:
            raise RuntimeError(
                "El Job Agent no seleccionó CV."
            )

        print()
        print(
            f"📄 Seleccionando CV "
            f"{decision.cv_id}..."
        )

        cv_result = await select_cv(
            page,
            decision.cv_id,
        )

        print(
            "✅ CV REAL SELECCIONADO:"
        )

        print(
            f"   {cv_result['filename']}"
        )

        print(
            f"   GetOnBoard resume_id="
            f"{cv_result['resume_id']}"
        )

        if cv_result["ui_filename"]:
            print(
                f"   UI Chosen="
                f"{cv_result['ui_filename']}"
            )

        # Guardrail inmediatamente después
        await assert_cv_selected(
            page,
            decision.cv_id,
        )

        print(
            "🛡️ CV guardrail: PASS"
        )

        # ================================================
        # CV SELECTION
        # ================================================

        if not decision.cv_id:
            raise RuntimeError(
                "El Job Agent no seleccionó CV."
            )

        print()
        print(
            f"📄 Seleccionando CV "
            f"{decision.cv_id}..."
        )

        cv_result = await select_cv(
            page,
            decision.cv_id,
        )

        print(
            "✅ CV REAL SELECCIONADO:"
        )

        print(
            f"   {cv_result['filename']}"
        )

        print(
            f"   GetOnBoard resume_id="
            f"{cv_result['resume_id']}"
        )

        if cv_result["ui_filename"]:
            print(
                f"   UI Chosen="
                f"{cv_result['ui_filename']}"
            )

        # Guardrail inmediatamente después
        await assert_cv_selected(
            page,
            decision.cv_id,
        )

        print(
            "🛡️ CV guardrail: PASS"
        )

        await inspect_cv_area(page)

        print()
        print(
            "⚠️ MODO TEST: "
            "esta oferta puede ser REVIEW; "
            "avanzaremos para probar el flujo, "
            "pero JAMÁS enviaremos la postulación."
        )

        print()
        print("➡️ Vamos a la siguiente etapa...")

        # ÚLTIMA VERIFICACIÓN ANTES DE GUARDAR/AVANZAR
        await assert_cv_selected(
            page,
            decision.cv_id,
        )

        print(
            "🛡️ Pre-navigation CV guardrail: PASS"
        )

        await click_next(page)

        stage = await detect_stage(page)

        await probe_current_fields(page)

        print()
        print("=" * 80)

        if stage == "REVIEW":
            print(
                "🔥 Llegamos a REVIEW."
            )

        elif stage == "CUSTOM_OR_UNKNOWN":
            print(
                "🔥 Detectamos una posible "
                "PÁGINA EXTRA."
            )

            print(
                "El próximo paso será resolver "
                "estas preguntas automáticamente."
            )

        else:
            print(
                f"ℹ️ Stage detectado: {stage}"
            )

        print()
        print(
            "🛑 NO SE PULSÓ ENVIAR."
        )

    finally:
        await session.close()


if __name__ == "__main__":
    asyncio.run(main())
