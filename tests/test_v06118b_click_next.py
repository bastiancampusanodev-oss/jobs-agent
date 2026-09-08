import asyncio

import pytest

from agentes.jobs import application_runner as runner


class FakeElement:

    def __init__(
        self,
        text,
        enabled,
        invalid=None,
    ):
        self.text = text
        self.enabled = enabled
        self.clicked = False
        self.invalid = invalid or []

    async def is_visible(self):
        return True

    async def inner_text(self):
        return self.text

    async def get_attribute(
        self,
        name,
    ):
        return ""

    async def is_enabled(self):
        return self.enabled

    async def scroll_into_view_if_needed(self):
        return None

    async def click(
        self,
        timeout=None,
    ):
        self.clicked = True

    async def evaluate(
        self,
        script,
    ):
        return self.invalid


class FakeLocator:

    def __init__(
        self,
        items,
    ):
        self.items = items

    async def count(self):
        return len(
            self.items
        )

    def nth(
        self,
        index,
    ):
        return self.items[index]


class FakePage:

    def __init__(
        self,
        buttons,
    ):
        self.buttons = buttons

    def locator(
        self,
        selector,
    ):
        return FakeLocator(
            self.buttons
        )

    async def wait_for_timeout(
        self,
        ms,
    ):
        return None


async def noop_profile_urls(
    page,
):
    return 0


def test_disabled_duplicate_does_not_block_enabled_next(
    monkeypatch,
):

    monkeypatch.setattr(
        runner,
        "_fill_known_professional_profile_urls",
        noop_profile_urls,
    )

    disabled = FakeElement(
        "Next",
        False,
    )

    enabled = FakeElement(
        "Next",
        True,
    )

    page = FakePage(
        [
            disabled,
            enabled,
        ]
    )

    asyncio.run(
        runner.click_next(
            page
        )
    )

    assert disabled.clicked is False
    assert enabled.clicked is True


def test_all_next_candidates_disabled_fail_closed(
    monkeypatch,
):

    monkeypatch.setattr(
        runner,
        "_fill_known_professional_profile_urls",
        noop_profile_urls,
    )

    one = FakeElement(
        "Next",
        False,
        invalid=[
            {
                "id": "real_required",
                "name": "application[field]",
                "type": "text",
                "value": "",
                "required": True,
            }
        ],
    )

    two = FakeElement(
        "Review",
        False,
    )

    page = FakePage(
        [
            one,
            two,
        ]
    )

    with pytest.raises(
        RuntimeError,
        match="todos los botones",
    ):

        asyncio.run(
            runner.click_next(
                page
            )
        )

    assert one.clicked is False
    assert two.clicked is False


def test_final_submit_is_never_next():

    assert (
        runner._is_final_application_submit(
            "Enviar postulación"
        )
        is True
    )

    assert (
        runner._is_next_control_label(
            "Enviar postulación"
        )
        is False
    )

    assert (
        runner._is_next_control_label(
            "Revisar y enviar »"
        )
        is True
    )
