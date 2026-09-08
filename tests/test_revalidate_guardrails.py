from pathlib import Path


TEXT = Path("scripts/jobs_loop.py").read_text(encoding="utf-8")


def test_revalidate_is_explicit_dry_run_target_only():
    assert '"--revalidate"' in TEXT
    assert 'if revalidate and (submit or not target_url):' in TEXT
    assert '--revalidate requiere --dry-run y --url' in TEXT


def test_revalidate_forces_editable_rewalk_and_ready_is_not_skipped():
    assert 'return not (targeted and revalidate)' in TEXT
    assert 'repair_step = "experience"' in TEXT
    assert '🔄 REVALIDATE: draft antiguo será' in TEXT
    assert 'repair_mode = bool(\n                    revalidate' in TEXT
