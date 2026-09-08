from datetime import datetime, timedelta, timezone

from scripts import jobs_loop


def _insert(url, status, age_hours):
    updated = (
        datetime.now(timezone.utc)
        - timedelta(hours=age_hours)
    ).isoformat()

    with jobs_loop.db() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO job_loop
            (url, status, updated_at)
            VALUES (?, ?, ?)
            """,
            (url, status, updated),
        )
        conn.commit()


def test_review_and_human_review_reenter_only_dry_run(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs_loop, "DB", tmp_path / "job_loop.db")
    monkeypatch.setenv("REVIEW_RETRY_SECONDS", "3600")
    monkeypatch.setenv("HUMAN_REVIEW_RETRY_SECONDS", "3600")
    monkeypatch.setenv("JOB_ERROR_RETRY_SECONDS", "900")
    monkeypatch.setenv("ANALYZED_RETRY_SECONDS", "900")
    monkeypatch.setenv("CTA_MISSING_RETRY_SECONDS", "3600")

    _insert("https://example/review-old", "REVIEW", 2)
    _insert("https://example/review-new", "REVIEW", 0.1)
    _insert("https://example/human-old", "HUMAN_REVIEW", 2)
    _insert("https://example/human-new", "HUMAN_REVIEW", 0.1)
    _insert("https://example/error-old", "ERROR", 1)
    _insert("https://example/analyzed-old", "ANALYZED", 1)
    _insert("https://example/cta-old", "APPLICATION_CTA_MISSING", 2)
    _insert("https://example/cta-new", "APPLICATION_CTA_MISSING", 0.1)

    dry = jobs_loop.queued_retry_urls(limit=20, submit=False)

    assert "https://example/analyzed-old" in dry
    assert "https://example/cta-old" in dry
    assert "https://example/cta-new" not in dry
    assert "https://example/review-old" in dry
    assert "https://example/human-old" in dry
    assert "https://example/error-old" in dry
    assert "https://example/review-new" not in dry
    assert "https://example/human-new" not in dry
    assert jobs_loop.queued_retry_urls(limit=20, submit=True) == []


def test_review_and_human_are_not_terminal_in_reversible_lane():
    review = {"status": "REVIEW"}
    human = {"status": "HUMAN_REVIEW"}
    assert jobs_loop.should_skip_record(review, submit=False) is False
    assert jobs_loop.should_skip_record(human, submit=False) is False
    assert jobs_loop.should_skip_record(review, submit=True) is True
    assert jobs_loop.should_skip_record(human, submit=True) is True
