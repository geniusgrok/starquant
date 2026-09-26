"""Two clauses of the plan that were never delivered, found by reading it against the code.

DL-L3 asks for dedup **and** `run_check.sh` 同源去重 - the same deduplication in the check script.
KILL-R7's evidence was 36 identical FAIL lines over 36 hours, and those came from the HOURLY CHECK
JOB, not from the loop: the check runs as a fresh process every hour, so an in-memory dedup dict is
empty every time and cannot suppress anything.  Dedup that only works inside one long-lived process
is dedup aimed away from the case that produced the finding.

DL-L5's last clause asks that a non-empty `foreign_positions` at startup 告警而非静默 - alert rather
than stay silent.  It logs.  A line in a file nobody reads is what "silent" means to an operator, and
foreign positions are money on the venue the loop has decided not to manage.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx

from starquant_live.alerts import HOURLY_CALLER_WINDOW_SECONDS


def _ok(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"code": 0})


def _counting(counter: list[int]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        counter.append(1)
        return httpx.Response(200, json={"code": 0})

    return httpx.MockTransport(handler)


async def test_dedup_survives_the_process_that_did_the_deduping(tmp_path: Path) -> None:
    """The hourly check job is a new process every hour; in-memory state helps it not at all."""
    from starquant_live.alerts import WebhookAlerts

    posts: list[int] = []
    state = tmp_path / "alert-state.json"
    for _ in range(5):  # five separate "processes"
        alerts = WebhookAlerts("https://open.feishu.cn/x", transport=_counting(posts), state_path=state)
        await alerts.send("the same standing problem", key="check-status")

    assert len(posts) == 1


async def test_the_window_still_re_announces_a_standing_problem(tmp_path: Path) -> None:
    """Hourly, not never: KILL-R7 wants the fifth hour quiet and the next window loud."""
    from starquant_live.alerts import WebhookAlerts

    posts: list[int] = []
    state = tmp_path / "alert-state.json"
    clock = [0.0]
    for _ in range(3):
        alerts = WebhookAlerts(
            "https://open.feishu.cn/x",
            transport=_counting(posts),
            state_path=state,
            dedup_window_seconds=3600.0,
            clock=lambda: clock[0],
        )
        await alerts.send("standing", key="k")
    assert len(posts) == 1

    clock[0] = 3601.0
    alerts = WebhookAlerts(
        "https://open.feishu.cn/x",
        transport=_counting(posts),
        state_path=state,
        dedup_window_seconds=3600.0,
        clock=lambda: clock[0],
    )
    await alerts.send("standing", key="k")

    assert len(posts) == 2


async def test_a_corrupt_state_file_costs_a_duplicate_not_an_alert(tmp_path: Path) -> None:
    """This is a cache.  It may never be the reason a message does not go out."""
    from starquant_live.alerts import WebhookAlerts

    state = tmp_path / "alert-state.json"
    state.write_text("{not json", encoding="utf-8")
    posts: list[int] = []

    alerts = WebhookAlerts("https://open.feishu.cn/x", transport=_counting(posts), state_path=state)

    assert await alerts.send("hello", key="k") is True
    assert len(posts) == 1


async def test_only_a_delivered_message_is_remembered(tmp_path: Path) -> None:
    """A dropped message must not suppress the retry an hour later."""
    from starquant_live.alerts import WebhookAlerts

    state = tmp_path / "alert-state.json"
    rejecting = httpx.MockTransport(lambda r: httpx.Response(200, json={"code": 19002}))
    assert (
        await WebhookAlerts("https://open.feishu.cn/x", transport=rejecting, state_path=state).send("x", key="k")
        is False
    )

    posts: list[int] = []
    assert (
        await WebhookAlerts("https://open.feishu.cn/x", transport=_counting(posts), state_path=state).send("x", key="k")
        is True
    )
    assert len(posts) == 1


async def test_a_foreign_position_at_startup_alerts(tmp_path: Path) -> None:
    """DL-L5's last clause: money on the venue the loop has decided not to manage."""
    from tests.live.helpers_liquidation import startup_with_foreign_position

    sent = await startup_with_foreign_position(["DOGEUSDT"])

    assert any("DOGEUSDT" in message and "不在本循环管理" in message for message in sent), sent


async def test_a_clean_startup_says_nothing(tmp_path: Path) -> None:
    from tests.live.helpers_liquidation import startup_with_foreign_position

    sent = await startup_with_foreign_position([])

    assert not any("foreign" in message.lower() for message in sent)


def test_every_process_that_shares_the_dedup_FILE_shares_its_window() -> None:
    """`live_cmd` says it out loud - "One dedup window across every process that can alert (DL-L3)" -
    and for one afternoon that sentence was false.  `HOURLY_CALLER_WINDOW_SECONDS` moved to 3540 and
    reached `report daily` and `run_check.sh`, which pass no window; the loop kept 3600, because the
    shipped profile stated the old default and `live_cmd` hardcoded it a second time as a fallback.
    Two copies of a number that must agree are how they stop agreeing, so the number now has one home
    and this asserts the shipped profile does not quietly grow a second."""
    from starquant_shared.config import load_yaml

    alerts = load_yaml("config/live.demo.yaml").get("alerts", {}) or {}
    window = float(alerts.get("dedup_window_seconds", HOURLY_CALLER_WINDOW_SECONDS))

    assert window == HOURLY_CALLER_WINDOW_SECONDS
    assert "3600.0)" not in Path("starquant_cli/live_cmd.py").read_text(encoding="utf-8")


def test_the_check_script_keeps_the_readings_from_the_runs_that_PASSED() -> None:
    """`verify`'s tolerance cannot be set from `verify-failures.jsonl`: that file records only runs
    that exceeded the tolerance, so it is a sample censored at the number under test.  The passing
    runs are the other half of the distribution, and the reading has to be attached to the line that
    is written when a check passes - mentioning it in a comment would keep none of them."""
    script = Path("deploy/run_check.sh").read_text(encoding="utf-8")

    assert 'ok   $check$(reading "$check" "$output")' in script
    assert "max_contribution_diff" in script


def test_the_check_script_uses_the_shared_dedup_state() -> None:
    """`run_check.sh` must pass a state path, or its dedup is the in-memory one that cannot work."""
    script = Path("deploy/run_check.sh").read_text(encoding="utf-8")

    assert "state_path" in script
    assert "force=True" not in script


async def test_a_foreign_open_order_at_startup_alerts() -> None:
    """AC-L5's other half, and the same shape as DL-L5's foreign positions.

    The FILTER is right and verified against the real venue (2026-09-07: a hand-placed
    `manual-acl5-…` order survived a real `startup_reconcile` with `cancel_stale_orders=True`).  What
    is missing is telling anyone.  A resting order the loop did not place is either the operator's or
    a leftover from something that crashed, and both are things you want to hear about at startup
    rather than discover in a fill.
    """
    from tests.live.helpers_liquidation import startup_with_foreign_order

    sent = await startup_with_foreign_order("manual-acl5-1")

    assert any("manual-acl5-1" in m and "挂单" in m for m in sent), sent


async def test_our_own_resting_order_is_not_announced_as_foreign() -> None:
    """`bd-` orders are cancelled by the reconcile; announcing them would be noise every restart."""
    from tests.live.helpers_liquidation import startup_with_foreign_order

    sent = await startup_with_foreign_order("bd-BTCUSDT-123")

    assert not any("foreign" in m.lower() and "order" in m.lower() for m in sent), sent


# --- The persisted window's clock, and the window's own length -----------------------------------
#
# `test_a_corrupt_state_file_costs_a_duplicate_not_an_alert` above states the invariant: this is a
# cache, and it may never be the reason a message does not go out.  It was tested against a MALFORMED
# file and broken by a well-formed one.  Three ways, all measured on the live machine 2026-09-14:
#
#   * `time.monotonic()` counts from the machine's last boot, and the file outlives boots.  After the
#     2026-09-10 reboot `check-verify` held 630465.2 against an uptime of 374798.0, so `clock() - last`
#     was -255667 - below any window, forever.  24 of 28 `verify` FAIL lines were never delivered and
#     the key had 71 hours left to run.
#   * the same error in the other direction: a previous boot SHORTER than this one writes a number
#     that reads as a recent delivery, and suppresses a real alert for up to a full window.
#   * the window is measured from the moment the provider ANSWERED, while an hourly caller's cadence
#     is measured from when it started.  An 8-second delivery at 11:10Z put the 12:10Z run 3592s
#     later - inside a 3600s window - and dropped the one FAIL that day that needed the operator.
#
# The fourth is the window itself: 3600s against callers that run hourly is a coin flip, and the live
# loop's cycles start a few seconds apart each hour, which lands on the losing side of it.


def _slow_provider(counter: list[int], clock: list[float], *, seconds: float) -> httpx.MockTransport:
    """A provider that takes `seconds` to answer, the way the real one takes about eight."""

    def handler(request: httpx.Request) -> httpx.Response:
        counter.append(1)
        clock[0] += seconds
        return httpx.Response(200, json={"code": 0})

    return httpx.MockTransport(handler)


async def test_a_timestamp_from_a_longer_previous_boot_does_not_silence_the_alert(tmp_path: Path) -> None:
    """The live numbers, as they sat in the file: a stored value larger than the current uptime."""
    from starquant_live.alerts import WebhookAlerts

    state = tmp_path / "alert-state.json"
    state.write_text(json.dumps({"check-verify": 630465.2}), encoding="utf-8")
    posts: list[int] = []

    alerts = WebhookAlerts(
        "https://open.feishu.cn/x",
        transport=_counting(posts),
        state_path=state,
        clock=lambda: 374798.0,
    )

    assert await alerts.send("verify FAIL", key="check-verify") is True
    assert len(posts) == 1


async def test_a_timestamp_from_a_shorter_previous_boot_does_not_silence_it_either(tmp_path: Path) -> None:
    """The same frame error pointing the other way, where the stale number looks perfectly recent."""
    from starquant_live.alerts import WebhookAlerts

    state = tmp_path / "alert-state.json"
    posts: list[int] = []
    wall = [1_000_000.0]

    # A previous boot, 100 seconds up, delivers and remembers.
    before = WebhookAlerts(
        "https://open.feishu.cn/x",
        transport=_counting(posts),
        state_path=state,
        clock=lambda: 100.0,
        wall_clock=lambda: wall[0],
    )
    assert await before.send("standing", key="k") is True

    # The machine reboots a day later and has been up 200 seconds.  `200 - 100` is inside any window,
    # and the two numbers are from different frames, so the subtraction means nothing.
    wall[0] += 86_400.0
    after = WebhookAlerts(
        "https://open.feishu.cn/x",
        transport=_counting(posts),
        state_path=state,
        clock=lambda: 200.0,
        wall_clock=lambda: wall[0],
    )

    assert await after.send("standing", key="k") is True
    assert len(posts) == 2


async def test_the_window_runs_from_when_the_caller_asked_not_from_when_the_provider_answered() -> None:
    """An hourly caller asks 3600s apart.  What the provider does in between is not its cadence."""
    from starquant_live.alerts import WebhookAlerts

    posts: list[int] = []
    clock = [0.0]
    alerts = WebhookAlerts(
        "https://open.feishu.cn/x",
        transport=_slow_provider(posts, clock, seconds=8.0),
        clock=lambda: clock[0],
        dedup_window_seconds=3600.0,
    )

    await alerts.send("standing", key="k")
    clock[0] = 3600.0  # the caller's next hourly run, exactly one window later
    await alerts.send("standing", key="k")

    assert len(posts) == 2


async def test_an_hourly_caller_that_drifts_a_few_seconds_is_not_deduplicated_against_itself() -> None:
    """The live loop's cycles start a few seconds apart each hour; the default window must clear that."""
    from starquant_live.alerts import WebhookAlerts

    posts: list[int] = []
    clock = [0.0]
    alerts = WebhookAlerts(  # the DEFAULT window: this is the number under test
        "https://open.feishu.cn/x",
        transport=_counting(posts),
        clock=lambda: clock[0],
    )

    for start in (0.0, 3597.0, 7194.0, 10791.0):
        clock[0] = start
        await alerts.send("standing", key="k")

    assert len(posts) == 4
