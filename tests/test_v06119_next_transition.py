import asyncio

from agentes.jobs import application_runner as runner


class Page:
    async def wait_for_timeout(self, ms):
        return None


def test_transition_timeout_is_bounded(monkeypatch):
    monkeypatch.setenv("NEXT_TRANSITION_TIMEOUT_MS", "1")

    async def stage(page):
        return "BASIC"

    monkeypatch.setattr(runner, "_stage_for_next_transition", stage)
    result = asyncio.run(runner._wait_for_next_transition(Page(), "BASIC"))
    assert result == "BASIC"


def test_final_submit_remains_excluded_from_next():
    assert runner._is_next_control_label("Enviar postulación") is False
    assert runner._is_next_control_label("Submit application") is False
    assert runner._is_next_control_label("Revisar y enviar »") is True

class _Button:
    async def is_visible(self):
        return True

    async def inner_text(self):
        return "Siguiente"

    async def get_attribute(self, name):
        return ""

    async def is_enabled(self):
        return True

    async def scroll_into_view_if_needed(self):
        return None

    async def click(self, timeout=None):
        return None

    async def evaluate(self, script):
        return []


class _Locator:
    def __init__(self, items):
        self.items = items

    async def count(self):
        return len(self.items)

    def nth(self, index):
        return self.items[index]


class _ClickPage(Page):
    def locator(self, selector):
        return _Locator([_Button()])


def test_click_next_quarantines_same_stage(monkeypatch):
    async def no_urls(page):
        return 0

    async def stage(page):
        return "BASIC"

    async def stuck(page, previous_stage, timeout_ms=None):
        return previous_stage

    monkeypatch.setattr(
        runner,
        "_fill_known_professional_profile_urls",
        no_urls,
    )
    monkeypatch.setattr(runner, "_stage_for_next_transition", stage)
    monkeypatch.setattr(runner, "_wait_for_next_transition", stuck)

    import pytest

    with pytest.raises(RuntimeError, match="NEXT_TRANSITION_STALLED"):
        asyncio.run(runner.click_next(_ClickPage()))
