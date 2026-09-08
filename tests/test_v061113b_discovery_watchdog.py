import asyncio

from scripts import jobs_loop


class NoNetworkPage:
    pass


def test_discovery_is_deferred_with_large_backlog(
    monkeypatch,
):
    monkeypatch.setenv(
        "JOB_DISCOVERY_BACKLOG_THRESHOLD",
        "20",
    )

    monkeypatch.setattr(
        jobs_loop,
        "queued_retry_urls",
        lambda limit, submit=False: [
            f"https://example.test/{i}"
            for i in range(20)
        ],
    )

    result = asyncio.run(
        jobs_loop.discover_jobs(
            NoNetworkPage(),
            scrolls=1,
        )
    )

    assert result == []


class HangingPage:

    class Mouse:
        async def wheel(self, *args):
            return None

    def __init__(self):
        self.mouse = self.Mouse()

    async def goto(
        self,
        *args,
        **kwargs,
    ):
        await asyncio.sleep(10)


def test_discovery_navigation_has_outer_watchdog(
    monkeypatch,
):
    monkeypatch.setenv(
        "JOB_DISCOVERY_BACKLOG_THRESHOLD",
        "20",
    )

    monkeypatch.setenv(
        "JOB_DISCOVERY_NAV_HARD_TIMEOUT",
        "0.02",
    )

    monkeypatch.setenv(
        "JOB_DISCOVERY_TOTAL_BUDGET",
        "2",
    )

    monkeypatch.setattr(
        jobs_loop,
        "queued_retry_urls",
        lambda limit, submit=False: [],
    )

    monkeypatch.setattr(
        jobs_loop,
        "GLOBAL_JOB_SEEDS",
        [
            (
                "TEST_CATEGORY",
                "https://example.test/jobs",
                "programming",
            )
        ],
    )

    result = asyncio.run(
        jobs_loop.discover_jobs(
            HangingPage(),
            scrolls=1,
        )
    )

    # Hanging navigation must be isolated and the
    # discovery call must still finish normally.
    assert result == []
