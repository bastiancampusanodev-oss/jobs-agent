from agentes.jobs.custom_known_facts import (
    financial_sector_custom_answer,
    project_stack_custom_answer,
)


def field(label):
    return {
        "field_key": "q",
        "kind": "text",
        "label": label,
        "required": True,
        "options": [],
    }


def test_financial_sector_uses_bancoestado():

    answer = financial_sector_custom_answer(
        field(
            "¿Posees experiencia en instituciones financieras "
            "como Banca, Compañías de Seguros, Corredoras de "
            "Bolsa? Indica cuáles:"
        )
    )

    assert answer is not None

    assert (
        "BancoEstado"
        in answer.text
    )

    assert (
        "sector financiero"
        in answer.text
    )

    assert (
        "monitoreo"
        in answer.text
    )


def test_financial_does_not_claim_insurance_or_brokerage():

    answer = financial_sector_custom_answer(
        field(
            "¿Posees experiencia en instituciones financieras?"
        )
    )

    assert answer is not None

    assert (
        "No atribuyo"
        in answer.text
    )

    assert (
        "compañías de seguros"
        in answer.text
    )

    assert (
        "corredoras de bolsa"
        in answer.text
    )


def test_comex_is_left_to_existing_specialized_policy():

    answer = financial_sector_custom_answer(
        field(
            "¿Tienes experiencia en instituciones financieras "
            "trabajando específicamente con COMEX?"
        )
    )

    assert answer is None


def test_java_spring_angular_narrative():

    answer = project_stack_custom_answer(
        field(
            "Cuéntenos sobre un proyecto donde haya trabajado "
            "con Java, Spring Boot y Angular, detallando su rol, "
            "los módulos que desarrolló y las tecnologías "
            "utilizadas."
        )
    )

    assert answer is not None

    text = answer.text

    assert "Java" in text
    assert "Spring Boot" in text
    assert "Angular" in text
    assert "APIs REST" in text
    assert "Gradle" in text
    assert "pruebas unitarias" in text

    assert (
        "servicios y APIs"
        in text
    )

    assert (
        "no atribuyo nombres"
        in text
    )


def test_angularjs_is_not_upgraded_from_angular():

    answer = project_stack_custom_answer(
        field(
            "Cuéntenos sobre un proyecto donde haya trabajado "
            "con Java, Spring Boot y AngularJS."
        )
    )

    assert answer is not None

    assert (
        "AngularJS 1.x"
        in answer.text
    )

    assert (
        "No atribuyo experiencia específica"
        in answer.text
    )


def test_unrelated_project_not_hijacked():

    answer = project_stack_custom_answer(
        field(
            "Cuéntanos sobre un proyecto con Salesforce."
        )
    )

    assert answer is None
