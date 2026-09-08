from __future__ import annotations

import asyncio
from agentes.browser import BrowserSession
from agentes.config import Settings


DRAFT_URL = (
    "https://www.getonbrd.com/jobs/"
    "desarrollador-back-end-python-agencia-de-aduanas-"
    "felipe-serrano-santiago/applications/"
    "02ee41ab3fec9da674871984d6fd2c2a"
)


async def main():
    settings = Settings()

    session = await BrowserSession.connect_cdp(
        settings.brave_cdp_url
    )

    try:
        browser = session.browser
        context = browser.contexts[0]
        page = await context.new_page()

        await page.goto(
            DRAFT_URL,
            wait_until="domcontentloaded",
            timeout=30000,
        )

        await page.wait_for_timeout(1500)

        print()
        print("=" * 90)
        print("🌐 URL")
        print("=" * 90)
        print(page.url)

        print()
        print("=" * 90)
        print("🧾 FORMS")
        print("=" * 90)

        forms = await page.locator("form").evaluate_all(
            """
            els => els.map((el, i) => ({
                i,
                id: el.id || '',
                action: el.action || '',
                method: el.method || '',
                className:
                    typeof el.className === 'string'
                        ? el.className
                        : '',
                text: (
                    el.innerText ||
                    el.textContent ||
                    ''
                ).trim().slice(-1200)
            }))
            """
        )

        for f in forms:
            print()
            print(f"FORM #{f['i']}")
            print(f"id={f['id'] or '—'}")
            print(f"method={f['method'] or '—'}")
            print(f"action={f['action'] or '—'}")
            print(f"class={f['className'] or '—'}")
            print("TEXT:")
            print(f["text"])

        print()
        print("=" * 90)
        print("🔘 TODOS LOS CONTROLES POSIBLES")
        print("=" * 90)

        controls = await page.locator(
            """
            button,
            input,
            a,
            [role='button'],
            [onclick]
            """
        ).evaluate_all(
            """
            els => els.map((el, i) => {
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();

                return {
                    i,
                    tag: el.tagName.toLowerCase(),
                    type: el.getAttribute('type') || '',
                    id: el.id || '',
                    name: el.getAttribute('name') || '',
                    value: el.value || '',
                    text: (
                        el.innerText ||
                        el.textContent ||
                        ''
                    ).trim(),
                    aria: el.getAttribute('aria-label') || '',
                    href: el.href || '',
                    disabled: !!el.disabled,
                    visible:
                        style.display !== 'none'
                        && style.visibility !== 'hidden'
                        && rect.width > 0
                        && rect.height > 0,
                    className:
                        typeof el.className === 'string'
                            ? el.className
                            : '',
                    html: (
                        el.outerHTML || ''
                    ).slice(0, 1800)
                };
            })
            """
        )

        for c in controls:
            blob = " ".join([
                c["text"],
                c["value"],
                c["aria"],
                c["id"],
                c["name"],
                c["className"],
                c["href"],
            ]).lower()

            if (
                c["visible"]
                or "enviar" in blob
                or "submit" in blob
                or "postul" in blob
                or "application" in blob
                or "send" in blob
            ):
                print()
                print("-" * 90)
                print(
                    f"[{c['i']}] "
                    f"{c['tag']} "
                    f"type={c['type'] or '—'} "
                    f"visible={c['visible']} "
                    f"disabled={c['disabled']}"
                )
                print(f"id={c['id'] or '—'}")
                print(f"name={c['name'] or '—'}")
                print(f"value={c['value'] or '—'}")
                print(f"text={c['text'] or '—'}")
                print(f"aria={c['aria'] or '—'}")
                print(f"href={c['href'] or '—'}")
                print(f"class={c['className'] or '—'}")
                print("HTML:")
                print(c["html"])

        print()
        print("=" * 90)
        print("🛑 PROBE COMPLETO — NO SE HIZO CLICK")
        print("=" * 90)

        await page.close()

    finally:
        await session.close()


asyncio.run(main())
