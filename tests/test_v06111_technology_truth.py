from types import SimpleNamespace

from agentes.jobs.application_runner import (
    _checkbox_answer,
    _checkbox_required,
    _technology_registry_supports,
)


def field(
    label,
    options,
    *,
    required=False,
    required_hint=True,
):
    return {
        "field_key": "q",
        "kind": "checkbox",
        "name": "q",
        "label": label,
        "required": required,
        "required_hint": required_hint,
        "options": [
            {
                "id": f"q_{i}",
                "value": str(i),
                "label": option,
            }
            for i, option
            in enumerate(
                options,
                1,
            )
        ],
    }


def test_required_hint_makes_group_required():

    assert _checkbox_required({
        "required": False,
        "required_hint": True,
        "label": "Pregunta sin asterisco recuperado",
    })


def test_improving_api_frontend_exact_choices():

    f = field(
        "¿Qué experiencias prácticas tienes desarrollando "
        "APIs y componentes frontend para aplicaciones escalables?",
        [
            (
                "Desarrollé interfaces responsivas en Angular "
                "aprovechando arquitectura basada en componentes"
            ),
            (
                "Gestioné estados complejos y acciones asíncronas "
                "en frontend usando RxJS en proyectos reales"
            ),
            (
                "Diseñé e implementé APIs RESTful con SpringBoot "
                "para servicios consumidos por aplicaciones SPA"
            ),
        ],
    )

    answer = _checkbox_answer(
        f,
        SimpleNamespace(),
        "",
    )

    assert answer.requires_human is False

    assert answer.selected == [
        (
            "Desarrollé interfaces responsivas en Angular "
            "aprovechando arquitectura basada en componentes"
        ),
        (
            "Diseñé e implementé APIs RESTful con SpringBoot "
            "para servicios consumidos por aplicaciones SPA"
        ),
    ]


def test_improving_quality_exact_choices():

    f = field(
        "¿Cómo has asegurado la calidad y mantenibilidad "
        "del código en proyectos fullstack?",
        [
            (
                "Participé activamente en revisiones de código "
                "colaborativas y documentación técnica"
            ),
            (
                "Utilicé Gradle y buenas prácticas para la "
                "automatización de builds y control de dependencias"
            ),
            (
                "Implementé pruebas unitarias y de integración "
                "para backend y frontend asegurando cobertura clave"
            ),
        ],
    )

    answer = _checkbox_answer(
        f,
        SimpleNamespace(),
        "",
    )

    assert answer.requires_human is False

    assert answer.selected == [
        option["label"]
        for option in f["options"]
    ]


def test_javascript_does_not_upgrade_to_rxjs():

    assert not _technology_registry_supports(
        "Gestioné estados complejos y acciones asíncronas "
        "usando RxJS en proyectos reales"
    )


def test_simple_go_is_confirmed():

    assert _technology_registry_supports(
        "He trabajado con Go"
    )


def test_simple_opensearch_is_confirmed():

    assert _technology_registry_supports(
        "Experiencia con OpenSearch"
    )


def test_simple_gcp_is_confirmed():

    assert _technology_registry_supports(
        "He utilizado Google Cloud Platform"
    )


def test_aws_keyword_does_not_claim_enterprise_admin():

    assert not _technology_registry_supports(
        "Administré infraestructura AWS enterprise "
        "a gran escala durante cinco años"
    )


def test_oracle_cloud_does_not_mean_oracle_database():

    assert not _technology_registry_supports(
        "Administré Oracle Database en producción"
    )
