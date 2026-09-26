"""DL-L2: the breaker stops the loop instead of feeding it back to launchd every 60 seconds.

``KeepAlive.SuccessfulExit=false`` in deploy/com.starquant.live.plist means exit code 0 is not
relaunched, and run_live.sh:24 already says so.  So the whole of L1-03 - a persistent TRIPPED flag,
a process-level backoff counter, and tests for both - collapses into: alert, then exit 0.  Net state
change is negative: ``consecutive_errors`` stops being persisted, because carrying it across
restarts was the thing that made a tripped breaker trip again immediately (KILL-R29).

The sequencing constraint (KILL-P1) is the point of this file.  A loop that exits quietly is worse
than one that hot-loops, because the hot loop at least leaves a trace.  So the clean exit is earned:
the breaker must first get its alert out, and if no channel accepts it the old behaviour stands -
raise, non-zero exit, launchd relaunches, and the operator eventually sees a log full of restarts.
"""

from __future__ import annotations

import pytest

from starquant_live.engine import BreakerTripped


class _Alerts:
    """Enough of WebhookAlerts to record what the breaker tried to say."""

    def __init__(self, *, delivers: bool) -> None:
        self.delivers = delivers
        self.sent: list[tuple[str, bool]] = []
        self.enabled = True

    async def send(self, text: str, *, key: str | None = None, force: bool = False) -> bool:
        self.sent.append((text, force))
        return self.delivers

    def clear(self, key: str) -> None:  # pragma: no cover - not exercised here
        pass


def test_breaker_tripped_is_the_clean_stop_signal() -> None:
    """A distinct type, so the CLI can tell 'the breaker decided' from 'something threw'."""
    tripped = BreakerTripped("venue unreachable 12x")

    assert isinstance(tripped, Exception)
    assert "venue unreachable" in str(tripped)


async def test_the_breaker_alerts_before_it_stops() -> None:
    from starquant_live.engine import breaker_stop

    alerts = _Alerts(delivers=True)

    with pytest.raises(BreakerTripped):
        await breaker_stop(alerts, consecutive_errors=12, detail="ConnectError: no route")

    assert len(alerts.sent) == 1
    text, force = alerts.sent[0]
    assert force is True  # never suppressed as a duplicate of the failures on the way down
    assert "12" in text and "no route" in text


async def test_an_undeliverable_alert_keeps_the_loud_failure() -> None:
    """No channel took it, so the loop must not disappear silently: the original error propagates."""
    from starquant_live.engine import breaker_stop

    alerts = _Alerts(delivers=False)
    original = RuntimeError("ConnectError: no route")

    with pytest.raises(RuntimeError) as caught:
        await breaker_stop(alerts, consecutive_errors=12, detail="x", original=original)

    assert caught.value is original
    assert len(alerts.sent) == 1


async def test_disabled_alerts_still_stop_the_loop_loudly() -> None:
    """An operator with no webhook configured gets the restart loop, which is at least visible."""
    from starquant_live.engine import breaker_stop

    class _Off:
        enabled = False

        async def send(self, text: str, *, key: str | None = None, force: bool = False) -> bool:
            return False

    original = RuntimeError("boom")
    with pytest.raises(RuntimeError):
        await breaker_stop(_Off(), consecutive_errors=12, detail="x", original=original)


def test_consecutive_errors_is_no_longer_persisted() -> None:
    """It was the cause of L1-03, not a symptom: a restart inherited the tripped count and re-tripped."""
    from dataclasses import fields

    from starquant_live.state import LiveState

    persisted = {f.name for f in fields(LiveState)}
    assert "consecutive_errors" not in persisted


def test_a_reloaded_state_carries_no_error_count() -> None:
    """The concrete regression: a state.json written by a tripped process must not re-trip the next one."""
    from starquant_live.state import LiveState

    revived = LiveState.from_dict({"restarts": 12, "consecutive_errors": 12})

    assert not hasattr(revived, "consecutive_errors")
    assert revived.restarts == 12  # everything else still round-trips


def test_the_heartbeat_still_reports_the_live_count() -> None:
    """Dropping it from the *persisted* state must not blind `live status --check`, which reads it."""
    import inspect

    from starquant_live import engine as module

    assert '"consecutive_errors"' in inspect.getsource(module)
