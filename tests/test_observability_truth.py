from agentes.jobs.candidate_truth import lookup_candidate_truth
from agentes.jobs.technical_answer_engine import (
    build_partial_technical_answer,
    looks_like_technical_question,
)


def test_named_observability_tools_are_supported_but_not_upgraded():
    assert lookup_candidate_truth("experience with Grafana").status == "confirmed"
    assert lookup_candidate_truth("experience with Splunk").status == "confirmed"
    assert lookup_candidate_truth("experience with Instana").status == "confirmed"
    assert lookup_candidate_truth("experience with Zabbix").status == "unknown"
    assert lookup_candidate_truth("experience with OpenTelemetry").status == "unknown"
    assert lookup_candidate_truth("experience with Wazuh").status == "unknown"


def test_observability_composite_answer_is_specific_and_qualified():
    question = (
        "¿Qué herramientas de observabilidad has implementado y administrado? "
        "(Grafana, Zabbix, OpenTelemetry, Wazuh u otras)"
    )

    answer = build_partial_technical_answer(question)

    assert answer is not None
    assert "Grafana" in answer
    assert "Splunk" in answer
    assert "Instana" in answer
    assert "OpenTelemetry" in answer
    assert "Zabbix" in answer
    assert "Wazuh" in answer
    assert "uso operativo" in answer
    assert "No tengo evidencia suficiente" in answer
    assert "implementación o administración directa" in answer


def test_sre_observability_wording_is_routed_as_technical():
    question = (
        "¿Qué herramientas de observabilidad has implementado y administrado? "
        "(Grafana, Zabbix, OpenTelemetry, Wazuh u otras)"
    )
    assert looks_like_technical_question(question) is True
    assert build_partial_technical_answer(question) is not None
