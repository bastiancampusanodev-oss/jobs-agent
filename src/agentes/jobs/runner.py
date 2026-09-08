from __future__ import annotations

import json
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from agentes.browser import BrowserSession, page_visible_text, page_interactive_elements
from agentes.config import Settings
from agentes.jobs.analyzer import analyze_job
from agentes.state import StateStore


console = Console()


def print_decision(payload: dict) -> None:
    job = payload["job"]
    title = f'{payload["decision"]} · {payload["match_score"]}% · {job.get("title") or "Vacancy"}'
    body = [
        f'Company: {job.get("company") or "?"}',
        f'CV: {payload.get("cv_id") or "—"}',
        f'Salary USD/month: {payload.get("salary_usd_monthly") or "—"}',
        f'Why: {payload.get("why", "")}',
        f'Interview: {payload.get("interview_defensibility", "")}',
    ]
    if payload.get("hard_gaps"):
        body.append("Gaps: " + "; ".join(payload["hard_gaps"]))
    console.print(Panel("\n".join(body), title=title))

    answers = payload.get("form_answers") or []
    if answers:
        table = Table(title="Form answers")
        table.add_column("Question", style="bold")
        table.add_column("Answer")
        for item in answers:
            table.add_row(item["question"], item["answer"])
        console.print(table)


async def analyze_fixture(path: str, source_url: str | None = None, save: bool = True) -> dict:
    text = Path(path).read_text(encoding="utf-8")
    decision = await analyze_job(text, source_url)
    payload = decision.model_dump()
    print_decision(payload)
    if save:
        store = StateStore(Settings().db_path)
        store.save_job_result(payload, source="fixture")
    return payload


async def browser_probe() -> None:
    settings = Settings()
    session = await BrowserSession.connect_cdp(settings.brave_cdp_url)
    try:
        table = Table(title="Brave tabs visible to Playwright")
        table.add_column("#")
        table.add_column("URL")
        for i, page in enumerate(session.pages(), 1):
            table.add_row(str(i), page.url)
        console.print(table)
    finally:
        await session.close()


async def analyze_current_getonboard(save: bool = True) -> dict:
    settings = Settings()
    session = await BrowserSession.connect_cdp(settings.brave_cdp_url)
    try:
        page = session.find_page("getonbrd.com")
        if page is None:
            raise RuntimeError("No Get on Board tab found in the Brave CDP session.")
        url = page.url
        text = await page_visible_text(page)
    finally:
        await session.close()

    if not text.strip():
        raise RuntimeError("The Get on Board tab had no readable body text.")

    store = StateStore(settings.db_path)
    if save and store.has_job_url(url):
        raise RuntimeError(f"Already processed: {url}")

    decision = await analyze_job(text, url)
    payload = decision.model_dump()
    print_decision(payload)
    if save:
        store.save_job_result(payload, source="getonboard_current_tab")
    return payload


def show_recent(limit: int = 20) -> None:
    rows = StateStore(Settings().db_path).recent(limit)
    table = Table(title="Recent job-agent decisions")
    for col in ["id", "decision", "match_score", "job_title", "company", "cv_id"]:
        table.add_column(col)
    for row in rows:
        table.add_row(*(str(row.get(col, "")) for col in ["id", "decision", "match_score", "job_title", "company", "cv_id"]))
    console.print(table)


def dump_json(payload: dict) -> None:
    console.print_json(json.dumps(payload, ensure_ascii=False))


async def form_probe() -> None:
    settings = Settings()
    session = await BrowserSession.connect_cdp(settings.brave_cdp_url)

    try:
        page = session.find_page("getonbrd.com")
        if page is None:
            raise RuntimeError("No Get on Board tab found.")

        console.print(f"[bold]URL:[/bold] {page.url}")

        elements = await page_interactive_elements(page)

        table = Table(title="Interactive elements")
        table.add_column("#", width=4)
        table.add_column("Tag", width=10)
        table.add_column("Type", width=12)
        table.add_column("Name / ID", width=20)
        table.add_column("Label / Text", overflow="fold")
        table.add_column("Required", width=8)

        interesting = []

        for el in elements:
            label = (
                el.get("label")
                or el.get("aria_label")
                or el.get("placeholder")
                or el.get("text")
                or el.get("href")
                or ""
            ).strip()

            identity = el.get("name") or el.get("id") or ""

            table.add_row(
                str(el["index"]),
                el["tag"],
                el.get("type", ""),
                identity[:40],
                label[:180],
                "YES" if el.get("required") else "",
            )

            if (
                el["tag"] in {"input", "textarea", "select"}
                or el.get("contenteditable") == "true"
                or el.get("role") == "textbox"
            ):
                interesting.append(el)

        console.print(table)

        if interesting:
            console.print()
            detail = Table(title="Form fields detail")
            detail.add_column("#")
            detail.add_column("Field")
            detail.add_column("Info", overflow="fold")

            for el in interesting:
                field_name = (
                    el.get("label")
                    or el.get("aria_label")
                    or el.get("placeholder")
                    or el.get("name")
                    or el.get("id")
                    or "unnamed"
                )

                info = [
                    f'tag={el.get("tag")}',
                    f'type={el.get("type") or "—"}',
                    f'name={el.get("name") or "—"}',
                    f'id={el.get("id") or "—"}',
                    f'role={el.get("role") or "—"}',
                    f'contenteditable={el.get("contenteditable") or "—"}',
                ]

                if el.get("accept"):
                    info.append(f'accept={el["accept"]}')

                if el.get("options"):
                    opts = [
                        x["text"]
                        for x in el["options"]
                        if x.get("text")
                    ]
                    info.append("options=" + " | ".join(opts[:20]))

                detail.add_row(
                    str(el["index"]),
                    field_name[:120],
                    "\n".join(info),
                )

            console.print(detail)

    finally:
        await session.close()
