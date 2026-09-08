from __future__ import annotations

from dataclasses import dataclass

from agentes.config import load_yaml
from agentes.jobs.job_language_policy import detect_job_language


@dataclass(frozen=True)
class CvLanguageAlignment:
    job_language: str
    original_cv_id: str
    resolved_cv_id: str
    original_cv_language: str | None
    changed: bool
    pair_found: bool


def _catalog() -> list[dict]:
    data = load_yaml("config/cvs.yaml")
    rows = data.get("cvs", [])
    return [row for row in rows if isinstance(row, dict)]


def resolve_cv_language(cv_id: str | None, job_text: str) -> CvLanguageAlignment:
    """
    Keep the CV profile/family selected by the decision engine, but make
    the document language deterministic from the current job posting.

    Example:
      01_ES (AI profile) + English vacancy -> 02_EN (same AI profile).

    If the catalog has no matching language pair, the original CV is kept
    and pair_found=False so callers may block an irreversible submit.
    """

    original = str(cv_id or "").strip()
    job_language = detect_job_language(job_text)
    rows = _catalog()

    current = next(
        (
            row
            for row in rows
            if str(row.get("id", "")).strip() == original
        ),
        None,
    )

    if current is None:
        return CvLanguageAlignment(
            job_language=job_language,
            original_cv_id=original,
            resolved_cv_id=original,
            original_cv_language=None,
            changed=False,
            pair_found=False,
        )

    current_language = str(current.get("language", "")).casefold() or None

    if current_language == job_language:
        return CvLanguageAlignment(
            job_language=job_language,
            original_cv_id=original,
            resolved_cv_id=original,
            original_cv_language=current_language,
            changed=False,
            pair_found=True,
        )

    profile = str(current.get("profile", "")).strip()
    paired = next(
        (
            row
            for row in rows
            if str(row.get("profile", "")).strip() == profile
            and str(row.get("language", "")).casefold() == job_language
        ),
        None,
    )

    if paired is None:
        return CvLanguageAlignment(
            job_language=job_language,
            original_cv_id=original,
            resolved_cv_id=original,
            original_cv_language=current_language,
            changed=False,
            pair_found=False,
        )

    resolved = str(paired.get("id", "")).strip()

    return CvLanguageAlignment(
        job_language=job_language,
        original_cv_id=original,
        resolved_cv_id=resolved,
        original_cv_language=current_language,
        changed=(resolved != original),
        pair_found=True,
    )
