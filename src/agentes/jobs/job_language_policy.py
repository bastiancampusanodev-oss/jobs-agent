from __future__ import annotations

import re
import unicodedata


def _norm(text: str) -> str:
    raw = unicodedata.normalize("NFKD", str(text or "").casefold())
    raw = "".join(ch for ch in raw if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", raw).strip()


def _first_marker(blob: str, markers: tuple[str, ...]) -> int | None:
    hits = [blob.find(marker) for marker in markers if marker in blob]
    return min(hits) if hits else None


def detect_job_language(text: str) -> str:
    """
    Resolve the language that should be used for the application artifacts.

    Explicit application-language instructions from the job board have
    absolute priority over generic UI/body-language heuristics. This avoids
    Spanish Get on Board chrome flipping an English-required vacancy to ES.
    """

    blob = f" {_norm(str(text or '')[:20000])} "

    explicit_en = (
        " requires applying in english ",
        " requires application in english ",
        " apply in english ",
        " application must be in english ",
        " please apply in english ",
        " application in english ",
        " requiere postular en ingles ",
        " debes postular en ingles ",
        " postulacion debe ser en ingles ",
        " postular en idioma ingles ",
    )
    explicit_es = (
        " requires applying in spanish ",
        " requires application in spanish ",
        " apply in spanish ",
        " application must be in spanish ",
        " please apply in spanish ",
        " application in spanish ",
        " requiere postular en espanol ",
        " debes postular en espanol ",
        " postulacion debe ser en espanol ",
        " postular en idioma espanol ",
    )

    en_pos = _first_marker(blob, explicit_en)
    es_pos = _first_marker(blob, explicit_es)

    if en_pos is not None and es_pos is None:
        return "en"
    if es_pos is not None and en_pos is None:
        return "es"
    if en_pos is not None and es_pos is not None:
        return "en" if en_pos <= es_pos else "es"

    # Fallback: score job-content signals by occurrence count. Repeated
    # content from the job description therefore outweighs a few localized
    # navigation labels from the surrounding site UI.
    en_markers = (
        " we are looking ",
        " what we're looking for ",
        " what we are looking for ",
        " responsibilities ",
        " requirements ",
        " experience ",
        " proficiency ",
        " hands-on ",
        " you should ",
        " you will ",
        " your ",
        " developer ",
        " engineer ",
        " role ",
        " position ",
        " skills ",
    )
    es_markers = (
        " buscamos ",
        " lo que buscamos ",
        " responsabilidades ",
        " requisitos ",
        " experiencia ",
        " conocimientos ",
        " funciones ",
        " deberas ",
        " debera ",
        " desarrollador ",
        " ingeniero ",
        " cargo ",
        " habilidades ",
    )

    en_score = sum(blob.count(marker) for marker in en_markers)
    es_score = sum(blob.count(marker) for marker in es_markers)

    return "en" if en_score > es_score else "es"
