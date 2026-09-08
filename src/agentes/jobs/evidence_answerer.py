from __future__ import annotations

import re


STOPWORDS = {
    # ES
    "que", "como", "con", "para", "por", "una", "uno",
    "los", "las", "del", "desde", "sobre", "cual", "cuál",
    "tienes", "tiene", "describe", "comenta", "comente",
    "experiencia", "conocimientos", "conocimiento",
    "cargo", "trabajo",
    "tu", "tus", "su", "sus", "usted",
    "de", "en", "el", "la", "un", "es",
    "directa", "directo", "directamente",
    "utilizando", "utilizar", "usando", "usar",
    "uso", "nivel", "tecnologia", "tecnología",

    # EN
    "the", "and", "with", "for", "from", "your", "have",
    "has", "describe", "experience", "knowledge", "role",
    "work", "about",
    "in", "of", "a", "an",
    "direct", "directly",
    "using", "use", "used", "technology", "level",
}


def _norm(text: str) -> str:
    text = str(text or "").casefold()

    text = (
        text.replace("á", "a")
        .replace("é", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ú", "u")
    )

    return re.sub(
        r"\s+",
        " ",
        text,
    ).strip()


def _tokens(text: str) -> set[str]:

    raw_tokens = re.findall(
        r"[a-z0-9+#.]{2,}",
        _norm(text),
    )

    out = set()

    for token in raw_tokens:

        # Keep meaningful internal punctuation:
        #
        #   node.js  -> node.js
        #   c++      -> c++
        #   c#       -> c#
        #
        # but remove sentence punctuation:
        #
        #   kubernetes. -> kubernetes
        #
        token = token.strip(".")

        if len(token) < 2:
            continue

        if token in STOPWORDS:
            continue

        out.add(token)

    return out


def _looks_like_internal_guardrail(text: str) -> bool:
    low = _norm(text)
    markers = (
        "unless new evidence",
        "never_claim",
        "never claim",
        "do_not_upgrade",
        "do not upgrade",
        "no se puede afirmar",
        "no se debe afirmar",
        "sin evidencia adicional",
        "requires additional evidence",
        "a technology as hands-on merely because",
        "direct core de comercio exterior experience",
    )
    return any(marker in low for marker in markers)


def evidence_is_user_facing(text: str) -> bool:
    value = str(text or "").strip()
    return bool(value) and not _looks_like_internal_guardrail(value)


def _candidate_lines(
    knowledge: str,
) -> list[str]:

    text = str(
        knowledge or ""
    )

    raw_lines = text.splitlines()

    def is_yaml_key(
        raw: str,
    ) -> bool:
        return bool(
            re.match(
                r"""
                ^\s*
                (?:-\s*)?
                [A-Za-z_][A-Za-z0-9_-]{0,50}
                \s*:
                """,
                raw,
                re.VERBOSE,
            )
        )

    def clean(
        raw: str,
    ) -> str:

        line = re.sub(
            r"\s+",
            " ",
            str(raw or ""),
        ).strip()

        low = _norm(line)

        if (
            low.startswith("source:")
            or low.startswith("source cv:")
        ):
            return ""

        if _looks_like_internal_guardrail(line):
            return ""

        # Remove YAML key while preserving its actual value.
        line = re.sub(
            r"""
            ^\s*
            (?:-\s*)?
            [A-Za-z_][A-Za-z0-9_-]{0,50}
            \s*:\s*
            """,
            "",
            line,
            count=1,
            flags=re.VERBOSE,
        )

        line = line.strip(
            " \t-\"'"
        )

        if _looks_like_internal_guardrail(line):
            return ""

        return line

    candidates = []

    # --------------------------------------------------------
    # SINGLE LINES
    # --------------------------------------------------------

    cleaned = [
        clean(line)
        for line in raw_lines
    ]

    for line in cleaned:
        if 20 <= len(line) <= 500:
            candidates.append(
                line
            )

    # --------------------------------------------------------
    # JOIN WRAPPED VALUES
    #
    # Example:
    #
    # professional: "He desarrollado ... combina
    # LLMs, RAG, Playwright...
    # workflow real."
    #
    # It must become one evidence candidate.
    # --------------------------------------------------------

    for i, first in enumerate(
        cleaned
    ):
        if not first:
            continue

        parts = [
            first
        ]

        for j in range(
            i + 1,
            min(
                len(raw_lines),
                i + 6,
            ),
        ):

            # A new YAML property means a new fact.
            if is_yaml_key(
                raw_lines[j]
            ):
                break

            nxt = cleaned[j]

            if not nxt:
                break

            joined = " ".join(
                parts + [nxt]
            )

            if len(joined) > 500:
                break

            parts.append(
                nxt
            )

            # Natural sentence end.
            if re.search(
                r'[.!?]["\']?$',
                raw_lines[j].strip(),
            ):
                break

        joined = " ".join(
            parts
        ).strip(
            " \t-\"'"
        )

        if 20 <= len(joined) <= 500:
            candidates.append(
                joined
            )

    # --------------------------------------------------------
    # DEDUPE
    # --------------------------------------------------------

    out = []
    seen = set()

    for candidate in candidates:

        normalized = _norm(
            candidate
        )

        if (
            not normalized
            or normalized in seen
        ):
            continue

        seen.add(
            normalized
        )

        out.append(
            candidate
        )

    return out


def _concept_tokens(
    text: str,
) -> set[str]:
    """
    Small lexical canonicalizer.

    We do not want an LLM here. We only normalize related
    word forms so that, for example:

        automatización
        automatizar
        automation
        automated

    represent the same concept.
    """

    concepts = set()

    for token in _tokens(text):

        low = _norm(token)

        if (
            low.startswith("automat")
            or low.startswith("automati")
        ):
            concepts.add("automation")
            continue

        if low in {
            "api",
            "apis",
        }:
            concepts.add("api")
            continue

        if low in {
            "ia",
            "ai",
        }:
            concepts.add("ai")
            continue

        concepts.add(low)

    return concepts


def _language_hint(
    text: str,
) -> str:

    low = _norm(text)

    spanish_markers = (
        " describe ",
        " experiencia ",
        " tienes ",
        " conocimiento ",
        " desarrollado ",
        " automatizacion ",
        " automatizar ",
        " con ",
        " para ",
        " tu ",
    )

    english_markers = (
        " describe ",
        " experience ",
        " have you ",
        " knowledge ",
        " developed ",
        " automation ",
        " with ",
        " your ",
    )

    wrapped = f" {low} "

    es = sum(
        marker in wrapped
        for marker in spanish_markers
    )

    en = sum(
        marker in wrapped
        for marker in english_markers
    )

    if es > en:
        return "es"

    if en > es:
        return "en"

    return "unknown"


def find_best_evidence(
    question: str,
    knowledge: str,
) -> str | None:

    q_concepts = _concept_tokens(
        question
    )

    if not q_concepts:
        return None

    question_language = (
        _language_hint(question)
    )

    best = None
    best_score = -1

    # If the question contains several meaningful concepts,
    # evidence should normally cover at least two of them.
    #
    # "Python + automatización" must not match a generic line
    # that merely contains "Python".
    required_overlap = (
        1
        if len(q_concepts) <= 1
        else min(
            2,
            len(q_concepts),
        )
    )

    for line in _candidate_lines(
        knowledge
    ):

        line_concepts = (
            _concept_tokens(line)
        )

        overlap = (
            q_concepts
            & line_concepts
        )

        coverage = len(
            overlap
        )

        if coverage < required_overlap:
            continue

        # Coverage dominates the score.
        score = coverage * 100

        # Prefer evidence containing a greater fraction
        # of the question's actual concepts.
        ratio = (
            coverage
            / max(
                1,
                len(q_concepts),
            )
        )

        # Weak partial overlap must not authorize a custom answer.
        # This prevents tag clouds such as "... QA Automation" from
        # answering a multi-part question about years/role/tools.
        min_ratio = 0.34 if len(q_concepts) >= 4 else 0.50
        if ratio < min_ratio:
            continue

        score += int(
            ratio * 50
        )

        # Same-language evidence is easier to insert directly
        # into the application without generative rewriting.
        line_language = (
            _language_hint(line)
        )

        if (
            question_language != "unknown"
            and line_language == question_language
        ):
            score += 30

        # Prefer complete, interview-defensible sentences.
        if 50 <= len(line) <= 400:
            score += 15

        if re.search(
            r"[.!?]$",
            line.strip(),
        ):
            score += 8

        # Prefer richer evidence only when semantic coverage
        # is otherwise equivalent.
        if (
            score > best_score
            or (
                score == best_score
                and len(line) > len(best or "")
            )
        ):
            best_score = score
            best = line

    if best and not evidence_is_user_facing(best):
        return None

    return best


def answer_from_evidence(
    question: str,
    knowledge: str,
) -> str | None:
    """
    Extractive only.

    Returns text that already exists in the evidence.
    It never asks an LLM to invent or paraphrase facts.
    """

    return find_best_evidence(
        question,
        knowledge,
    )
