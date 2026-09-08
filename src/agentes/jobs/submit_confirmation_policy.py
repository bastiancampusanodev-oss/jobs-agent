from __future__ import annotations

import re
import unicodedata


def _norm(text: str | None) -> str:
    value = unicodedata.normalize("NFKD", text or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.lower()
    value = re.sub(r"\s+", " ", value).strip()
    return value


def is_known_privacy_submit_confirmation(message: str | None) -> bool:
    """
    Allow only the standard Get on Board privacy confirmation observed
    immediately before sending an application.

    This is intentionally narrow. Unknown confirmations, CAPTCHA/MFA,
    identity checks, or any other consent remain human-only.
    """
    text = _norm(message)
    if not text:
        return False

    blocked = (
        "captcha",
        "recaptcha",
        "verification code",
        "codigo de verificacion",
        "mfa",
        "two-factor",
        "2fa",
        "verify your identity",
        "verifica tu identidad",
        "phone verification",
        "verificacion telefonica",
        "sms",
    )
    if any(token in text for token in blocked):
        return False

    spanish = (
        "al enviar tu postulacion" in text
        and "politica de privacidad" in text
    )
    english = (
        (
            "by submitting your application" in text
            or "when you submit your application" in text
        )
        and "privacy policy" in text
    )
    return spanish or english
