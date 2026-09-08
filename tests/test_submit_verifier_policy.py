from pathlib import Path


def _verifier_source() -> str:
    text = Path("scripts/jobs_loop.py").read_text()
    start = text.index("async def verify_submit_externally(")
    end = text.index("\n\nasync def submit_review", start)
    return text[start:end]


def test_verifier_retries_read_only_only():
    fn = _verifier_source()
    assert "attempts: int = 3" in fn
    assert "for attempt in range(1, attempts + 1)" in fn
    assert "await verifier.goto(" in fn
    assert ".click(" not in fn


def test_verifier_detects_late_success_and_preview_draft_text():
    fn = _verifier_source()
    assert "ver tu postulación" in fn
    assert "aún no ha sido enviada" in fn
    assert "aún sin enviar" in fn
    assert 'return "SUBMITTED"' in fn
    assert 'return "DRAFT"' in fn
    assert 'return "UNKNOWN"' in fn


def test_submit_review_still_has_one_final_target_click():
    text = Path("scripts/jobs_loop.py").read_text()
    start = text.index("async def submit_review(")
    end = text.index("\n\nasync def safe_click_next", start)
    fn = text[start:end]
    assert fn.count("await target.click(") == 1
