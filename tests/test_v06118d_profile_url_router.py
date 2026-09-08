from agentes.jobs import application_runner as runner


LINKEDIN = (
    "https://www.linkedin.com/in/"
    "bastian-undefined-46171042a/"
)

GITHUB = "https://github.com/bcampusano"


def configure(monkeypatch):

    monkeypatch.setenv(
        "AGENT_PROFESSIONAL_PROFILE_URL",
        LINKEDIN,
    )

    monkeypatch.setenv(
        "AGENT_PORTFOLIO_URL",
        GITHUB,
    )


def test_webpro_portfolio_uses_github(
    monkeypatch,
):

    configure(monkeypatch)

    assert (
        runner._known_profile_url_for_field(
            "webpro_portfolio webpro[portfolio]"
        )
        == GITHUB
    )


def test_spanish_portfolio_uses_github(
    monkeypatch,
):

    configure(monkeypatch)

    assert (
        runner._known_profile_url_for_field(
            "Link a tu portafolio"
        )
        == GITHUB
    )


def test_github_request_uses_github(
    monkeypatch,
):

    configure(monkeypatch)

    assert (
        runner._known_profile_url_for_field(
            "GitHub profile URL"
        )
        == GITHUB
    )


def test_linkedin_uses_linkedin(
    monkeypatch,
):

    configure(monkeypatch)

    assert (
        runner._known_profile_url_for_field(
            "LinkedIn profile URL"
        )
        == LINKEDIN
    )


def test_professional_profile_uses_linkedin(
    monkeypatch,
):

    configure(monkeypatch)

    assert (
        runner._known_profile_url_for_field(
            "Perfil profesional"
        )
        == LINKEDIN
    )


def test_gitlab_is_not_faked(
    monkeypatch,
):

    configure(monkeypatch)

    assert (
        runner._known_profile_url_for_field(
            "GitLab profile URL"
        )
        is None
    )


def test_random_url_is_untouched(
    monkeypatch,
):

    configure(monkeypatch)

    assert (
        runner._known_profile_url_for_field(
            "API endpoint URL"
        )
        is None
    )
