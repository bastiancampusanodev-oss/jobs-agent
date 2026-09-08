from __future__ import annotations

from datetime import datetime
from pathlib import Path

import re
import yaml


ROOT = (
    Path(__file__)
    .resolve()
    .parents[3]
)

CANDIDATE_PATH = (
    ROOT
    / "config"
    / "candidate.yaml"
)


def _norm(text: str) -> str:
    return re.sub(
        r"\s+",
        " ",
        str(text or "").casefold(),
    ).strip()


def _load_experience() -> list[dict]:
    data = yaml.safe_load(
        CANDIDATE_PATH.read_text(
            encoding="utf-8"
        )
    ) or {}

    return list(
        data.get("experience")
        or []
    )


def _parse_period(
    period: str,
) -> tuple[int | None, int | None]:

    text = str(
        period or ""
    ).strip().casefold()

    years = [
        int(x)
        for x in re.findall(
            r"\b(20\d{2})\b",
            text,
        )
    ]

    if not years:
        return None, None

    start = years[0]

    if (
        "present" in text
        or "actual" in text
        or "presente" in text
    ):
        end = datetime.now().year

    elif len(years) >= 2:
        end = years[1]

    else:
        end = start

    return start, end


def _period_text(
    period: str,
) -> str:
    start, end = _parse_period(
        period
    )

    if start is None:
        return "duración no especificada"

    current = datetime.now().year

    # A single current-year period does NOT justify
    # claiming a full year.
    if (
        start == end
        and start == current
    ):
        return "menos de 1 año"

    if start == end:
        return "menos de 1 año"

    years = max(
        0,
        end - start,
    )

    if years == 1:
        return "aproximadamente 1 año"

    return (
        f"aproximadamente {years} años"
    )


def build_sre_devops_duration_answer(
    question: str,
) -> str | None:
    """
    Answers specifically about years in SRE / DevOps /
    cloud-operations roles using candidate.yaml.

    We keep direct cloud/SRE experience separate from
    adjacent systems-administration experience.
    """

    low = _norm(
        question
    )

    duration_terms = (
        "cuantos años",
        "cuántos años",
        "how many years",
        "years of experience",
    )

    role_terms = (
        "sre",
        "devops",
        "operaciones cloud",
        "cloud operations",
    )

    if not (
        any(
            x in low
            for x in duration_terms
        )
        and any(
            x in low
            for x in role_terms
        )
    ):
        return None

    experience = _load_experience()

    direct = []
    adjacent = []

    for item in experience:

        role = str(
            item.get("role")
            or ""
        )

        org = str(
            item.get("organization")
            or ""
        )

        period = str(
            item.get("period")
            or ""
        )

        facts = [
            str(x)
            for x in (
                item.get("facts")
                or []
            )
        ]

        blob = _norm(
            " ".join(
                [
                    role,
                    *facts,
                ]
            )
        )

        # Direct evidence for this specific question.
        if any(
            marker in blob
            for marker in (
                "sre",
                "devops",
                "cloud environments",
                "cloud operations",
                "operaciones cloud",
            )
        ):
            direct.append(
                {
                    "role": role,
                    "organization": org,
                    "period": period,
                }
            )

            continue

        # Relevant infrastructure/operations background,
        # but NOT relabeled as formal SRE/DevOps.
        if any(
            marker in blob
            for marker in (
                "administrador de sistemas",
                "systems administrator",
                "systems and server administration",
            )
        ):
            adjacent.append(
                {
                    "role": role,
                    "organization": org,
                    "period": period,
                }
            )

    spanish = (
        "¿" in question
        or any(
            marker in low
            for marker in (
                "cuantos",
                "cuántos",
                "años",
                "experiencia",
                "trabajando",
                "operaciones",
            )
        )
    )

    if not direct:
        return None

    primary = direct[0]

    direct_duration = _period_text(
        primary["period"]
    )

    if adjacent:
        secondary = adjacent[0]

        adjacent_duration = _period_text(
            secondary["period"]
        )

        if spanish:
            return (
                f"En roles directamente relacionados con "
                f"operaciones cloud cuento con {direct_duration} "
                f"de experiencia, respaldada por mi trabajo en "
                f"{primary['organization']} durante "
                f"{primary['period']}. Además, cuento con "
                f"{adjacent_duration} como "
                f"{secondary['role']} "
                f"({secondary['period']}), con experiencia "
                f"relevante en infraestructura y operaciones. "
                f"Distingo esta trayectoria de un rol "
                f"SRE/DevOps formal."
            )

        return (
            f"I have {direct_duration} of experience in a role "
            f"directly related to cloud operations, supported by "
            f"my work at {primary['organization']} during "
            f"{primary['period']}. In addition, I have "
            f"{adjacent_duration} as a {secondary['role']} "
            f"({secondary['period']}), providing relevant "
            f"infrastructure and operations experience. "
            f"I keep that background distinct from a formal "
            f"SRE/DevOps role."
        )

    if spanish:
        return (
            f"Cuento con {direct_duration} de experiencia "
            f"directamente relacionada con operaciones cloud "
            f"en {primary['organization']} "
            f"({primary['period']})."
        )

    return (
        f"I have {direct_duration} of experience directly "
        f"related to cloud operations at "
        f"{primary['organization']} "
        f"({primary['period']})."
    )
