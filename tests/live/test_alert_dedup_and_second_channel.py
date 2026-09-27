"""DL-L3: an alert channel that repeats itself is a channel nobody reads.

KILL-R7 measured the failure mode in the repo's own logs: 40 FAIL lines in check.stdout.log, 36 of
them the same sentence, for 36 hours, unhandled.  An unattended loop's only output is its alerts, so
a duplicate storm is not cosmetic - it is how the one alert that matters gets missed.

Two changes, and the order between them is load-bearing.  DL-L2 turns the breaker into a clean exit
(``sys.exit(0)``, which launchd will not relaunch), and a book that stops silently is worse than one
that hot-loops every 60 seconds.  So the breaker's alert has to be deliverable *before* the breaker
is allowed to stop the loop: ``force`` bypasses dedup and the return value says whether any channel
took it.  That is what makes KILL-P1 a sequencing constraint rather than a hope.
"""

from __future__ import annotations

import httpx
import pytest

from starquant_live.alerts import WebhookAlerts


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _recorder(bucket: list[tuple[str, str]], *, status: int = 200) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        bucket.append((str(request.url), request.content.decode()))
        return httpx.Response(status)

    return httpx.MockTransport(handler)


async def test_the_same_alert_inside_the_window_is_sent_once() -> None:
    sent: list[tuple[str, str]] = []
    clock = _Clock()
    alerts = WebhookAlerts("https://hook/a", transport=_recorder(sent), clock=clock, dedup_window_seconds=3600)

    for _ in range(10):
        await alerts.send("report daily --check FAIL: changes_7d 2 > 1")
        clock.now += 60.0

    assert len(sent) == 1


async def test_it_repeats_once_the_window_passes_so_a_standing_problem_is_not_forgotten() -> None:
    sent: list[tuple[str, str]] = []
    clock = _Clock()
    alerts = WebhookAlerts("https://hook/a", transport=_recorder(sent), clock=clock, dedup_window_seconds=3600)

    await alerts.send("still broken")
    clock.now += 3599.0
    await alerts.send("still broken")
    clock.now += 2.0
    await alerts.send("still broken")

    assert len(sent) == 2


async def test_recovery_re_arms_the_alert() -> None:
    """Edge-triggered, like the guard announcements: cleared state means the next one fires."""
    sent: list[tuple[str, str]] = []
    clock = _Clock()
    alerts = WebhookAlerts("https://hook/a", transport=_recorder(sent), clock=clock)

    await alerts.send("venue unreachable", key="venue")
    await alerts.send("venue unreachable", key="venue")
    alerts.clear("venue")
    await alerts.send("venue unreachable", key="venue")

    assert len(sent) == 2


async def test_different_alerts_do_not_suppress_each_other() -> None:
    sent: list[tuple[str, str]] = []
    alerts = WebhookAlerts("https://hook/a", transport=_recorder(sent), clock=_Clock())

    await alerts.send("guards engaged")
    await alerts.send("probe book stopped")

    assert len(sent) == 2


async def test_a_forced_alert_ignores_dedup() -> None:
    """The breaker's last words are never a duplicate, however many times it failed on the way down."""
    sent: list[tuple[str, str]] = []
    alerts = WebhookAlerts("https://hook/a", transport=_recorder(sent), clock=_Clock())

    await alerts.send("cycle failed", key="cycle")
    delivered = await alerts.send("breaker tripped, exiting", key="cycle", force=True)

    assert delivered is True
    assert len(sent) == 2


async def test_both_channels_receive_the_alert() -> None:
    sent: list[tuple[str, str]] = []
    alerts = WebhookAlerts("https://hook/a", secondary_url="https://hook/b", transport=_recorder(sent), clock=_Clock())

    assert await alerts.send("something") is True
    assert sorted(url for url, _ in sent) == ["https://hook/a", "https://hook/b"]


async def test_one_dead_channel_does_not_lose_the_alert() -> None:
    """A second channel exists precisely for the hour the first one is down."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "dead":
            raise httpx.ConnectError("no route", request=request)
        return httpx.Response(200)

    alerts = WebhookAlerts(
        "https://dead/a", secondary_url="https://live/b", transport=httpx.MockTransport(handler), clock=_Clock()
    )

    assert await alerts.send("something") is True


async def test_delivery_failure_is_reported_so_the_breaker_can_refuse_to_exit_quietly() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    alerts = WebhookAlerts("https://dead/a", transport=httpx.MockTransport(handler), clock=_Clock())

    assert await alerts.send("breaker tripped", force=True) is False


async def test_a_suppressed_alert_is_not_a_delivery() -> None:
    sent: list[tuple[str, str]] = []
    alerts = WebhookAlerts("https://hook/a", transport=_recorder(sent), clock=_Clock())

    assert await alerts.send("x") is True
    assert await alerts.send("x") is False  # suppressed, not delivered - the caller can tell


async def test_disabled_alerts_stay_disabled() -> None:
    alerts = WebhookAlerts("")

    assert alerts.enabled is False
    assert await alerts.send("anything") is False
    assert await alerts.send("anything", force=True) is False


@pytest.mark.parametrize("status", [400, 500])
async def test_a_rejecting_channel_counts_as_undelivered(status: int) -> None:
    sent: list[tuple[str, str]] = []
    alerts = WebhookAlerts("https://hook/a", transport=_recorder(sent, status=status), clock=_Clock())

    assert await alerts.send("x", force=True) is False
