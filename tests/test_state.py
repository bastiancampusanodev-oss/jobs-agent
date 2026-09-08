from agentes.state import StateStore


def test_state_saves_and_deduplicates_url(tmp_path) -> None:
    store = StateStore(tmp_path / "agents.db")
    payload = {
        "decision": "SKIP",
        "match_score": 40,
        "cv_id": None,
        "job": {"title": "Role", "company": "Co", "url": "https://example.com/1"},
    }
    store.save_job_result(payload, source="test")
    assert store.has_job_url("https://example.com/1")
    assert store.recent(1)[0]["decision"] == "SKIP"
