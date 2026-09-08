from __future__ import annotations

import re
import unicodedata


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


def _visible_options(field: dict) -> list[str]:
    values = []

    for option in field.get("options") or []:

        if isinstance(option, dict):
            value = str(
                option.get("label")
                or option.get("text")
                or option.get("value")
                or ""
            ).strip()
        else:
            value = str(option or "").strip()

        if value:
            values.append(value)

    return values


def _negative_option(field: dict) -> str | None:
    options = _visible_options(field)

    exact_priority = (
        "no",
        "ninguna",
        "ninguno",
        "none",
        "n/a",
        "na",
        "no aplica",
        "not applicable",
        "sin experiencia",
        "no experience",
        "ninguna de las anteriores",
        "none of the above",
    )

    for wanted in exact_priority:
        for option in options:
            if _norm(option) == wanted:
                return option

    for option in options:
        low = _norm(option)

        if (
            low.startswith("ninguna ")
            or low.startswith("ninguno ")
            or low.startswith("none ")
            or low.startswith("no tengo ")
            or low.startswith("no cuento ")
        ):
            return option

    return None


def _pure_years_question(blob: str) -> bool:

    asks_years = any(
        marker in blob
        for marker in (
            "cuantos anos",
            "anos de experiencia",
            "how many years",
            "years of experience",
        )
    )

    if not asks_years:
        return False

    # Preguntas compuestas requieren texto, no sólo un número.
    compound = (
        " y que ",
        " y cuales ",
        " y describe ",
        " y detalla ",
        "and what",
        "and describe",
        "practicas",
        "responsabilidades",
        "cuentanos",
        "comenta",
        "describe",
        "detalla",
    )

    return not any(
        marker in blob
        for marker in compound
    )


def _simple_number(value: str) -> str | None:
    text = _norm(value)

    match = re.fullmatch(
        r"(?:aprox(?:imadamente)?\s*)?"
        r"(\d+(?:[.,]\d+)?)"
        r"(?:\s*(?:anos?|years?))?",
        text,
    )

    if not match:
        return None

    number = match.group(1).replace(",", ".")

    try:
        parsed = float(number)
    except Exception:
        return None

    if parsed < 0 or parsed > 60:
        return None

    if parsed.is_integer():
        return str(int(parsed))

    return str(parsed)


def _expected_salary_question(blob: str) -> bool:

    money = any(
        marker in blob
        for marker in (
            "salario",
            "sueldo",
            "renta",
            "remuneracion",
            "compensation",
            "salary",
            "pretension",
            "pretensiones",
        )
    )

    if not money:
        return False

    historical = any(
        marker in blob
        for marker in (
            "salario actual",
            "sueldo actual",
            "renta actual",
            "current salary",
            "most recent salary",
            "ultimo sueldo",
            "ultima renta",
            "salario mas reciente",
        )
    )

    if historical:
        return False

    # Una moneda explícita distinta requiere el motor específico
    # de currency/salary; no improvisamos conversiones aquí.
    explicit_clp = any(
        marker in blob
        for marker in (
            " clp",
            "pesos chilenos",
            "peso chileno",
        )
    )

    if explicit_clp:
        return False

    expectation = any(
        marker in blob
        for marker in (
            "expectativa",
            "pretension",
            "pretensiones",
            "esperado",
            "expected",
            "desired",
            "liquido",
            "liquida",
            "net salary",
            "salary expectation",
        )
    )

    return expectation


def normalize_custom_answer(
    field: dict,
    answer,
    *,
    salary_usd: int | float | None = None,
) -> dict:
    """
    Last deterministic semantic firewall before a CUSTOM answer
    is written to the real form.

    It never invents positive experience.
    """

    blob = _blob(field)

    kind = str(
        field.get("kind") or ""
    ).casefold()

    state = {
        "text": getattr(answer, "text", None),
        "selected": list(
            getattr(answer, "selected", None)
            or []
        ),
        "checked": getattr(
            answer,
            "checked",
            None,
        ),
        "requires_human": bool(
            getattr(
                answer,
                "requires_human",
                False,
            )
        ),
        "reason": str(
            getattr(
                answer,
                "reason",
                "",
            )
            or ""
        ),
        "changed": False,
        "gate_reason": "",
    }


    # ========================================================
    # YEARS MUST BE NUMERIC
    # ========================================================

    if (
        kind == "text"
        and _pure_years_question(blob)
    ):

        numeric = _simple_number(
            state["text"] or ""
        )

        if numeric is None:
            numeric = "0"

        if (
            state["text"] != numeric
            or state["requires_human"]
        ):
            state.update(
                text=numeric,
                selected=[],
                checked=None,
                requires_human=False,
                reason="",
                changed=True,
                gate_reason="years_numeric",
            )

        return state


    # ========================================================
    # EXPECTED SALARY MUST BE NUMERIC
    # ========================================================

    if (
        kind == "text"
        and salary_usd is not None
        and _expected_salary_question(blob)
    ):

        try:
            salary = str(
                int(float(salary_usd))
            )
        except Exception:
            salary = ""

        if salary:

            if (
                str(state["text"] or "").strip()
                != salary
                or state["requires_human"]
            ):
                state.update(
                    text=salary,
                    selected=[],
                    checked=None,
                    requires_human=False,
                    reason="",
                    changed=True,
                    gate_reason="expected_salary_numeric",
                )

            return state


    # ========================================================
    # REQUIRED CHECKBOX:
    # use an explicit negative option if the form provides one.
    #
    # We do NOT select a positive experience claim without evidence.
    # ========================================================

    if (
        kind == "checkbox"
        and state["requires_human"]
    ):

        negative = _negative_option(
            field
        )

        if negative:
            state.update(
                text=None,
                selected=[negative],
                checked=None,
                requires_human=False,
                reason="",
                changed=True,
                gate_reason="checkbox_explicit_negative",
            )

        return state


    # ========================================================
    # SELECT/RADIO:
    # if an unresolved answer has an explicit negative choice,
    # prefer that rather than inventing a positive claim.
    # ========================================================

    if (
        kind in {"radio", "select"}
        and state["requires_human"]
    ):

        negative = _negative_option(
            field
        )

        if negative:
            state.update(
                text=None,
                selected=[negative],
                checked=None,
                requires_human=False,
                reason="",
                changed=True,
                gate_reason="choice_explicit_negative",
            )

        return state


    return state
