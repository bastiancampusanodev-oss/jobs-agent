from pathlib import Path

from agentes.jobs.submit_confirmation_policy import (
    is_known_privacy_submit_confirmation,
)


def test_spanish_getonbrd_privacy_confirmation_is_allowed():
    message = (
        "Al enviar tu postulación, estás manifestando tu conformidad "
        "con la versión más reciente de nuestra Política de Privacidad"
    )
    assert is_known_privacy_submit_confirmation(message)


def test_english_privacy_confirmation_is_allowed():
    message = (
        "By submitting your application, you agree to the latest "
        "version of our Privacy Policy"
    )
    assert is_known_privacy_submit_confirmation(message)


def test_unknown_confirmation_is_not_allowed():
    assert not is_known_privacy_submit_confirmation(
        "Are you sure you want to continue?"
    )


def test_security_challenge_is_never_allowed_even_with_privacy_words():
    assert not is_known_privacy_submit_confirmation(
        "Al enviar tu postulación aceptas la Política de Privacidad. "
        "Ingresa el código de verificación SMS."
    )


def test_jobs_loop_installs_dialog_guard_before_click():
    text = Path("scripts/jobs_loop.py").read_text(encoding="utf-8")
    listener = text.index('page.on("dialog", _submit_dialog_guard)')
    click = text.index("await target.click(", listener)
    assert listener < click
    assert 'await dialog.accept()' in text
    assert 'await dialog.dismiss()' in text
    assert 'return "CONFIRMATION_REQUIRED"' in text
