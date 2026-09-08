from __future__ import annotations

import asyncio
import json

from agentes.browser import BrowserSession
from agentes.config import Settings


async def main():
    settings = Settings()

    session = await BrowserSession.connect_cdp(
        settings.brave_cdp_url
    )

    try:
        page = session.find_page("getonbrd.com")

        if page is None:
            raise RuntimeError("No encontré Get on Board.")

        print("📍 Inicial:", page.url)

        # Si estamos en REVIEW, volver a BASIC.
        if "job_application_preview=true" in page.url:
            print("⬅️ Volviendo automáticamente a BASIC...")

            await page.go_back(
                wait_until="domcontentloaded",
                timeout=15000,
            )

            await page.wait_for_timeout(1500)

        print("📍 Actual:", page.url)

        if "step=basic" not in page.url:
            raise RuntimeError(
                "No quedamos en step=basic. "
                "No se modificó la postulación."
            )

        # =====================================================
        # 1. TODOS LOS INPUTS, INCLUSO HIDDEN
        # =====================================================

        inputs = await page.locator(
            "input, select, textarea"
        ).evaluate_all(
            """
            els => els.map((el, i) => ({
                i,
                tag: el.tagName.toLowerCase(),
                type: el.getAttribute('type') || '',
                id: el.id || '',
                name: el.getAttribute('name') || '',
                value: el.value || '',
                checked: !!el.checked,
                hidden:
                    el.type === 'hidden' ||
                    window.getComputedStyle(el).display === 'none',
                role: el.getAttribute('role') || '',
                aria_label: el.getAttribute('aria-label') || '',
                aria_controls: el.getAttribute('aria-controls') || '',
                aria_expanded: el.getAttribute('aria-expanded') || '',
                autocomplete: el.getAttribute('autocomplete') || '',
                className:
                    typeof el.className === 'string'
                        ? el.className
                        : '',
                data: {...el.dataset}
            }))
            """
        )

        print()
        print("=" * 80)
        print("🧬 INPUTS / SELECTS — INCLUYE HIDDEN")
        print("=" * 80)

        for x in inputs:
            print()
            print(
                f"[{x['i']}] {x['tag']} "
                f"type={x['type'] or '—'}"
            )
            print(f"    id={x['id'] or '—'}")
            print(f"    name={x['name'] or '—'}")
            print(f"    value={x['value'] or '—'}")
            print(f"    checked={x['checked']}")
            print(f"    hidden={x['hidden']}")
            print(f"    role={x['role'] or '—'}")

            if x["aria_label"]:
                print(
                    f"    aria-label={x['aria_label']}"
                )

            if x["aria_controls"]:
                print(
                    f"    aria-controls={x['aria_controls']}"
                )

            if x["aria_expanded"]:
                print(
                    f"    aria-expanded={x['aria_expanded']}"
                )

            if x["data"]:
                print(
                    "    data="
                    + json.dumps(
                        x["data"],
                        ensure_ascii=False
                    )[:700]
                )

        # =====================================================
        # 2. NODOS RELACIONADOS CON CV
        # =====================================================

        cv_nodes = await page.locator(
            "a, button, label, div, span"
        ).evaluate_all(
            """
            els => {
                const result = [];

                for (const [i, el] of els.entries()) {
                    const own = (
                        el.innerText ||
                        el.textContent ||
                        ''
                    ).trim();

                    const attrs = [
                        el.id || '',
                        el.getAttribute('name') || '',
                        el.getAttribute('href') || '',
                        el.getAttribute('class') || '',
                        el.getAttribute('aria-label') || ''
                    ].join(' ');

                    const blob = (own + ' ' + attrs).toLowerCase();

                    if (
                        blob.includes('.pdf') ||
                        blob.includes('curriculum') ||
                        blob.includes('currículum') ||
                        blob.includes('resume') ||
                        /\\bcv\\b/i.test(blob)
                    ) {
                        result.push({
                            i,
                            tag: el.tagName.toLowerCase(),
                            text: own.slice(0, 500),
                            id: el.id || '',
                            href: el.getAttribute('href') || '',
                            role: el.getAttribute('role') || '',
                            className:
                                typeof el.className === 'string'
                                    ? el.className
                                    : ''
                        });
                    }
                }

                return result;
            }
            """
        )

        print()
        print("=" * 80)
        print("📄 ELEMENTOS RELACIONADOS CON CV")
        print("=" * 80)

        for x in cv_nodes:
            print()
            print(
                f"{x['tag']} id={x['id'] or '—'} "
                f"role={x['role'] or '—'}"
            )

            if x["text"]:
                print(
                    "    text="
                    + x["text"].replace("\\n", " | ")
                )

            if x["href"]:
                print(f"    href={x['href']}")

            if x["className"]:
                print(
                    f"    class={x['className'][:400]}"
                )

        # =====================================================
        # 3. HTML ALREDEDOR DEL PDF SELECCIONADO
        # =====================================================

        contexts = await page.locator("a").evaluate_all(
            """
            els => {
                const out = [];

                for (const el of els) {
                    const text = (
                        el.innerText ||
                        el.textContent ||
                        ''
                    ).trim();

                    if (!text.toLowerCase().includes('.pdf')) {
                        continue;
                    }

                    let node = el;

                    for (let level = 0; level < 5 && node; level++) {
                        out.push({
                            level,
                            text,
                            html: (node.outerHTML || '').slice(0, 3500)
                        });

                        node = node.parentElement;
                    }
                }

                return out;
            }
            """
        )

        print()
        print("=" * 80)
        print("🔬 DOM ALREDEDOR DEL CV ACTUAL")
        print("=" * 80)

        for c in contexts:
            print()
            print(
                f"--- NIVEL {c['level']} "
                f"({c['text']}) ---"
            )
            print(c["html"])

        print()
        print("=" * 80)
        print("✅ CV probe terminado.")
        print("🛑 NO se modificó ni envió la postulación.")

    finally:
        await session.close()


if __name__ == "__main__":
    asyncio.run(main())
