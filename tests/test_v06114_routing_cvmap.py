from pathlib import Path

import pytest

import agentes.jobs.application_runner as app_runner


class _Body:

    async def inner_text(self):
        return ""


class _Page:

    def __init__(self):
        self.url = (
            "https://www.getonbrd.com/jobs/test/"
            "applications/new?step=basic"
        )

    def locator(
        self,
        selector,
    ):
        assert selector == "body"
        return _Body()


@pytest.mark.asyncio
async def test_basic_query_without_basic_dom_is_not_basic(
    monkeypatch,
):
    page = _Page()

    async def fake_step(_page):
        return "basic"

    async def no_basic(_page):
        return False

    async def no_custom(_page):
        return []

    monkeypatch.setattr(
        app_runner,
        "resolve_gob_step",
        fake_step,
    )

    monkeypatch.setattr(
        app_runner,
        "_basic_form_dom_present",
        no_basic,
    )

    monkeypatch.setattr(
        app_runner,
        "extract_custom_fields",
        no_custom,
    )

    stage = await app_runner.detect_stage(
        page
    )

    assert stage == "UNKNOWN"


@pytest.mark.asyncio
async def test_basic_query_with_real_basic_dom_is_basic(
    monkeypatch,
):
    page = _Page()

    async def fake_step(_page):
        return "basic"

    async def has_basic(_page):
        return True

    monkeypatch.setattr(
        app_runner,
        "resolve_gob_step",
        fake_step,
    )

    monkeypatch.setattr(
        app_runner,
        "_basic_form_dom_present",
        has_basic,
    )

    stage = await app_runner.detect_stage(
        page
    )

    assert stage == "BASIC"


def test_new_application_route_has_special_handling():

    source = Path(
        "scripts/jobs_loop.py"
    ).read_text()

    # /applications/new must receive dedicated handling.
    assert (
        'current.endswith('
        in source
    )

    assert (
        '"/applications/new"'
        in source
    )

    # Any legacy phantom /new/edit route must be sanitized.
    assert (
        '"/applications/new/edit"'
        in source
    )

    assert (
        '"/applications/new",'
        in source
    )

    assert (
        "LEGACY ROUTE FIX"
        in source
    )


def test_legacy_uneditable_becomes_safe_blocker():

    source = Path(
        "scripts/jobs_loop.py"
    ).read_text()

    assert (
        "REPAIR_MODE_UNEDITABLE:"
        in source
    )

    assert (
        "LEGACY_REPAIR_BLOCKER:"
        in source
    )

    assert (
        'status="HUMAN_REVIEW"'
        in source
    )


def test_cv_family_map_matches_catalog():

    import re

    source = Path(
        "src/agentes/jobs/analyzer.py"
    ).read_text()

    data_pattern = (
        r'"data"\s*:\s*\{\s*'
        r'"es"\s*:\s*"07_ES"\s*,\s*'
        r'"en"\s*:\s*"08_EN"'
    )

    ops_pattern = (
        r'"ops"\s*:\s*\{\s*'
        r'"es"\s*:\s*"05_ES"\s*,\s*'
        r'"en"\s*:\s*"06_EN"'
    )

    assert re.search(
        data_pattern,
        source,
    )

    assert re.search(
        ops_pattern,
        source,
    )



def test_catalog_meaning_is_consistent():

    source = Path(
        "config/cvs.yaml"
    ).read_text()

    assert 'id: "05_ES"' in source
    assert (
        "DevOps_Cloud_Observability_ES.pdf"
        in source
    )

    assert 'id: "06_EN"' in source
    assert (
        "DevOps_Cloud_Observability_EN.pdf"
        in source
    )

    assert 'id: "07_ES"' in source
    assert (
        "Data_Engineer_PySpark_SQL_ES.pdf"
        in source
    )

    assert 'id: "08_EN"' in source
    assert (
        "Data_Engineer_PySpark_SQL_EN.pdf"
        in source
    )


def test_basic_stage_is_dom_guarded():

    source = Path(
        "src/agentes/jobs/application_runner.py"
    ).read_text()

    assert (
        "_basic_form_dom_present"
        in source
    )

    assert (
        "BASIC STAGE GUARD"
        in source
    )
