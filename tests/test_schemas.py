from agentes.jobs.schemas import JobDecision, JobInfo


def base_payload() -> dict:
    return {
        "decision": "APPLY",
        "match_score": 90,
        "job": JobInfo(title="Systems Analyst", company="Example"),
        "cv_id": "09_ES",
        "why": "Strong central-function fit.",
        "interview_defensibility": "High",
    }


def test_unsupported_claim_forces_review() -> None:
    payload = base_payload()
    payload["unsupported_claims"] = ["Claims direct SAP experience"]
    result = JobDecision(**payload)
    assert result.decision == "REVIEW"


def test_missing_cv_for_apply_forces_review() -> None:
    payload = base_payload()
    payload["cv_id"] = None
    result = JobDecision(**payload)
    assert result.decision == "REVIEW"
