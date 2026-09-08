from __future__ import annotations

import asyncio
import os
from pathlib import Path

from pydantic import BaseModel, Field
from agents import Agent, Runner

from agentes.browser import BrowserSession
from agentes.config import Settings


ROOT = Path(__file__).resolve().parents[1]


class ProfileAnswers(BaseModel):
    language: str = Field(description="es or en")
    professional: str = Field(
        description="Answer for professional experience/profile field"
    )
    academic: str = Field(
        description="Answer for academic background/studies field"
    )


def load_candidate() -> str:
    candidates = (
        list(ROOT.rglob("candidate.yaml"))
        + list(ROOT.rglob("candidate.yml"))
    )

    if not candidates:
        raise RuntimeError("No encontré candidate.yaml en el proyecto.")

    path = candidates[0]
    print(f"✅ Knowledge source: {path.relative_to(ROOT)}")

    return path.read_text(encoding="utf-8")


async def get_job_text(page) -> tuple[str, str]:
    """
    Desde la página /applications/new intenta encontrar el enlace
    de la oferta original y leerla en una pestaña temporal.
    """

    links = await page.locator("a").evaluate_all(
        """
        els => els.map(a => ({
            text: (a.innerText || a.textContent || '').trim(),
            href: a.href || ''
        }))
        """
    )

    job_link = None

    for link in links:
        href = link.get("href", "")

        if (
            "getonbrd.com" in href
            and "/applications/" not in href
            and (
                "/jobs/" in href
                or "/empleos/" in href
            )
        ):
            # Evitar navegación genérica
            text = link.get("text", "").strip()

            if text and text.lower() not in {
                "empleos para ti",
                "tus postulaciones",
                "invitaciones",
            }:
                job_link = href
                break

    # Fallback: usar la propia página de aplicación
    if not job_link:
        print("⚠️ No encontré oferta original; usando página actual.")
        text = await page.locator("body").inner_text()
        return page.url, text

    print(f"✅ Oferta encontrada: {job_link}")

    temp = await page.context.new_page()

    try:
        await temp.goto(
            job_link,
            wait_until="domcontentloaded",
            timeout=30000,
        )

        await temp.wait_for_timeout(1500)

        text = await temp.locator("body").inner_text()

        return job_link, text

    finally:
        await temp.close()


async def generate_answers(
    candidate_text: str,
    job_url: str,
    job_text: str,
) -> ProfileAnswers:

    instructions = """
You write job application answers for the candidate.

ABSOLUTE RULES:

1. Never invent skills, employers, technologies, years, degrees,
   certifications or responsibilities.
2. candidate.yaml is the source of truth.
3. Tailor the answers to the actual job.
4. Answer in the language used by the job posting.
5. If the job is Spanish, write natural professional Spanish.
6. If the job is English, write natural professional English.
7. Do not mention gaps unless necessary.
8. Do not claim direct experience that is not supported.
9. Avoid generic corporate filler.
10. Keep each answer concise enough for a job application form.

professional:
Summarize the candidate's most relevant professional experience,
technical profile, strengths and relevant current activities.

academic:
Summarize formal education plus relevant teaching, technical
training and professional learning.

Do not include Markdown headings.
"""

    agent = Agent(
        name="GetOnBoard Profile Writer",
        instructions=instructions,
        model=os.getenv("AGENT_MODEL", "gpt-5.6-terra"),
        output_type=ProfileAnswers,
    )

    prompt = f"""
CANDIDATE SOURCE OF TRUTH
=========================
{candidate_text}


JOB URL
=======
{job_url}


JOB POSTING
===========
{job_text[:30000]}


Generate the two application answers.
"""

    result = await Runner.run(
        agent,
        prompt,
        max_turns=3,
    )

    return result.final_output


async def set_trix(page, selector: str, text: str):
    locator = page.locator(selector)

    await locator.wait_for(
        state="visible",
        timeout=10000,
    )

    # Trix expone su propio objeto editor.
    # insertString actualiza también el hidden input asociado.
    success = await locator.evaluate(
        """
        (el, text) => {
            if (!el.editor) {
                return false;
            }

            el.editor.loadHTML("");
            el.editor.insertString(text);

            el.dispatchEvent(
                new Event("input", { bubbles: true })
            );

            el.dispatchEvent(
                new Event("change", { bubbles: true })
            );

            return true;
        }
        """,
        text,
    )

    if not success:
        # Fallback para versiones distintas de Trix.
        await locator.click()
        await page.keyboard.press("Control+A")
        await page.keyboard.insert_text(text)

    print(f"✅ Rellenado {selector}")


async def main():
    settings = Settings()

    session = await BrowserSession.connect_cdp(
        settings.brave_cdp_url
    )

    try:
        page = session.find_page("getonbrd.com")

        if page is None:
            raise RuntimeError(
                "No encontré una pestaña Get on Board."
            )

        if "/applications/" not in page.url:
            raise RuntimeError(
                "La pestaña Get on Board no está en el formulario "
                "de postulación."
            )

        print()
        print("🤖 PROFILE PAGE AGENT")
        print("=" * 60)
        print(page.url)
        print()

        candidate = load_candidate()

        job_url, job_text = await get_job_text(page)

        print("🧠 Generando respuestas...")

        answers = await generate_answers(
            candidate,
            job_url,
            job_text,
        )

        print()
        print(
            f"🌎 Idioma detectado: "
            f"{answers.language.upper()}"
        )

        print()
        print("👨‍💻 EXPERIENCIA")
        print("-" * 60)
        print(answers.professional)

        print()
        print("🎓 FORMACIÓN")
        print("-" * 60)
        print(answers.academic)
        print()

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

        print()
        print("🔥 PÁGINA 1 COMPLETADA")
        print()
        print(
            "NO se pulsó Siguiente. "
            "Revisa visualmente Brave."
        )

    finally:
        await session.close()


if __name__ == "__main__":
    asyncio.run(main())
