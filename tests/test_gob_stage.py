import asyncio
from pathlib import Path

from agentes.jobs.gob_stage import repair_step_from_stage, resolve_gob_step


class FakeLocator:
    def __init__(self, *, count=0, value="", attrs=None):
        self._count = count
        self._value = value
        self._attrs = attrs or {}

    @property
    def first(self):
        return self

    async def count(self):
        return self._count

    async def input_value(self):
        return self._value

    async def get_attribute(self, name):
        return self._attrs.get(name)


class FakePage:
    def __init__(self, url, *, hidden_step=None):
        self.url = url
        self.hidden_step = hidden_step

    def locator(self, selector):
        if selector == "input[name='job_application[step]']":
            if self.hidden_step is None:
                return FakeLocator(count=0)
            return FakeLocator(count=1, value=self.hidden_step)
        return FakeLocator(count=0)


def run(coro):
    return asyncio.run(coro)


def test_hidden_step_has_priority_over_url_step():
    page = FakePage(
        "https://www.getonbrd.com/applications/123/edit?step=basic",
        hidden_step="custom",
    )

    assert run(resolve_gob_step(page)) == "custom"


def test_query_step_detects_custom_without_hidden_input():
    page = FakePage(
        "https://www.getonbrd.com/applications/123/edit?step=custom"
    )

    assert run(resolve_gob_step(page)) == "custom"


def test_unknown_step_is_not_treated_as_editable():
    page = FakePage(
        "https://www.getonbrd.com/applications/123/edit?step=review"
    )

    assert run(resolve_gob_step(page)) is None


def test_stage_fallback_maps_back_to_repair_step():
    assert repair_step_from_stage("PROFILE") == "experience"
    assert repair_step_from_stage("BASIC") == "basic"
    assert repair_step_from_stage("CUSTOM") == "custom"
    assert repair_step_from_stage("REVIEW") is None


def test_jobs_loop_contains_controlled_target_and_stable_tiebreak():
    text = Path("scripts/jobs_loop.py").read_text(encoding="utf-8")

    assert 'parser.add_argument(\n        "--url"' in text
    assert "url ASC" in text
    assert "target_url: str | None = None" in text
