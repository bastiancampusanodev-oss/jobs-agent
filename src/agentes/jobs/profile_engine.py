from __future__ import annotations

import re


MIN_PROFILE_CHARS = 550


def _norm(text: str) -> str:
    return re.sub(
        r"\s+",
        " ",
        str(text or "").casefold(),
    ).strip()


def detect_language(job_text: str) -> str:
    # Backwards-compatible public entry point. All application artifacts
    # now share the same deterministic language policy.
    from agentes.jobs.job_language_policy import detect_job_language

    return detect_job_language(job_text)


def detect_family(job_text: str) -> str:
    """
    Detect role family.

    Strong role/title signals have priority over secondary
    technologies mentioned in requirements.
    """

    text = _norm(
        job_text[:10000]
    )

    # First ~300 chars normally contain the job title/header.
    head = text[:350]

    # --------------------------------------------------------
    # TITLE / HEADER — STRONG SIGNALS
    # --------------------------------------------------------

    if any(
        x in head
        for x in (
            "backend",
            "spring boot",
            "java developer",
            "python developer",
            "desarrollador backend",
            "backend developer",
            "backend engineer",
            "integration developer",
            "desarrollador de integraciones",
        )
    ):
        return "backend"

    if any(
        x in head
        for x in (
            "data engineer",
            "ingeniero de datos",
            "data scientist",
            "cientifico de datos",
            "científico de datos",
        )
    ):
        return "data"

    if any(
        x in head
        for x in (
            "devops",
            "devsecops",
            "site reliability",
            "sre",
            "platform engineer",
            "cloud engineer",
            "ingeniero de plataformas",
        )
    ):
        return "devops"

    if any(
        x in head
        for x in (
            "ai engineer",
            "ml engineer",
            "machine learning engineer",
            "ingeniero de inteligencia artificial",
            "ingeniero ia",
        )
    ):
        return "ai"

    # --------------------------------------------------------
    # FULL DESCRIPTION — SECONDARY SIGNALS
    # --------------------------------------------------------

    if any(
        x in text
        for x in (
            "artificial intelligence",
            "inteligencia artificial",
            "machine learning",
            "llm",
            "rag",
            "generative ai",
            "genai",
            "agentic",
        )
    ):
        return "ai"

    if any(
        x in text
        for x in (
            "data engineer",
            "ingeniero de datos",
            "data science",
            "pyspark",
            "spark",
            "etl",
            "analytics",
            "big data",
        )
    ):
        return "data"

    # Backend BEFORE DevOps here.
    if any(
        x in text
        for x in (
            "backend",
            "spring boot",
            "java",
            "api",
            "apis",
            "integration",
            "integracion",
            "integración",
            "software engineer",
            "desarrollador",
            "ingeniero de software",
        )
    ):
        return "backend"

    if any(
        x in text
        for x in (
            "devops",
            "devsecops",
            "sre",
            "site reliability",
            "platform engineer",
            "cloud engineer",
            "kubernetes",
            "observability",
            "observabilidad",
            "infraestructura",
        )
    ):
        return "devops"

    return "general"


PROFILES_ES = {
    "ai": (
        "Mi experiencia combina desarrollo de software, inteligencia artificial "
        "aplicada y automatización de procesos técnicos. Trabajo con Python, "
        "integración de APIs de LLM, RAG y LangChain, y actualmente desarrollo "
        "y opero un agente autónomo end-to-end en Python que integra razonamiento "
        "mediante LLMs, outputs estructurados, automatización de navegador con "
        "Playwright, estado persistente, recuperación ante fallos y guardrails "
        "antes de acciones irreversibles. También tengo experiencia en desarrollo "
        "de producto con IA aplicada y Kotlin/Android en AirTap. Complemento esta "
        "experiencia con docencia técnica en USACH, donde he trabajado contenidos "
        "de IA aplicada, APIs de IA, LangChain, RAG, datos, sistemas distribuidos "
        "y blockchain. Mi enfoque combina desarrollo práctico, análisis técnico, "
        "automatización y capacidad para llevar soluciones desde la idea hasta un "
        "workflow funcional y verificable."
    ),

    "data": (
        "Tengo experiencia práctica con Python, SQL, PySpark y procesamiento de "
        "datos, junto con una base sólida en desarrollo de software y sistemas. "
        "Como docente / relator TI en la Universidad de Santiago de Chile he "
        "trabajado contenidos de data engineering, PySpark y sistemas distribuidos, "
        "incluyendo transformación de datos, Structured Streaming y conceptos de "
        "procesamiento distribuido. Mi experiencia previa también incluye desarrollo "
        "con Python, Java, APIs REST y SQL, además de operación tecnológica en "
        "BancoEstado, donde trabajé con monitoreo, análisis de logs, trazabilidad, "
        "respuesta a incidentes y continuidad operacional. Esta combinación me "
        "permite abordar problemas de datos tanto desde la programación como desde "
        "la operación, calidad, observabilidad y comprensión del comportamiento de "
        "los sistemas en producción."
    ),

    "devops": (
        "Tengo experiencia en operación tecnológica, administración de sistemas "
        "y desarrollo de software, trabajando con Linux, Docker, Kubernetes, "
        "monitoreo, logging, microservicios y respuesta a incidentes. En BancoEstado "
        "me desempeñé como Analista de Producción / Tecnología, participando en "
        "monitoreo de producción, análisis de logs y trazabilidad, continuidad "
        "operacional y resolución de incidentes en entornos con Kubernetes, cloud "
        "y microservicios. Anteriormente trabajé como Administrador de Sistemas en "
        "ObbySpa, con responsabilidades sobre servidores, usuarios y accesos, redes, "
        "backups, documentación y resolución de incidentes. Además, mi experiencia "
        "como desarrollador con Python, Java, SQL, APIs REST y Git me permite "
        "entender los sistemas tanto desde la infraestructura y operación como "
        "desde el código que se ejecuta sobre ellos."
    ),

    "backend": (
        "Tengo experiencia en desarrollo de software con Python, Java, SQL y APIs "
        "REST, además de Git, Linux, microservicios y automatización. Trabajé como "
        "Analista Programador / Desarrollador en Willard Solutions & Metacontrol, "
        "donde utilicé Java, Python, APIs REST, SQL y documentación técnica. También "
        "cuento con experiencia en operación tecnológica en BancoEstado, trabajando "
        "con monitoreo, análisis de logs, trazabilidad, microservicios, Linux y "
        "respuesta a incidentes, lo que me entrega una visión práctica del ciclo "
        "completo de una aplicación. Actualmente desarrollo además un agente "
        "autónomo end-to-end en Python que integra RAG, outputs estructurados, "
        "Playwright, persistencia de estado, recuperación ante fallos y guardrails. "
        "Esta combinación me permite trabajar en backend considerando no sólo el "
        "desarrollo, sino también integración, mantenibilidad y operación."
    ),

    "general": (
        "Mi experiencia profesional combina desarrollo de software, análisis y "
        "operación de sistemas, soporte tecnológico, automatización y docencia TI. "
        "He trabajado con Python, Java, Kotlin/Android, SQL, APIs REST, Git, Linux, "
        "Docker, Kubernetes, microservicios y tecnologías de inteligencia artificial "
        "y datos. En BancoEstado me desempeñé en producción tecnológica, trabajando "
        "con monitoreo, logs, trazabilidad, respuesta a incidentes y continuidad "
        "operacional. También tengo experiencia previa como desarrollador y como "
        "administrador de sistemas. Actualmente complemento esta trayectoria con "
        "docencia técnica en USACH y con proyectos propios de IA aplicada y "
        "automatización, incluyendo un agente autónomo end-to-end en Python. Mi "
        "perfil combina capacidad de desarrollo, comprensión operacional, análisis "
        "técnico y aprendizaje continuo para adaptarme a distintos desafíos TI."
    ),
}


PROFILES_EN = {
    "ai": (
        "My experience combines software development, applied artificial intelligence "
        "and technical workflow automation. I work with Python, LLM API integration, "
        "RAG and LangChain, and I currently build and operate an end-to-end autonomous "
        "agent in Python combining LLM reasoning, structured outputs, Playwright "
        "browser automation, persistent state, failure recovery and safety guardrails "
        "before irreversible actions. I also have experience in applied AI product "
        "development and Kotlin/Android through AirTap. In parallel, I teach technical "
        "topics at Universidad de Santiago de Chile, including applied AI, AI APIs, "
        "LangChain, RAG, data engineering, distributed systems and blockchain. My "
        "background therefore combines hands-on development, technical analysis, "
        "automation and the ability to turn an idea into a functional and verifiable "
        "real-world workflow."
    ),

    "data": (
        "I have hands-on experience with Python, SQL, PySpark and data processing, "
        "combined with a solid background in software development and systems. As an "
        "IT instructor at Universidad de Santiago de Chile, I have worked with data "
        "engineering, PySpark and distributed systems topics, including data "
        "transformation, Structured Streaming and distributed processing concepts. "
        "My previous experience also includes development with Python, Java, REST "
        "APIs and SQL, as well as technology operations at BancoEstado, where I "
        "worked with production monitoring, log analysis, traceability, incident "
        "response and operational continuity. This combination allows me to approach "
        "data problems from programming, operations, observability and system "
        "behavior perspectives."
    ),

    "devops": (
        "My background combines technology operations, systems administration and "
        "software development. I have worked with Linux, Docker, Kubernetes, "
        "monitoring, logging, microservices and incident response. At BancoEstado I "
        "worked as a Production / Technology Analyst, dealing with production "
        "monitoring, log analysis and traceability, operational continuity and "
        "incident response in environments involving Kubernetes, cloud technologies "
        "and microservices. Previously, as a Systems Administrator at ObbySpa, I "
        "worked with servers, users and access management, networks, backups, "
        "documentation and incident resolution. My development experience with "
        "Python, Java, SQL, REST APIs and Git also helps me understand systems from "
        "both the infrastructure and application perspectives."
    ),

    "backend": (
        "I have software development experience with Python, Java, SQL and REST APIs, "
        "as well as Git, Linux, microservices and automation. I worked as a Programmer "
        "Analyst / Developer at Willard Solutions & Metacontrol, using Java, Python, "
        "REST APIs, SQL and technical documentation. I also have technology operations "
        "experience at BancoEstado involving production monitoring, log analysis, "
        "traceability, microservices, Linux and incident response, which gives me a "
        "practical view of the complete application lifecycle. I currently build an "
        "end-to-end autonomous agent in Python that integrates RAG, structured outputs, "
        "Playwright automation, persistent state, failure recovery and safety "
        "guardrails. This combination allows me to approach backend work with "
        "development, integration, maintainability and production operation in mind."
    ),

    "general": (
        "My professional background combines software development, systems analysis "
        "and operations, technical support, automation and IT teaching. I have worked "
        "with Python, Java, Kotlin/Android, SQL, REST APIs, Git, Linux, Docker, "
        "Kubernetes, microservices, applied AI and data technologies. At BancoEstado "
        "I worked in production technology with monitoring, logs, traceability, "
        "incident response and operational continuity. My previous experience also "
        "includes software development and systems administration. I currently "
        "complement this background through technical teaching at Universidad de "
        "Santiago de Chile and hands-on applied AI and automation projects, including "
        "an end-to-end autonomous agent in Python. My profile combines development, "
        "operations, technical analysis and continuous learning."
    ),
}


ACADEMIC_ES = (
    "Actualmente curso Ingeniería en Ejecución de Software en la Universidad "
    "Técnica Federico Santa María (UTFSM), encontrándome en la etapa final de "
    "la carrera. Previamente completé la formación de Analista Programador en "
    "CFT ProAndes. Mi formación académica se complementa con experiencia práctica "
    "en desarrollo de software, sistemas y tecnologías de información. Durante "
    "2026 me desempeño además como docente / relator TI en la Universidad de "
    "Santiago de Chile (USACH), donde he impartido contenidos relacionados con "
    "inteligencia artificial aplicada, APIs de IA, LangChain y RAG, blockchain, "
    "data engineering, PySpark y sistemas distribuidos. Esta combinación entre "
    "estudios formales, práctica profesional y docencia técnica me ha permitido "
    "fortalecer tanto fundamentos de ingeniería de software como la capacidad de "
    "aplicar y explicar tecnologías en contextos reales."
)


ACADEMIC_EN = (
    "I am currently completing Ingeniería en Ejecución de Software at Universidad "
    "Técnica Federico Santa María (UTFSM), where I am in the final stage of the "
    "degree. I previously completed the Analista Programador program at CFT "
    "ProAndes. My academic background is complemented by hands-on experience in "
    "software development, systems and information technology. During 2026 I also "
    "work as an IT instructor at Universidad de Santiago de Chile (USACH), teaching "
    "topics related to applied artificial intelligence, AI APIs, LangChain and RAG, "
    "blockchain, data engineering, PySpark and distributed systems. This combination "
    "of formal education, professional practice and technical teaching has helped me "
    "strengthen both software engineering foundations and my ability to apply and "
    "explain technology in practical contexts."
)


def _validate_profile(
    professional: str,
    academic: str,
) -> None:

    for name, value in (
        ("professional", professional),
        ("academic", academic),
    ):
        if len(value) < MIN_PROFILE_CHARS:
            raise RuntimeError(
                f"PROFILE {name} demasiado corto: "
                f"{len(value)} < {MIN_PROFILE_CHARS}"
            )


def build_profile(job_text: str) -> dict:
    """
    v0.6.11.6 PROFILE POLICY ALIGNMENT.

    PROFILE must use the same deterministic role family and
    canonical language policy as the analyzer/CV pipeline.
    """

    from agentes.jobs.analyzer import (
        _best_family,
    )

    from agentes.jobs.job_language_policy import (
        detect_job_language,
    )

    blob = str(
        job_text
        or ""
    ).casefold()

    analyzer_family, _ = (
        _best_family(
            blob
        )
    )

    family_map = {
        "software": "backend",
        "python": "backend",
        "data": "data",
        "ops": "devops",
        "ai": "ai",
    }

    family = family_map.get(
        analyzer_family,
        "backend",
    )

    language = detect_job_language(
        job_text
    )

    if language == "en":
        professional = PROFILES_EN[family]
        academic = ACADEMIC_EN
    else:
        professional = PROFILES_ES[family]
        academic = ACADEMIC_ES

    _validate_profile(
        professional,
        academic,
    )

    return {
        "language": language,
        "professional": professional,
        "academic": academic,
        "family": family,
        "professional_chars": len(professional),
        "academic_chars": len(academic),
    }
