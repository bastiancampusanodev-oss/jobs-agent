from __future__ import annotations

import argparse
import asyncio

from agentes.jobs.runner import analyze_current_getonboard, analyze_fixture, browser_probe, form_probe, show_recent
from agentes.jobs.application_runner import run_application


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Agentes personal automation factory")
    sub = parser.add_subparsers(dest="command", required=True)

    jobs = sub.add_parser("jobs", help="Job application agent")
    jobs_sub = jobs.add_subparsers(dest="jobs_command", required=True)

    fixture = jobs_sub.add_parser("fixture", help="Analyze a saved vacancy text")
    fixture.add_argument("path")
    fixture.add_argument("--url", default=None)
    fixture.add_argument("--no-save", action="store_true")

    jobs_sub.add_parser("browser-probe", help="List tabs from a Brave CDP session")

    jobs_sub.add_parser("form-probe", help="Inspect interactive fields on the current Get on Board page")

    jobs_sub.add_parser(
        "apply",
        help="Run Get on Board application flow in dry-run mode",
    )

    current = jobs_sub.add_parser("current", help="Analyze the currently open Get on Board tab")
    current.add_argument("--no-save", action="store_true")

    recent = jobs_sub.add_parser("recent", help="Show recent decisions")
    recent.add_argument("--limit", type=int, default=20)

    return parser.parse_args()


async def async_main(args: argparse.Namespace) -> None:
    if args.command != "jobs":
        raise SystemExit(2)
    if args.jobs_command == "fixture":
        await analyze_fixture(args.path, args.url, save=not args.no_save)
    elif args.jobs_command == "browser-probe":
        await browser_probe()
    elif args.jobs_command == "form-probe":
        await form_probe()
    elif args.jobs_command == "apply":
        await run_application(dry_run=True)
    elif args.jobs_command == "current":
        await analyze_current_getonboard(save=not args.no_save)
    elif args.jobs_command == "recent":
        show_recent(args.limit)


def main() -> None:
    args = parse_args()
    asyncio.run(async_main(args))


if __name__ == "__main__":
    main()
