from __future__ import annotations

from dataclasses import dataclass

from playwright.async_api import Browser, Page, Playwright, async_playwright


@dataclass
class BrowserSession:
    playwright: Playwright
    browser: Browser

    @classmethod
    async def connect_cdp(cls, endpoint: str) -> "BrowserSession":
        pw = await async_playwright().start()
        browser = await pw.chromium.connect_over_cdp(endpoint, no_defaults=True)
        return cls(playwright=pw, browser=browser)

    def pages(self) -> list[Page]:
        pages: list[Page] = []
        for context in self.browser.contexts:
            pages.extend(context.pages)
        return pages

    def find_page(self, url_fragment: str) -> Page | None:
        fragment = url_fragment.lower()
        for page in self.pages():
            if fragment in page.url.lower():
                return page
        return None

    async def close(self) -> None:
        # Disconnect from the attached browser; do not close the user's Brave process.
        await self.browser.close()
        await self.playwright.stop()


async def page_visible_text(page: Page, max_chars: int = 60_000) -> str:
    text = await page.locator("body").inner_text(timeout=15_000)
    return text[:max_chars]


async def page_interactive_elements(page: Page) -> list[dict]:
    """Return visible interactive elements from the current page."""
    return await page.locator(
        """
        input,
        textarea,
        select,
        button,
        a,
        [role='button'],
        [role='textbox'],
        [contenteditable='true']
        """
    ).evaluate_all(
        """elements => elements
            .filter(el => {
                const s = window.getComputedStyle(el);
                const r = el.getBoundingClientRect();
                return s.display !== 'none'
                    && s.visibility !== 'hidden'
                    && r.width > 0
                    && r.height > 0;
            })
            .map((el, index) => {
                let label = '';

                if (el.labels && el.labels.length) {
                    label = Array.from(el.labels)
                        .map(x => x.innerText || x.textContent || '')
                        .join(' ')
                        .trim();
                }

                if (!label) {
                    const parentLabel = el.closest('label');
                    if (parentLabel) {
                        label = (parentLabel.innerText || parentLabel.textContent || '').trim();
                    }
                }

                if (!label && el.id) {
                    const external = document.querySelector(
                        `label[for="${CSS.escape(el.id)}"]`
                    );
                    if (external) {
                        label = (external.innerText || external.textContent || '').trim();
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
                    index,
                    tag: el.tagName.toLowerCase(),
                    type: el.getAttribute('type') || '',
                    id: el.id || '',
                    name: el.getAttribute('name') || '',
                    label: label,
                    aria_label: el.getAttribute('aria-label') || '',
                    role: el.getAttribute('role') || '',
                    contenteditable: el.getAttribute('contenteditable') || '',
                    placeholder: el.getAttribute('placeholder') || '',
                    text: (el.innerText || el.textContent || '').trim().slice(0, 300),
                    value: el.value || '',
                    href: el.href || '',
                    required: !!el.required,
                    disabled: !!el.disabled,
                    accept: el.getAttribute('accept') || '',
                    options
                };
            })
        """
    )
