from agentes.jobs.custom_known_facts import qa_custom_answer
from agentes.jobs.evidence_answerer import answer_from_evidence
from agentes.jobs.technical_answer_engine import build_partial_technical_answer


JOB = "QA Junior Funcional y Automatización. Testing, pruebas funcionales y automatización de pruebas."


def _field(label: str):
    return {
        "field_key": "q",
        "kind": "text",
        "label": label,
        "required": True,
        "options": [],
    }


def test_qa_tool_list_does_not_turn_azure_devops_into_cloud_answer():
    q = (
        "¿Qué herramientas de QA has utilizado durante tu experiencia laboral? "
        "Indica cuáles has utilizado (Selenium, Playwright, Cypress, UiPath, "
        "Postman, Jira, Azure DevOps, Confluence, TestRail o Xray?"
    )
    assert build_partial_technical_answer(q) is None
    answer = qa_custom_answer(_field(q), JOB)
    assert answer is not None
    assert "No he desempeñado un rol formal de QA" in answer.text
    assert "entornos cloud" not in answer.text


def test_agile_azure_devops_question_is_not_cloud_answer():
    q = (
        "¿Cuál es tu experiencia trabajando con metodologías ágiles (Scrum), "
        "herramientas como Jira o Azure DevOps y colaborando con desarrolladores, "
        "analistas y Product Owner?"
    )
    assert build_partial_technical_answer(q) is None
    answer = qa_custom_answer(_field(q), JOB)
    assert answer is not None
    assert "No tengo experiencia específica" in answer.text
    assert "Jira" in answer.text
    assert "Azure DevOps" in answer.text


def test_composite_qa_tools_answer_is_not_reduced_to_apis():
    q = (
        "¿Qué herramientas de automatización, gestión de pruebas, bases de datos "
        "y validación de APIs has utilizado?"
    )
    answer = qa_custom_answer(_field(q), JOB)
    assert answer is not None
    assert "SQL" in answer.text
    assert "APIs REST" in answer.text
    assert "gestión de pruebas" in answer.text


def test_formal_qa_years_are_zero_not_adjacent_engineering_years():
    q = "¿Cuántos años de experiencia tienes desempeñándote como Analista QA (manual y automatizado)?"
    answer = qa_custom_answer(_field(q), JOB)
    assert answer is not None
    assert answer.text.startswith("0 años de experiencia formal")
    assert "no la presento como experiencia QA directa" in answer.text


def test_weak_tag_cloud_does_not_answer_multi_part_qa_years_question():
    q = "¿Cuántos años de experiencia tienes desempeñándote como Analista QA (manual y automatizado)?"
    knowledge = "Python Backend Software Engineering DevOps Platform Engineering Systems Engineering QA Automation"
    assert answer_from_evidence(q, knowledge) is None
