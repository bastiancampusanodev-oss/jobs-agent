from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Literal


SalarySource = Literal[
    "published_range",
    "published_fixed",
    "market",
]


@dataclass(frozen=True)
class SalaryQuote:
    amount_usd_monthly: int
    source: SalarySource
    negotiable: bool
    reason: str

    published_min_usd_monthly: int | None = None
    published_max_usd_monthly: int | None = None

    original_currency: str | None = None
    original_period: str | None = None


# ============================================================
# GENERAL
# ============================================================

def _norm(text: str) -> str:
    return (
        str(text or "")
        .replace("\u00a0", " ")
        .replace("\u202f", " ")
    )


def _round_50(value: float) -> int:
    return max(
        1,
        int(round(value / 50.0) * 50),
    )


def _parse_number(raw: str) -> float | None:
    s = (
        _norm(raw)
        .strip()
        .lower()
        .replace(" ", "")
    )

    if not s:
        return None

    multiplier = 1.0

    if s.endswith("k"):
        multiplier = 1_000.0
        s = s[:-1]

    elif s.endswith("m"):
        multiplier = 1_000_000.0
        s = s[:-1]

    # 2.5k / 2,5k
    if multiplier != 1.0:
        if "," in s and "." not in s:
            s = s.replace(",", ".")
        elif "," in s and "." in s:
            s = s.replace(",", "")

    else:
        # 2.500.000 / 2,500,000
        if re.fullmatch(
            r"\d{1,3}(?:[.,]\d{3})+",
            s,
        ):
            s = re.sub(
                r"[.,]",
                "",
                s,
            )

        # 2.5 / 2,5
        elif re.fullmatch(
            r"\d+[.,]\d{1,2}",
            s,
        ):
            s = s.replace(",", ".")

        else:
            s = re.sub(
                r"[.,]",
                "",
                s,
            )

    try:
        return float(s) * multiplier
    except ValueError:
        return None


# ============================================================
# PARSE PUBLISHED SALARY
# ============================================================

_CURRENCY = (
    r"(?:USD\s*\$?|US\$|CLP\s*\$?|\$)"
)

_NUMBER = (
    r"\d(?:[\d., ]*\d)?"
    r"(?:[kKmM](?![A-Za-z]))?"
)

_RANGE_RE = re.compile(
    rf"""(?ix)
    (?P<currency>{_CURRENCY})?\s*
    (?P<a>{_NUMBER})
    \s*(?:-|–|—|to|a|hasta)\s*
    (?P<currency2>{_CURRENCY})?\s*
    (?P<b>{_NUMBER})
    """
)

_FIXED_RE = re.compile(
    rf"""(?ix)
    (?P<currency>{_CURRENCY})\s*
    (?P<a>{_NUMBER})
    """
)

_SALARY_HINTS = (
    "salary",
    "salary range",
    "compensation",
    "pay range",
    "sueldo",
    "renta ofrecida",
    "rango salarial",
    "remuneración",
    "remuneracion",
)


def _currency_from_context(
    token: str | None,
    a: float,
    b: float | None,
    context: str,
) -> str:

    token_norm = (
        token or ""
    ).upper().replace(" ", "")

    context_upper = context.upper()

    if (
        "CLP" in token_norm
        or "CLP" in context_upper
    ):
        return "CLP"

    if (
        "USD" in token_norm
        or "US$" in token_norm
        or "USD" in context_upper
        or "US$" in context_upper
    ):
        return "USD"

    highest = max(
        a,
        b if b is not None else a,
    )

    # "$2.500.000" → casi seguro CLP.
    if highest >= 100_000:
        return "CLP"

    return "USD"


def _period_from_context(
    context: str,
    currency: str,
    highest: float,
) -> str:

    low = context.casefold()

    annual_terms = (
        "annual",
        "annually",
        "yearly",
        "per year",
        "/year",
        "/yr",
        "al año",
        "anual",
        "anuales",
        "/año",
    )

    monthly_terms = (
        "monthly",
        "per month",
        "/month",
        "/mo",
        "mensual",
        "mensuales",
        "al mes",
        "/mes",
    )

    if any(
        x in low
        for x in annual_terms
    ):
        return "annual"

    if any(
        x in low
        for x in monthly_terms
    ):
        return "monthly"

    # Inferencia conservadora por magnitud.
    if (
        currency == "USD"
        and highest >= 25_000
    ):
        return "annual"

    if (
        currency == "CLP"
        and highest >= 20_000_000
    ):
        return "annual"

    return "monthly"


def _to_usd_monthly(
    amount: float,
    currency: str,
    period: str,
) -> float:

    value = amount

    if period == "annual":
        value /= 12.0

    if currency == "CLP":

        # Configurable.
        # NO es una cotización FX en tiempo real.
        clp_per_usd = float(
            os.getenv(
                "SALARY_CLP_PER_USD",
                "950",
            )
        )

        if clp_per_usd <= 0:
            clp_per_usd = 950.0

        value /= clp_per_usd

    return value


def _segments(
    job_text: str,
) -> list[str]:

    text = _norm(job_text)

    lines = [
        re.sub(
            r"\s+",
            " ",
            line,
        ).strip()
        for line in text.splitlines()
        if line.strip()
    ]

    interesting = []

    for line in lines:
        low = line.casefold()

        if (
            any(
                hint in low
                for hint in _SALARY_HINTS
            )
            or "usd" in low
            or "us$" in low
            or "clp" in low
            or re.search(
                r"\$\s*\d",
                line,
            )
        ):
            interesting.append(line)

    if not interesting:
        interesting = [
            re.sub(
                r"\s+",
                " ",
                text,
            )[:12000]
        ]

    return interesting


def _published_quote(
    job_text: str,
) -> SalaryQuote | None:

    # --------------------------------------------------------
    # RANGE
    # --------------------------------------------------------

    for segment in _segments(job_text):

        for match in _RANGE_RE.finditer(
            segment
        ):
            a = _parse_number(
                match.group("a")
            )
            b = _parse_number(
                match.group("b")
            )

            if (
                a is None
                or b is None
            ):
                continue

            low_raw, high_raw = sorted(
                (a, b)
            )

            currency = _currency_from_context(
                (
                    match.group("currency")
                    or match.group("currency2")
                ),
                low_raw,
                high_raw,
                segment,
            )

            period = _period_from_context(
                segment,
                currency,
                high_raw,
            )

            low_usd = _to_usd_monthly(
                low_raw,
                currency,
                period,
            )

            high_usd = _to_usd_monthly(
                high_raw,
                currency,
                period,
            )

            # Evitar años, versiones, etc.
            if high_usd < 300:
                continue

            # Competitive floor policy:
            # if the employer publishes a range, request
            # exactly the lower bound of that range.
            #
            # Example:
            # USD 1000-1500 -> USD 1000.
            target = int(
                round(low_usd)
            )

            # HARD GUARANTEE:
            # nunca salir del rango publicado.
            target = int(
                min(
                    max(
                        target,
                        int(round(low_usd)),
                    ),
                    int(round(high_usd)),
                )
            )

            return SalaryQuote(
                amount_usd_monthly=target,
                source="published_range",
                negotiable=False,
                reason=(
                    "Rango salarial publicado; "
                    "política competitiva: mínimo "
                    "de la banda."
                ),
                published_min_usd_monthly=int(
                    round(low_usd)
                ),
                published_max_usd_monthly=int(
                    round(high_usd)
                ),
                original_currency=currency,
                original_period=period,
            )

    # --------------------------------------------------------
    # FIXED
    # --------------------------------------------------------

    for segment in _segments(job_text):

        for match in _FIXED_RE.finditer(
            segment
        ):
            amount = _parse_number(
                match.group("a")
            )

            if amount is None:
                continue

            currency = _currency_from_context(
                match.group("currency"),
                amount,
                None,
                segment,
            )

            period = _period_from_context(
                segment,
                currency,
                amount,
            )

            usd = _to_usd_monthly(
                amount,
                currency,
                period,
            )

            if usd < 300:
                continue

            target = _round_50(
                usd
            )

            return SalaryQuote(
                amount_usd_monthly=target,
                source="published_fixed",
                negotiable=False,
                reason=(
                    "Monto salarial fijo publicado."
                ),
                published_min_usd_monthly=int(
                    round(usd)
                ),
                published_max_usd_monthly=int(
                    round(usd)
                ),
                original_currency=currency,
                original_period=period,
            )

    return None


# ============================================================
# MARKET ENGINE
# ============================================================

_MARKET_USD = {

    "software": {
        "junior": 1800,
        "mid": 2500,
        "senior": 3400,
        "lead": 4200,
    },

    "ai": {
        "junior": 2200,
        "mid": 3300,
        "senior": 4600,
        "lead": 5600,
    },

    "devops": {
        "junior": 1850,
        "mid": 2450,
        "senior": 3200,
        "lead": 4000,
    },

    "data": {
        "junior": 1650,
        "mid": 2650,
        "senior": 3450,
        "lead": 4200,
    },

    "qa": {
        "junior": 1500,
        "mid": 2100,
        "senior": 2800,
        "lead": 3400,
    },

    "support": {
        "junior": 1300,
        "mid": 1800,
        "senior": 2400,
        "lead": 3000,
    },

    "analyst": {
        "junior": 1600,
        "mid": 2300,
        "senior": 3100,
        "lead": 3800,
    },
}


def _detect_seniority(
    structured: str,
    full_blob: str,
) -> str:

    def detect(text: str):
        low = text.casefold()

        if any(
            x in low
            for x in (
                "staff",
                "principal",
                "lead",
                "tech lead",
                "architect",
                "arquitect",
                "jefe",
            )
        ):
            return "lead"

        if any(
            x in low
            for x in (
                "semi senior",
                "semi-senior",
                "mid level",
                "mid-level",
                "intermediate",
            )
        ):
            return "mid"

        if any(
            x in low
            for x in (
                "senior",
                "sr.",
                "sr ",
            )
        ):
            return "senior"

        if any(
            x in low
            for x in (
                "junior",
                "jr.",
                "jr ",
                "entry level",
            )
        ):
            return "junior"

        return None

    return (
        detect(structured)
        or detect(full_blob)
        or "mid"
    )


def _detect_family(
    blob: str,
) -> str:

    low = blob.casefold()

    if any(
        x in low
        for x in (
            "artificial intelligence",
            "inteligencia artificial",
            "machine learning",
            "llm",
            "rag",
            "ai engineer",
            "ml engineer",
            "agentic",
        )
    ):
        return "ai"

    if any(
        x in low
        for x in (
            "devops",
            "sre",
            "cloud",
            "platform engineer",
            "kubernetes",
            "infrastructure",
            "infraestructura",
            "devsecops",
        )
    ):
        return "devops"

    if any(
        x in low
        for x in (
            "data engineer",
            "data scientist",
            "analytics",
            "business intelligence",
            "big data",
            "ingeniero de datos",
            "científico de datos",
            "cientifico de datos",
        )
    ):
        return "data"

    if any(
        x in low
        for x in (
            "qa",
            "tester",
            "testing",
            "quality assurance",
        )
    ):
        return "qa"

    if any(
        x in low
        for x in (
            "support",
            "soporte",
            "help desk",
            "service desk",
            "operaciones ti",
        )
    ):
        return "support"

    if any(
        x in low
        for x in (
            "business analyst",
            "business systems",
            "analista funcional",
            "analista de sistemas",
        )
    ):
        return "analyst"

    return "software"


def _market_quote(
    decision,
    job_text: str,
) -> SalaryQuote:

    job = getattr(
        decision,
        "job",
        None,
    )

    title = (
        getattr(job, "title", "")
        if job
        else ""
    )

    seniority_raw = (
        getattr(job, "seniority", "")
        if job
        else ""
    )

    structured = (
        f"{title} {seniority_raw}"
    )

    parts = [
        job_text[:10000],
        structured,
        getattr(
            job,
            "location",
            "",
        ) if job else "",
        getattr(
            job,
            "modality",
            "",
        ) if job else "",
        getattr(
            job,
            "contract",
            "",
        ) if job else "",
        getattr(
            decision,
            "why",
            "",
        ),
    ]

    blob = " ".join(
        str(x or "")
        for x in parts
    )

    family = _detect_family(
        blob
    )

    seniority = _detect_seniority(
        structured,
        blob,
    )

    amount = float(
        _MARKET_USD[
            family
        ][
            seniority
        ]
    )

    low = blob.casefold()

    # Premium moderado sólo si el mercado
    # claramente es cross-border/global.
    if any(
        x in low
        for x in (
            "worldwide",
            "global remote",
            "remote worldwide",
            "international remote",
            "remote latam",
            "latam remote",
        )
    ):
        amount *= 1.15

    # El clamp 1k–10k aplica SOLAMENTE
    # cuando no existe rango publicado.
    amount = min(
        10_000,
        max(
            1_000,
            _round_50(amount),
        ),
    )

    return SalaryQuote(
        amount_usd_monthly=int(
            amount
        ),
        source="market",
        negotiable=True,
        reason=(
            f"Mercado {family}/{seniority}; "
            "monto conversable."
        ),
    )


# ============================================================
# PUBLIC API
# ============================================================

def quote_salary(
    decision,
    job_text: str = "",
) -> SalaryQuote:

    published = _published_quote(
        job_text
    )

    if published is not None:
        return published

    return _market_quote(
        decision,
        job_text,
    )


def resolve_salary(
    decision,
    job_text: str = "",
) -> int:

    return quote_salary(
        decision,
        job_text,
    ).amount_usd_monthly


def salary_answer_text(
    decision,
    job_text: str = "",
    language: str = "es",
) -> str:

    quote = quote_salary(
        decision,
        job_text,
    )

    amount = (
        quote.amount_usd_monthly
    )

    if language.lower().startswith(
        "en"
    ):
        if quote.negotiable:
            return (
                f"USD {amount:,}/month, "
                "negotiable depending on scope, "
                "responsibilities and benefits."
            )

        return (
            f"USD {amount:,}/month."
        )

    if quote.negotiable:
        return (
            f"USD {amount:,} mensuales, "
            "conversable según alcance, "
            "responsabilidades y beneficios."
        )

    return (
        f"USD {amount:,} mensuales."
    )
