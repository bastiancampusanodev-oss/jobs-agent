from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field as dc_field
from typing import Optional


@dataclass
class AutonomousAnswer:
    text: Optional[str] = None
    selected: list[str] = dc_field(default_factory=list)
    checked: Optional[bool] = None


def _norm(value: str) -> str:
    raw = unicodedata.normalize(
        "NFKD",
        str(value or "").casefold(),
    )

    raw = "".join(
        ch
        for ch in raw
        if not unicodedata.combining(ch)
    )

    return re.sub(
        r"\s+",
        " ",
        raw,
    ).strip()


def _blob(field: dict) -> str:
    return _norm(
        " ".join(
            str(field.get(key) or "")
            for key in (
                "field_key",
                "label",
                "name",
                "id",
            )
        )
    )


def _options(field: dict) -> list[str]:
    values = []

    for option in field.get("options") or []:

        if isinstance(option, dict):
            visible = str(
                option.get("label")
                or option.get("value")
                or ""
            ).strip()

        else:
            visible = str(
                option or ""
            ).strip()

        if visible:
            values.append(visible)

    return values


def _negative_option(field: dict) -> str | None:
    options = _options(field)

    priorities = (
        "no",
        "0",
        "0 anos",
        "0 years",
        "sin experiencia",
        "no experience",
        "ninguna",
        "ninguno",
        "none",
        "no aplica",
        "not applicable",
        "n/a",
        "prefiero no responder",
        "prefer not to say",
        "menos de 1 ano",
        "less than 1 year",
    )

    for wanted in priorities:

        for option in options:
            value = _norm(option)

            if (
                value == wanted
                or value.startswith(
                    wanted + " "
                )
            ):
                return option

    # Si son rangos numéricos, usar el mínimo.
    numeric = []

    for option in options:

        match = re.search(
            r"\b(\d+(?:[.,]\d+)?)\b",
            _norm(option),
        )

        if not match:
            continue

        try:
            number = float(
                match.group(1).replace(
                    ",",
                    ".",
                )
            )

        except Exception:
            continue

        numeric.append(
            (number, option)
        )

    if numeric:
        numeric.sort(
            key=lambda x: x[0]
        )

        return numeric[0][1]

    # Seniority/skill: elegir la opción
    # que menos sobredeclare experiencia.
    conservative_terms = (
        "junior",
        "jr",
        "beginner",
        "basic",
        "basico",
        "básico",
        "entry",
    )

    for option in options:
        value = _norm(option)

        if any(
            term in value
            for term in conservative_terms
        ):
            return option

    return None


def autonomous_answer(
    field: dict,
    *,
    salary_usd: int | float | None = None,
) -> AutonomousAnswer | None:

    blob = _blob(field)

    kind = str(
        field.get("kind") or ""
    ).casefold()

    spanish = any(
        word in blob
        for word in (
            "experiencia",
            "tienes",
            "cuantos",
            "anos",
            "trabajado",
            "comenta",
            "describe",
            "cual",
            "salario",
            "renta",
        )
    )

    # ========================================================
    # TEXT
    # ========================================================

    if kind == "text":

        # Exact years:
        # never fabricate tenure.
        if any(
            term in blob
            for term in (
                "cuantos anos",
                "cuántos años",
                "anos de experiencia",
                "años de experiencia",
                "how many years",
                "years of experience",
            )
        ):
            return AutonomousAnswer(
                text="0"
            )

        # Expected compensation:
        # use the already-computed JobDecision value.
        if (
            salary_usd is not None
            and any(
                term in blob
                for term in (
                    "expectativa salarial",
                    "expectativas salariales",
                    "pretension de renta",
                    "pretensión de renta",
                    "pretensiones de renta",
                    "expected salary",
                    "salary expectation",
                )
            )
        ):
            return AutonomousAnswer(
                text=str(
                    int(float(salary_usd))
                )
            )

        # Current/historical salary:
        # do not invent it; answer professionally.
        if any(
            term in blob
            for term in (
                "salario actual",
                "sueldo actual",
                "renta actual",
                "salario mas reciente",
                "salario más reciente",
                "current salary",
                "most recent salary",
            )
        ):

            if spanish:

                if salary_usd is not None:
                    return AutonomousAnswer(
                        text=(
                            "Prefiero no indicar mi "
                            "remuneración histórica. "
                            "Para esta oportunidad mi "
                            "expectativa es aproximadamente "
                            f"USD {int(float(salary_usd))} "
                            "mensuales, conversable."
                        )
                    )

                return AutonomousAnswer(
                    text=(
                        "Prefiero no indicar mi "
                        "remuneración histórica."
                    )
                )

            if salary_usd is not None:
                return AutonomousAnswer(
                    text=(
                        "I prefer not to disclose my "
                        "historical compensation. "
                        "For this opportunity my expectation "
                        f"is approximately USD "
                        f"{int(float(salary_usd))} per month, "
                        "negotiable."
                    )
                )

            return AutonomousAnswer(
                text=(
                    "I prefer not to disclose my "
                    "historical compensation."
                )
            )

        # Passwords / OTP / identity numbers:
        # respond without inventing a secret.
        if any(
            term in blob
            for term in (
                "password",
                "contrasena",
                "contraseña",
                "verification code",
                "codigo de verificacion",
                "código de verificación",
                "one time password",
                "otp",
                "2fa",
                "numero de rut",
                "número de rut",
                "passport number",
                "numero de pasaporte",
                "número de pasaporte",
            )
        ):

            return AutonomousAnswer(
                text=(
                    "Prefiero no ingresar credenciales "
                    "o identificadores sensibles en una "
                    "pregunta abierta."
                    if spanish
                    else
                    "I prefer not to enter credentials "
                    "or sensitive identifiers in an "
                    "open application question."
                )
            )

        # Generic truthful last resort.
        if spanish:
            return AutonomousAnswer(
                text=(
                    "No cuento con experiencia directa "
                    "documentada específicamente en lo "
                    "consultado. Mi experiencia relacionada "
                    "incluye desarrollo de software, "
                    "automatización, APIs, cloud/DevOps, "
                    "datos, observabilidad, operación de "
                    "sistemas y soluciones con IA, LLMs, "
                    "RAG y agentes autónomos. Prefiero "
                    "describir mi experiencia con precisión "
                    "antes que atribuirme conocimientos que "
                    "no pueda respaldar."
                )
            )

        return AutonomousAnswer(
            text=(
                "I do not have documented direct experience "
                "specifically in the area being asked about. "
                "My related experience includes software "
                "development, automation, APIs, cloud/DevOps, "
                "data, observability, systems operations and "
                "AI solutions including LLMs, RAG and "
                "autonomous agents. I prefer to describe my "
                "experience accurately rather than claim "
                "experience I cannot support."
            )
        )

    # ========================================================
    # RADIO / SELECT
    # ========================================================

    if kind in {
        "radio",
        "select",
    }:

        selected = _negative_option(
            field
        )

        if selected:
            return AutonomousAnswer(
                selected=[selected]
            )

        # No honest conservative choice can be inferred.
        # Let existing safety logic handle this rare case.
        return None

    # ========================================================
    # CHECKBOX
    # ========================================================

    if kind == "checkbox":

        # Unknown claim/consent is never silently asserted.
        return AutonomousAnswer(
            checked=False
        )

    return None
