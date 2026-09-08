import asyncio

from agentes.jobs import application_runner as runner


class FakePage:

    async def wait_for_timeout(
        self,
        ms,
    ):
        return None


def test_transition_waits_for_stable_new_stage(
    monkeypatch,
):

    states = iter(
        [
            "BASIC",
            "CUSTOM",
            "CUSTOM",
        ]
    )

    async def fake_detect(
        page,
    ):
        return next(
            states,
            "CUSTOM",
        )

    monkeypatch.setattr(
        runner,
        "detect_stage",
        fake_detect,
    )

    result = asyncio.run(
        runner._wait_for_next_transition(
            FakePage(),
            "BASIC",
            timeout_ms=1500,
        )
    )

    assert result == "CUSTOM"


def test_transition_timeout_is_fail_closed(
    monkeypatch,
):

    async def fake_detect(
        page,
    ):
        return "BASIC"

    monkeypatch.setattr(
        runner,
        "detect_stage",
        fake_detect,
    )

    result = asyncio.run(
        runner._wait_for_next_transition(
            FakePage(),
            "BASIC",
            timeout_ms=500,
        )
    )

    assert result == "BASIC"


def test_unknown_previous_stage_does_not_invent_transition():

    result = asyncio.run(
        runner._wait_for_next_transition(
            FakePage(),
            None,
            timeout_ms=500,
        )
    )

    assert result is None
