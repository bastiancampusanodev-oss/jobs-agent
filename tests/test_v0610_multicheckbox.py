from types import SimpleNamespace

from agentes.jobs.application_runner import (
    _checkbox_option_supported,
)


def truth(
    *,
    status="confirmed",
    concepts=(),
    evidence=(),
):
    return SimpleNamespace(
        status=status,
        concepts=list(concepts),
        evidence=[
            SimpleNamespace(
                text=value,
                organization="",
                role="",
            )
            for value in evidence
        ],
    )


CORPUS = """
skills:
  - Python
  - Kubernetes
  - Docker
  - automation
experience:
  - Production monitoring
  - Incident response
  - Log analysis and traceability
  - Operational continuity
"""


def test_kubernetes_interaction_is_supported():
    q = (
        "Has configurado o interactuado con clusters de "
        "Kubernetes para desplegar o monitorear aplicaciones"
    )

    assert _checkbox_option_supported(
        q,
        truth(
            concepts=["Kubernetes"],
            evidence=["Kubernetes"],
        ),
        CORPUS.casefold(),
    )


def test_docker_skill_does_not_invent_image_creation():
    q = (
        "Has creado o modificado imágenes de contenedores Docker "
        "para entornos de desarrollo o producción"
    )

    assert not _checkbox_option_supported(
        q,
        truth(
            concepts=["Docker"],
            evidence=["Docker"],
        ),
        CORPUS.casefold(),
    )


def test_incident_documentation_from_production_truth():
    q = (
        "Has intervenido en la identificación y documentación "
        "de incidencias técnicas en sistemas en producción"
    )

    assert _checkbox_option_supported(
        q,
        truth(
            concepts=["incident response"],
            evidence=[
                "Incident response",
                "Log analysis and traceability",
            ],
        ),
        CORPUS.casefold(),
    )


def test_python_automation_scripts_supported():
    q = (
        "Has desarrollado o editado scripts en Bash y/o Python "
        "para automatizar tareas rutinarias en ambientes de TI"
    )

    assert _checkbox_option_supported(
        q,
        truth(
            concepts=["Python"],
            evidence=["Python automation"],
        ),
        CORPUS.casefold(),
    )


def test_unknown_option_not_selected():
    q = (
        "Has administrado OpenShift productivo durante cinco años"
    )

    assert not _checkbox_option_supported(
        q,
        truth(
            status="unknown",
        ),
        CORPUS.casefold(),
    )


def test_outcome_is_not_invented():
    q = (
        "Has implementado soluciones que redujeron tiempos "
        "o errores en 80%"
    )

    assert not _checkbox_option_supported(
        q,
        truth(
            concepts=["Python"],
            evidence=["Python automation"],
        ),
        CORPUS.casefold(),
    )
