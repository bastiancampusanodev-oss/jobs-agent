import asyncio
from types import SimpleNamespace

from agentes.jobs.application_runner import (
    _deterministic_custom_answer,
)
from agentes.jobs.custom_known_facts import (
    english_level_custom_answer,
    professional_summary_custom_answer,
    residence_country_custom_answer,
    technology_duration_custom_answer,
)
from agentes.jobs.gob_stage import resolve_gob_step


class FakeLocator:
    def __init__(self, *, count=0, value=""):
        self._count = count
        self._value = value

    @property
    def first(self):
        return self

    async def count(self):
        return self._count

    async def input_value(self):
        return self._value

    async def get_attribute(self, name):
        return self._value if name == "value" else None


class FakePage:
    def __init__(self, url, hidden=None):
        self.url = url
        self.hidden = hidden

    def locator(self, selector):
        if selector == "input[name='job_application[step]']":
            if self.hidden is None:
                return FakeLocator(count=0)
            return FakeLocator(
                count=1,
                value=self.hidden,
            )
        return FakeLocator(count=0)


def test_questions_query_is_internal_custom():
    page = FakePage(
        "https://www.getonbrd.com/applications/abc/"
        "edit?step=questions"
    )
    assert asyncio.run(
        resolve_gob_step(page)
    ) == "custom"


def test_questions_hidden_is_internal_custom():
    page = FakePage(
        "https://www.getonbrd.com/applications/abc/edit",
        hidden="questions",
    )
    assert asyncio.run(
        resolve_gob_step(page)
    ) == "custom"


def test_residence_radio_selects_si():
    field = {
        "field_key": "country",
        "kind": "radio",
        "label": (
            "¿Resides en uno de los siguientes países: "
            "Chile, Colombia, Perú o México?"
        ),
        "required": True,
        "options": [
            {"label": "SI", "value": "yes"},
            {"label": "NO", "value": "no"},
        ],
    }
    answer = residence_country_custom_answer(field)
    assert answer is not None
    assert answer.selected == ["SI"]


def test_residence_country_select_chooses_chile():
    field = {
        "field_key": "country",
        "kind": "select",
        "label": "País de residencia: Chile u otro país",
        "required": True,
        "options": [
            {"label": "Chile", "value": "cl"},
            {"label": "México", "value": "mx"},
        ],
    }
    answer = residence_country_custom_answer(field)
    assert answer is not None
    assert answer.selected == ["Chile"]


def test_residence_boolean_checkbox():
    field = {
        "field_key": "residence",
        "kind": "checkbox",
        "label": "Confirmo que resido en Chile",
        "required": True,
        "options": [],
    }
    answer = residence_country_custom_answer(field)
    assert answer is not None
    assert answer.checked is True

    integrated = _deterministic_custom_answer(
        field,
        SimpleNamespace(),
        "",
    )
    assert integrated is not None
    assert integrated.checked is True
    assert integrated.requires_human is False


def test_english_oral_written_is_deterministic():
    field = {
        "field_key": "english",
        "kind": "text",
        "label": "¿Cuál es tu nivel de inglés oral y escrito?",
        "required": True,
        "options": [],
    }
    answer = english_level_custom_answer(field)
    assert answer is not None
    assert "Intermedio-avanzado" in answer.text


def test_professional_summary_is_nonempty():
    field = {
        "field_key": "professional",
        "kind": "text",
        "label": (
            "Cuéntanos brevemente de tu experiencia profesional "
            "(cuántos años llevas trabajando en el área, "
            "qué tecnologías has utilizado, etc.)"
        ),
        "required": True,
        "options": [],
    }
    answer = professional_summary_custom_answer(field)
    assert answer is not None
    assert "más de 5 años" in answer.text
    assert "Python" in answer.text


def test_node_python_angular_does_not_invent_angular_years():
    field = {
        "field_key": "years",
        "kind": "text",
        "label": (
            "¿Cuántos años de experiencia profesional tienes "
            "desarrollando con Node, Python y Angular?"
        ),
        "required": True,
        "options": [],
    }
    answer = technology_duration_custom_answer(field)
    assert answer is None


def test_aws_service_duration_does_not_invent_years():
    field = {
        "field_key": "aws",
        "kind": "text",
        "label": (
            "¿Cuánto tiempo de experiencia tienes trabajando "
            "con servicios de AWS como Lambda, DynamoDB, "
            "API Gateway o CloudFront?"
        ),
        "required": True,
        "options": [],
    }
    answer = technology_duration_custom_answer(field)
    assert answer is None
