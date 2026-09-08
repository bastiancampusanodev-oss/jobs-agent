from agentes.jobs.analyzer import (
    GrayDecision,
    _resolve_gray_advisory,
)


def gray(
    decision,
    score,
):
    return GrayDecision(
        decision=decision,
        match_score=score,
    )


def test_apply_zero_cannot_destroy_deterministic_67():

    decision, score, reason = (
        _resolve_gray_advisory(
            deterministic_score=67,
            gray=gray(
                "APPLY",
                0,
            ),
        )
    )

    assert decision == "APPLY"
    assert score == 67
    assert "llm_score=0" in reason


def test_apply_zero_cannot_destroy_deterministic_73():

    decision, score, reason = (
        _resolve_gray_advisory(
            deterministic_score=73,
            gray=gray(
                "APPLY",
                0,
            ),
        )
    )

    assert decision == "APPLY"
    assert score == 73


def test_timeout_preserves_deterministic_74():

    decision, score, reason = (
        _resolve_gray_advisory(
            deterministic_score=74,
            gray=None,
        )
    )

    assert decision == "REVIEW"
    assert score == 74
    assert reason == "llm_unavailable"


def test_timeout_preserves_deterministic_55():

    decision, score, reason = (
        _resolve_gray_advisory(
            deterministic_score=55,
            gray=None,
        )
    )

    assert decision == "REVIEW"
    assert score == 55


def test_llm_apply_cannot_promote_weak_deterministic_score():

    decision, score, reason = (
        _resolve_gray_advisory(
            deterministic_score=55,
            gray=gray(
                "APPLY",
                99,
            ),
        )
    )

    assert decision == "REVIEW"
    assert score == 55


def test_llm_review_does_not_change_score():

    decision, score, reason = (
        _resolve_gray_advisory(
            deterministic_score=68,
            gray=gray(
                "REVIEW",
                5,
            ),
        )
    )

    assert decision == "REVIEW"
    assert score == 68


def test_llm_skip_cannot_destroy_strong_deterministic_match():

    decision, score, reason = (
        _resolve_gray_advisory(
            deterministic_score=70,
            gray=gray(
                "SKIP",
                0,
            ),
        )
    )

    assert decision == "REVIEW"
    assert score == 70


def test_llm_skip_can_reject_weak_match():

    decision, score, reason = (
        _resolve_gray_advisory(
            deterministic_score=45,
            gray=gray(
                "SKIP",
                10,
            ),
        )
    )

    assert decision == "SKIP"
    assert score == 45


def test_llm_numeric_score_never_increases_deterministic_score():

    decision, score, reason = (
        _resolve_gray_advisory(
            deterministic_score=62,
            gray=gray(
                "APPLY",
                100,
            ),
        )
    )

    assert decision == "APPLY"
    assert score == 62


def test_score_is_clamped_defensively():

    decision, score, reason = (
        _resolve_gray_advisory(
            deterministic_score=150,
            gray=None,
        )
    )

    assert decision == "REVIEW"
    assert score == 100
