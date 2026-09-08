from __future__ import annotations

import re

from agentes.jobs.candidate_truth import (
    lookup_candidate_truth,
)


TECHNOLOGIES = [
    (
        "OpenTelemetry",
        r"\bopentelemetry\b",
        "experience with OpenTelemetry",
    ),
    (
        "Grafana",
        r"\bgrafana\b",
        "experience with Grafana",
    ),
    (
        "Splunk",
        r"\bsplunk\b",
        "experience with Splunk",
    ),
    (
        "Instana",
        r"\binstana\b",
        "experience with Instana",
    ),
    (
        "Zabbix",
        r"\bzabbix\b",
        "experience with Zabbix",
    ),
    (
        "Wazuh",
        r"\bwazuh\b",
        "experience with Wazuh",
    ),
    (
        "Spring Boot",
        r"\bspring\s+boot\b",
        "experience with Spring Boot",
    ),
    (
        "Express",
        r"\bexpress(?:\.js)?\b",
        "experience with Express",
    ),
    (
        "Microsoft Azure",
        r"\b(?:microsoft\s+)?azure\b",
        "experience with Azure",
    ),
    (
        "AWS",
        r"\b(?:aws|amazon\s+web\s+services)\b",
        "experience with AWS",
    ),
    (
        "JavaScript",
        r"\bjavascript\b",
        "experience with JavaScript",
    ),
    (
        "Node.js",
        r"\bnode(?:\.js|js)\b",
        "experience with Node.js",
    ),
    (
        "PostgreSQL",
        r"\bpostgres(?:ql)?\b",
        "experience with PostgreSQL",
    ),
    (
        "microservicios",
        r"\b(?:microservicios|microservices)\b",
        "experience with microservices",
    ),
    (
        "APIs",
        r"\b(?:rest\s+)?apis?\b",
        "experience with APIs",
    ),
    (
        "Kubernetes",
        r"\bkubernetes\b",
        "experience with Kubernetes",
    ),
    (
        "Docker",
        r"\bdocker\b",
        "experience with Docker",
    ),
    (
        "Python",
        r"\bpython\b",
        "experience with Python",
    ),
    (
        "Java",
        r"\bjava\b",
        "experience with Java",
    ),
]


def _norm(text: str) -> str:
    return re.sub(
        r"\s+",
        " ",
        str(text or "").casefold(),
    ).strip()




TECHNICAL_QUESTION_MARKERS = (
    "experiencia",
    "experience",
    "conocimiento",
    "knowledge",
    "manejo",
    "dominio",
    "familiaridad",
    "familiarity",
    "has trabajado",
    "have you worked",
    "has utilizado",
    "have you used",
    "describe tu experiencia",
    "describe your experience",
    # Ownership/action wording used by Get on Board technical forms.
    "implementado",
    "administrado",
    "implemented",
    "administered",
    "herramientas de observabilidad",
    "observability tools",
)


def looks_like_technical_question(text: str) -> bool:
    low = _norm(text)
    return any(marker in low for marker in TECHNICAL_QUESTION_MARKERS)


def _language(question: str) -> str:
    low = _norm(question)

    # Strongest signal.
    if "¿" in str(question):
        return "es"

    spanish = (
        "tienes",
        "tiene",
        "qué",
        "que",
        "cuántos",
        "cuantos",
        "años",
        "conocimiento",
        "experiencia",
        "herramientas",
        "desarrollo",
        "implementado",
        "administrado",
        "trabajando",
        "dispuesto",
        "renta",
        "pretensiones",
        "manejo",
        "nivel",
    )

    english = (
        "what",
        "which",
        "how many",
        "years",
        "experience",
        "knowledge",
        "tools",
        "implemented",
        "managed",
        "working",
        "proficiency",
        "level",
    )

    es_score = sum(
        marker in low
        for marker in spanish
    )

    en_score = sum(
        marker in low
        for marker in english
    )

    return (
        "en"
        if en_score > es_score
        else "es"
    )


def _join_es(items: list[str]) -> str:
    if not items:
        return ""

    if len(items) == 1:
        return items[0]

    if len(items) == 2:
        return (
            items[0]
            + " y "
            + items[1]
        )

    return (
        ", ".join(items[:-1])
        + " y "
        + items[-1]
    )


def _join_en(items: list[str]) -> str:
    if not items:
        return ""

    if len(items) == 1:
        return items[0]

    if len(items) == 2:
        return (
            items[0]
            + " and "
            + items[1]
        )

    return (
        ", ".join(items[:-1])
        + " and "
        + items[-1]
    )


def technologies_in_question(
    question: str,
) -> list[tuple[str, str]]:

    low = _norm(question)

    found = []

    occupied = []

    # Long/specific patterns first so Java does not
    # incorrectly match inside JavaScript.
    for display, pattern, truth_query in TECHNOLOGIES:

        match = re.search(
            pattern,
            low,
            flags=re.I,
        )

        if not match:
            continue

        # Avoid Java inside JavaScript.
        if (
            display == "Java"
            and re.search(
                r"\bjavascript\b",
                low,
            )
        ):
            java_matches = list(
                re.finditer(
                    r"\bjava\b",
                    low,
                )
            )

            if not java_matches:
                continue

        span = match.span()

        if any(
            not (
                span[1] <= old[0]
                or span[0] >= old[1]
            )
            for old in occupied
        ):
            continue

        occupied.append(span)

        found.append(
            (
                display,
                truth_query,
            )
        )

    return found


def build_partial_technical_answer(
    question: str,
) -> str | None:
    """
    Answer composite technology questions without claiming
    every technology in the question.

    Returns None if there is no factual foothold.
    """

    technologies = technologies_in_question(
        question
    )

    if not technologies:
        return None

    confirmed = []
    denied = []
    unknown = []

    for display, truth_query in technologies:

        truth = lookup_candidate_truth(
            truth_query
        )

        if truth.status == "confirmed":
            confirmed.append(display)

        elif truth.status == "denied":
            denied.append(display)

        else:
            unknown.append(display)

    language = _language(
        question
    )

    low = _norm(
        question
    )

    asks_level = (
        "nivel" in low
        or "level" in low
    )

    # --------------------------------------------------------
    # PROVIDER-SPECIFIC CLOUD QUESTION
    #
    # General cloud experience does NOT become Azure/AWS
    # experience. But it is useful contextual evidence.
    # --------------------------------------------------------

    provider_question = any(
        x in [
            name
            for name, _ in technologies
        ]
        for x in (
            "Microsoft Azure",
            "AWS",
        )
    )

    # A provider token inside another product/list is not a cloud question.
    # Examples: "Azure DevOps" in a QA tooling list or agile/Jira question.
    provider_specific_context = (
        provider_question
        and "azure devops" not in low
        and not any(
            marker in low
            for marker in (
                "herramientas de qa",
                "qa tools",
                "selenium",
                "cypress",
                "postman",
                "jira",
                "scrum",
                "product owner",
                "gestion de pruebas",
                "gestión de pruebas",
                "test management",
            )
        )
        and (
            "aws" in low
            or "amazon web services" in low
            or "microsoft azure" in low
            or "infraestructura" in low
            or "infrastructure" in low
            or "entorno cloud" in low
            or "entornos cloud" in low
            or "cloud environment" in low
            or "cloud environments" in low
            or "servicios cloud" in low
            or "cloud services" in low
        )
    )

    if (
        not confirmed
        and provider_specific_context
    ):
        cloud = lookup_candidate_truth(
            "experience with cloud"
        )

        if cloud.status == "confirmed":

            if language == "es":
                return (
                    "Tengo experiencia trabajando en entornos cloud. "
                    "Para Microsoft Azure y AWS no tengo un nivel "
                    "específico respaldado en mi perfil actual, por "
                    "lo que prefiero no atribuirme experiencia que "
                    "no pueda defender técnicamente."
                )

            return (
                "I have experience working with cloud environments. "
                "For Microsoft Azure and AWS, I do not currently have "
                "a specific proficiency level supported by my profile, "
                "so I prefer not to claim experience I cannot defend "
                "technically."
            )

    # --------------------------------------------------------
    # OBSERVABILITY TOOL LIST
    #
    # The candidate has documented operational use of specific
    # observability tools.  Operational use must NOT be upgraded
    # into end-to-end implementation/administration ownership.
    # --------------------------------------------------------

    observability_tools = {
        "Grafana",
        "Splunk",
        "Instana",
        "Zabbix",
        "OpenTelemetry",
        "Wazuh",
    }

    mentioned_names = {
        name
        for name, _ in technologies
    }

    if mentioned_names & observability_tools:

        known_observability = []

        for display in (
            "Grafana",
            "Splunk",
            "Instana",
        ):
            truth = lookup_candidate_truth(
                f"experience with {display}"
            )

            if truth.status == "confirmed":
                known_observability.append(display)

        unknown_mentioned = [
            name
            for name, truth_query in technologies
            if (
                name in observability_tools
                and lookup_candidate_truth(
                    truth_query
                ).status != "confirmed"
            )
        ]

        if known_observability:
            if language == "es":
                text = (
                    "Mi experiencia directa es de uso operativo: "
                    f"he trabajado con {_join_es(known_observability)} "
                    "para monitoreo de producción, observabilidad, "
                    "análisis de logs/trazabilidad y respuesta a "
                    "incidentes."
                )

                if unknown_mentioned:
                    text += (
                        " No tengo evidencia suficiente para afirmar "
                        "implementación o administración directa de "
                        f"{_join_es(unknown_mentioned)}, por lo que no "
                        "atribuyo ese alcance a mi experiencia."
                    )

                return text

            text = (
                "My direct experience is operational: I have worked "
                f"with {_join_en(known_observability)} for production "
                "monitoring, observability, log/trace analysis and "
                "incident response."
            )

            if unknown_mentioned:
                text += (
                    " I do not have sufficient evidence to claim direct "
                    "implementation or administration of "
                    f"{_join_en(unknown_mentioned)}, so I do not attribute "
                    "that scope to my experience."
                )

            return text

        monitoring = lookup_candidate_truth(
            "experience with monitoring"
        )

        logging = lookup_candidate_truth(
            "experience with logging"
        )

        if (
            monitoring.status == "confirmed"
            or logging.status == "confirmed"
        ):

            unknown_tools = [
                name
                for name, _ in technologies
                if name in observability_tools
            ]

            if language == "es":
                return (
                    "Mi experiencia confirmada incluye "
                    "monitoreo de producción, logging y "
                    "análisis de trazabilidad. No tengo "
                    "evidencia suficiente en mi perfil actual "
                    "para afirmar que haya implementado o "
                    "administrado directamente "
                    f"{_join_es(unknown_tools)}, por lo que "
                    "prefiero no sobredeclarar experiencia "
                    "con herramientas específicas."
                )

            return (
                "My confirmed experience includes production "
                "monitoring, logging and trace analysis. "
                "My current profile does not contain enough "
                "evidence to claim direct implementation or "
                "administration of "
                f"{_join_en(unknown_tools)}, so I prefer not "
                "to overstate tool-specific experience."
            )

    # No confirmed technology = do not manufacture an answer.
    if not confirmed:
        return None

    if language == "es":

        confirmed_text = _join_es(
            confirmed
        )

        if asks_level:
            text = (
                f"Cuento con experiencia práctica y defendible "
                f"en {confirmed_text}."
            )
        else:
            text = (
                f"Mi experiencia confirmada incluye "
                f"{confirmed_text}."
            )

        if unknown:
            text += (
                f" Para {_join_es(unknown)} no tengo "
                "un nivel específico respaldado en mi perfil "
                "actual, por lo que prefiero no sobredeclarar "
                "experiencia."
            )

        if denied:
            text += (
                f" No cuento con experiencia directa en "
                f"{_join_es(denied)}."
            )

        return text

    confirmed_text = _join_en(
        confirmed
    )

    if asks_level:
        text = (
            f"I have practical and professionally defensible "
            f"experience with {confirmed_text}."
        )
    else:
        text = (
            f"My confirmed experience includes "
            f"{confirmed_text}."
        )

    if unknown:
        text += (
            f" For {_join_en(unknown)}, I do not currently "
            "have a specific proficiency level supported by "
            "my profile, so I prefer not to overstate my "
            "experience."
        )

    if denied:
        text += (
            f" I do not have direct experience with "
            f"{_join_en(denied)}."
        )

    return text
