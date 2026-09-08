from __future__ import annotations

from urllib.parse import parse_qsl, urlsplit


EDITABLE_GOB_STEPS = {
    "experience",
    "basic",
    "custom",
    "questions",
}


_STEP_ALIASES = {
    "experience": "experience",
    "basic": "basic",
    "custom": "custom",
    # Get on Board currently exposes this editable page as
    # ?step=questions. Internally it is our CUSTOM stage.
    "questions": "custom",
}


def normalize_gob_step(value: str | None) -> str | None:
    return _STEP_ALIASES.get(
        str(value or "").strip().casefold()
    )


_STAGE_TO_REPAIR_STEP = {
    "PROFILE": "experience",
    "BASIC": "basic",
    "CUSTOM": "custom",
}


async def resolve_gob_step(page) -> str | None:
    """Resolve Get on Board's canonical editable application step.

    Priority:
      1. hidden ``job_application[step]`` input
      2. ``?step=...`` in the current URL

    Visual/DOM heuristics belong to ``detect_stage`` and are intentionally
    kept outside this resolver.
    """

    step_input = page.locator(
        "input[name='job_application[step]']"
    )

    if await step_input.count():
        candidate = ""

        try:
            candidate = (
                await step_input.first.input_value()
            ).strip().casefold()
        except Exception:
            try:
                candidate = (
                    await step_input.first.get_attribute(
                        "value"
                    )
                    or ""
                ).strip().casefold()
            except Exception:
                candidate = ""

        normalized = normalize_gob_step(candidate)
        if normalized is not None:
            return normalized

    try:
        query = urlsplit(page.url).query
    except Exception:
        query = ""

    for key, value in parse_qsl(
        query,
        keep_blank_values=True,
    ):
        if key.casefold() != "step":
            continue

        candidate = value.strip().casefold()

        normalized = normalize_gob_step(candidate)
        if normalized is not None:
            return normalized

    return None


def repair_step_from_stage(stage: str) -> str | None:
    """Map the agent stage name back to Get on Board's editable step."""

    return _STAGE_TO_REPAIR_STEP.get(
        str(stage or "").strip().upper()
    )
