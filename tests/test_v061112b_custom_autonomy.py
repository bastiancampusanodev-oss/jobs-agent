from agentes.jobs.custom_autonomy_policy import (
    autonomous_answer,
)


def field_text(label):
    return {
        "field_key": "q",
        "kind": "text",
        "label": label,
        "options": [],
    }


def test_years_never_none():
    out = autonomous_answer(
        field_text(
            "¿Cuántos años de experiencia tienes con Appium?"
        )
    )

    assert out is not None
    assert out.text == "0"


def test_open_question_never_none():
    out = autonomous_answer(
        field_text(
            "Describe tu experiencia con SAP Datasphere"
        )
    )

    assert out is not None
    assert out.text


def test_unknown_yes_no_becomes_no():
    out = autonomous_answer(
        {
            "field_key": "q",
            "kind": "radio",
            "label": (
                "¿Has trabajado formalmente "
                "como Product Owner?"
            ),
            "options": [
                {
                    "label": "Sí",
                    "value": "yes",
                },
                {
                    "label": "No",
                    "value": "no",
                },
            ],
        }
    )

    assert out is not None
    assert out.selected == ["No"]


def test_current_salary_does_not_invent_history():
    out = autonomous_answer(
        field_text(
            "¿Cuál es tu salario actual?"
        ),
        salary_usd=2500,
    )

    assert out is not None
    assert out.text
    assert "Prefiero" in out.text


def test_checkbox_unknown_is_false():
    out = autonomous_answer(
        {
            "field_key": "q",
            "kind": "checkbox",
            "label": (
                "Tengo experiencia profesional con Appium"
            ),
            "options": [],
        }
    )

    assert out is not None
    assert out.checked is False
