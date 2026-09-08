from __future__ import annotations

import asyncio
import json
import re

from agentes.browser import BrowserSession
from agentes.config import Settings


async def inspect_page(page):
    await page.wait_for_timeout(1200)

    url = page.url
    body = await page.locator("body").inner_text()

    body_lower = body.lower()

    if any(x in body_lower for x in [
        "vista previa",
        "preview",
        "revisar y enviar",
        "review and submit",
    ]):
        stage = "REVIEW"

    elif any(x in body_lower for x in [
        "pretensión de renta",
        "pretensiones de renta",
        "salary expectation",
        "expected salary",
        "por qué quieres trabajar",
        "why do you want to work",
        "curriculum",
        "cv",
    ]):
        stage = "BASIC_INFO"

    elif any(x in body_lower for x in [
        "experiencia y perfil profesional",
        "professional experience",
        "formación académica",
        "academic background",
    ]):
        stage = "PROFILE"

    else:
        stage = "CUSTOM_OR_UNKNOWN"

    print()
    print("=" * 80)
    print(f"🧭 STAGE: {stage}")
    print(f"🌐 URL: {url}")
    print("=" * 80)

    fields = await page.locator(
        """
        input,
        textarea,
        select,
        trix-editor,
        [role='textbox'],
        [contenteditable='true']
        """
    ).evaluate_all(
        """
        els => els
          .filter(el => {
            const style = window.getComputedStyle(el);
            const rect = el.getBoundingClientRect();

            return style.display !== 'none'
                && style.visibility !== 'hidden'
                && rect.width > 0
                && rect.height > 0;
          })
          .map((el, i) => {
            let label = '';

            if (el.labels && el.labels.length) {
                label = Array.from(el.labels)
                    .map(x => (x.innerText || x.textContent || '').trim())
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
                const parent = el.closest(
                    'label, .form-group, .field, .mb-3, .mb-4'
                );

                if (parent) {
                    label = (
                        parent.innerText ||
                        parent.textContent ||
                        ''
                    ).trim().slice(0, 500);
                }
            }

            let options = [];

            if (el.tagName === 'SELECT') {
                options = Array.from(el.options).map(o => ({
                    text: (o.textContent || '').trim(),
                    value: o.value,
                    selected: o.selected
                }));
            }

            return {
                index: i,
                tag: el.tagName.toLowerCase(),
                type: el.getAttribute('type') || '',
                id: el.id || '',
                name: el.getAttribute('name') || '',
                role: el.getAttribute('role') || '',
                placeholder: el.getAttribute('placeholder') || '',
                label,
                value: el.value || '',
                checked: !!el.checked,
                required: !!el.required,
                disabled: !!el.disabled,
                accept: el.getAttribute('accept') || '',
                options
            };
          })
        """
    )

    print()
    print("📝 CAMPOS DETECTADOS")
    print("-" * 80)

    for f in fields:
        print()
        print(f"[{f['index']}] {f['tag']} type={f['type'] or '—'}")
        print(f"    id={f['id'] or '—'}")
        print(f"    name={f['name'] or '—'}")
        print(f"    role={f['role'] or '—'}")

        label = (
            f.get("label")
            or f.get("placeholder")
            or "—"
        )

        print(f"    label={label[:350]}")

        if f["type"] in ("checkbox", "radio"):
            print(f"    checked={f['checked']}")

        if f["accept"]:
            print(f"    accept={f['accept']}")

        if f["options"]:
            print("    options:")
            for opt in f["options"][:30]:
                print(
                    f"      - {opt['text']!r} "
                    f"value={opt['value']!r}"
                )

    buttons = await page.locator(
        "button, input[type='submit'], [role='button']"
    ).evaluate_all(
        """
        els => els
          .filter(el => {
            const style = window.getComputedStyle(el);
            const rect = el.getBoundingClientRect();

            return style.display !== 'none'
                && style.visibility !== 'hidden'
                && rect.width > 0
                && rect.height > 0;
          })
          .map((el, i) => ({
            index: i,
            tag: el.tagName.toLowerCase(),
            type: el.getAttribute('type') || '',
            text: (
                el.innerText ||
                el.value ||
                el.getAttribute('aria-label') ||
                ''
            ).trim()
          }))
        """
    )

    print()
    print("🔘 BOTONES")
    print("-" * 80)

    for b in buttons:
        if b["text"]:
            print(
                f"[{b['index']}] "
                f"{b['tag']} "
                f"type={b['type'] or '—'} "
                f"→ {b['text'][:150]}"
            )

    print()
    print("✅ Probe terminado. NO se hizo submit.")


async def main():
    settings = Settings()

    session = await BrowserSession.connect_cdp(
        settings.brave_cdp_url
    )

    try:
        page = session.find_page("getonbrd.com")

        if page is None:
            raise RuntimeError(
                "No encontré una pestaña de Get on Board."
            )

        print(f"📍 Página actual: {page.url}")

        # Solo avanzar si seguimos en la primera página.
        professional = page.locator("#trix-professional")

        if await professional.count() > 0:
            print("✅ Página PROFILE detectada")

            print("🔎 Buscando botón Siguiente/Next...")

            next_button = None

            # 1. Get on Board actualmente usa button[type=submit]
            candidates = page.locator(
                "button[type='submit'], input[type='submit']"
            )

            for i in range(await candidates.count()):
                candidate = candidates.nth(i)

                if not await candidate.is_visible():
                    continue

                text = (
                    await candidate.inner_text()
                    if await candidate.evaluate(
                        "(el) => el.tagName.toLowerCase() === 'button'"
                    )
                    else await candidate.get_attribute("value") or ""
                )

                text = (text or "").strip()

                print(
                    f"   candidato submit #{i}: "
                    f"{text!r}"
                )

                if re.search(
                    r"\\b(siguiente|next|continuar|continue)\\b",
                    text,
                    re.IGNORECASE,
                ):
                    next_button = candidate
                    break

            # 2. Fallback por texto visible
            if next_button is None:
                candidates = page.locator("button")

                for i in range(await candidates.count()):
                    candidate = candidates.nth(i)

                    if not await candidate.is_visible():
                        continue

                    text = (
                        await candidate.inner_text()
                    ).strip()

                    if re.search(
                        r"\\b(siguiente|next|continuar|continue)\\b",
                        text,
                        re.IGNORECASE,
                    ):
                        next_button = candidate
                        break

            # 3. Último fallback:
            # si sólo existe un submit visible, usarlo.
            if next_button is None:
                visible_submits = []

                submits = page.locator(
                    "button[type='submit'], input[type='submit']"
                )

                for i in range(await submits.count()):
                    candidate = submits.nth(i)

                    if await candidate.is_visible():
                        visible_submits.append(candidate)

                if len(visible_submits) == 1:
                    print(
                        "⚠️ Usando único submit visible "
                        "como botón de avance."
                    )
                    next_button = visible_submits[0]

            if next_button is None:
                raise RuntimeError(
                    "No pude identificar de forma segura "
                    "el botón Siguiente/Next."
                )

            print("➡️ Pulsando Siguiente...")

            old_url = page.url

            await next_button.scroll_into_view_if_needed()

            await next_button.click(
                timeout=10000
            )

            try:
                await page.wait_for_url(
                    lambda u: u != old_url,
                    timeout=7000,
                )
            except Exception:
                # Algunas apps cambian contenido sin cambiar URL.
                pass

            await page.wait_for_timeout(1500)

        else:
            print(
                "ℹ️ Ya no estamos en PROFILE; "
                "inspeccionando página actual."
            )

        await inspect_page(page)

    finally:
        await session.close()


if __name__ == "__main__":
    asyncio.run(main())
