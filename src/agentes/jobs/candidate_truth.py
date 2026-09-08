from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml

from agentes.jobs.evidence_answerer import _concept_tokens


TruthStatus = Literal[
    "confirmed",
    "denied",
    "guarded",
    "unknown",
]


@dataclass(frozen=True)
class TruthEvidence:
    text: str
    organization: str | None = None
    role: str | None = None


@dataclass(frozen=True)
class TruthResult:
    status: TruthStatus
    concepts: tuple[str, ...]
    evidence: tuple[TruthEvidence, ...] = ()
    reason: str = ""


PROJECT_ROOT = (
    Path(__file__)
    .resolve()
    .parents[3]
)

CANDIDATE_PATH = (
    PROJECT_ROOT
    / "config"
    / "candidate.yaml"
)


def _norm(value: str) -> str:
    text = str(value or "").casefold()

    text = "".join(
        char
        for char in unicodedata.normalize(
            "NFKD",
            text,
        )
        if not unicodedata.combining(
            char
        )
    )

    return " ".join(
        text.split()
    )


@lru_cache(maxsize=1)
def _candidate() -> dict:

    with CANDIDATE_PATH.open(
        "r",
        encoding="utf-8",
    ) as handle:

        data = yaml.safe_load(
            handle
        )

    if not isinstance(
        data,
        dict,
    ):
        raise RuntimeError(
            "candidate.yaml inválido"
        )

    return data


def _confirmed_evidence() -> list[
    TruthEvidence
]:

    data = _candidate()

    result = []

    skills = (
        data.get("skills", {})
        .get(
            "hands_on_or_professionally_defensible",
            [],
        )
    )

    for skill in skills:
        result.append(
            TruthEvidence(
                text=str(skill),
            )
        )

    for experience in data.get(
        "experience",
        [],
    ):

        role = str(
            experience.get(
                "role",
                "",
            )
        )

        organization = str(
            experience.get(
                "organization",
                "",
            )
        )

        for fact in experience.get(
            "facts",
            [],
        ):
            result.append(
                TruthEvidence(
                    text=str(fact),
                    organization=(
                        organization
                        or None
                    ),
                    role=(
                        role
                        or None
                    ),
                )
            )

    return result


def _guarded_entries() -> list[str]:

    data = _candidate()

    return [
        str(item)
        for item in (
            data.get("skills", {})
            .get(
                "do_not_upgrade_to_expert_without_evidence",
                [],
            )
        )
    ]


def _denied_entries() -> list[str]:

    data = _candidate()

    return [
        str(item)
        for item in (
            data.get(
                "truth_guardrails",
                {},
            )
            .get(
                "never_claim",
                [],
            )
        )
    ]


def _concept_in_text(
    concept: str,
    text: str,
) -> bool:

    concepts = _concept_tokens(
        text
    )

    return concept in concepts


def _entry_covers_question(
    entry: str,
    concepts: set[str],
) -> bool:

    if not concepts:
        return False

    entry_concepts = (
        _concept_tokens(entry)
    )

    overlap = (
        concepts
        & entry_concepts
    )

    # Require most meaningful query concepts to appear.
    return (
        len(overlap)
        / len(concepts)
    ) >= 0.75


def lookup_candidate_truth(
    question: str,
) -> TruthResult:

    concepts = set(
        _concept_tokens(
            question
        )
    )

    if not concepts:
        return TruthResult(
            status="unknown",
            concepts=(),
            reason=(
                "No se detectaron conceptos "
                "significativos."
            ),
        )

    # --------------------------------------------------------
    # EXPLICIT NEVER-CLAIM GUARDRAILS
    # --------------------------------------------------------

    for entry in _denied_entries():

        if _entry_covers_question(
            entry,
            concepts,
        ):
            return TruthResult(
                status="denied",
                concepts=tuple(
                    sorted(concepts)
                ),
                reason=(
                    "El perfil contiene un guardrail "
                    "explícito de no afirmar esta experiencia."
                ),
            )

    # --------------------------------------------------------
    # CONFIRMED PROFESSIONAL / HANDS-ON EVIDENCE
    # --------------------------------------------------------

    all_evidence = (
        _confirmed_evidence()
    )

    matched = []

    concepts_confirmed = set()

    for evidence in all_evidence:

        matched_concepts = {
            concept
            for concept in concepts
            if _concept_in_text(
                concept,
                evidence.text,
            )
        }

        if not matched_concepts:
            continue

        concepts_confirmed.update(
            matched_concepts
        )

        matched.append(
            evidence
        )

    if (
        concepts
        and concepts.issubset(
            concepts_confirmed
        )
    ):
        return TruthResult(
            status="confirmed",
            concepts=tuple(
                sorted(concepts)
            ),
            evidence=tuple(
                matched
            ),
            reason=(
                "Todos los conceptos aparecen "
                "en evidencia factual del candidato."
            ),
        )

    # --------------------------------------------------------
    # GUARDED / DO-NOT-UPGRADE
    # --------------------------------------------------------

    for entry in _guarded_entries():

        if _entry_covers_question(
            entry,
            concepts,
        ):
            return TruthResult(
                status="guarded",
                concepts=tuple(
                    sorted(concepts)
                ),
                reason=(
                    "La tecnología aparece en una zona "
                    "que requiere evidencia adicional "
                    "antes de elevar el nivel de experiencia."
                ),
            )

    # --------------------------------------------------------
    # UNKNOWN != NO
    # --------------------------------------------------------

    return TruthResult(
        status="unknown",
        concepts=tuple(
            sorted(concepts)
        ),
        evidence=tuple(
            matched
        ),
        reason=(
            "No existe evidencia suficiente para "
            "confirmar ni negar la experiencia."
        ),
    )
