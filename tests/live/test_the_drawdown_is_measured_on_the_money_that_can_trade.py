"""The drawdown denominator (2026-09-20), which is M-007's correction one instrument over.

The page carried three drawdowns and none of them answered "我的回撤是多少".  `drawdown_state` reads
total equity and reports the DEEPEST reading ever; `drawdown_vs_hwm_pct` reads total equity and reports
today's; `ladder_drawdown_pct` reads the book's attributed P&L against the ladder's own anchor.  The
fourth line, `giveback_since_hwm_in_usdt_pct`, looks like the answer and is not: it divides a
total-equity giveback by a USDT base, so its numerator and its denominator come from two series whose
high-water marks were 13 hours apart on the day this was written.

That mixing was a decision, not an oversight - A-GB01 (2026-09-15) chose it explicitly, because a
high-water mark on the USDT series "would be a FOURTH ruler on a page whose problem is that it already
carries three".  The operator overturned it on 2026-09-20: collateral cannot open a position, so the
drawdown that matters is the tradable money's, numerator and denominator both.

What the mixing cost, on the live record: 6.58% printed where the tradable series was down 6.00%, and
on 2026-09-16 the page read 5.92% while that series had drawn down 11.40%.
"""

from __future__ import annotations

import pytest

from starquant_live.reports import _noise_scale_lines, _risk_budget_lines, _tradable_drawdown_line
from starquant_live.risk_budget import RiskBudgetParams, risk_budget_status, usdt_drawdown_state

HOUR = 3_600_000
BAR = 1_789_000_000_000
PARAMS = RiskBudgetParams()


def _cycle(i: int, *, equity: float, usdt: float, rebaselined: bool = False) -> dict:
    row: dict = {
        "bar_open_ms": BAR + i * HOUR,
        "at": f"2026-09-20T{i:02d}:00:00+00:00",
        "equity": equity,
        "collateral": {"equity": equity, "usdt_equity": usdt, "collateral": equity - usdt},
    }
    if rebaselined:
        row["external_flows"] = {"rebaselined": True}
    return row


# --- the mark itself, which is the whole of the ruling -------------------------------------------------


def test_the_tradable_series_keeps_its_own_high_water_mark() -> None:
    """The two series peak on different bars, which is why one cannot be read off the other.

    Bar 1 is the total-equity high (collateral up 200, USDT flat); bar 2 is the USDT high.  Any reading
    that takes its numerator from one mark and its denominator from the other is measuring a fall that
    started at neither.
    """
    rows = [
        _cycle(0, equity=10_000.0, usdt=5_000.0),
        _cycle(1, equity=10_200.0, usdt=5_000.0),  # collateral repriced, the book did nothing
        _cycle(2, equity=10_100.0, usdt=5_100.0),  # the book made 100, collateral gave back 200
        _cycle(3, equity=9_900.0, usdt=4_900.0),
    ]

    block = usdt_drawdown_state(rows, PARAMS)

    assert block["peak"] == 5_100.0, "the USDT mark is bar 2's, not bar 1's"
    assert block["peak_at"] == "2026-09-20T02:00:00+00:00"
    assert block["value"] == pytest.approx(200.0 / 5_100.0)
    # And the two rulers do not differ by the denominator alone: total equity fell 300 over those two
    # bars because 100 of it was collateral being remarked, while the tradable money fell 200.  Different
    # numerator, different mark, different denominator - which is why one cannot be rescaled into the
    # other, and why `giveback_since_hwm_in_usdt_pct` taking one from each is not a rounding matter.
    assert block["value"] / (1.0 - 9_900.0 / 10_200.0) == pytest.approx(1.333, abs=0.001)


def test_current_and_deepest_are_both_reported_because_the_page_had_only_one() -> None:
    """「回撤是多少」was answered with the deepest reading ever when the question was about today."""
    rows = [
        _cycle(0, equity=10_000.0, usdt=5_000.0),
        _cycle(1, equity=6_000.0, usdt=1_000.0),  # -80% of the tradable money
        _cycle(2, equity=9_000.0, usdt=4_000.0),  # most of the way back
    ]

    block = usdt_drawdown_state(rows, PARAMS)

    assert block["value"] == pytest.approx(0.20), "today's distance below the mark"
    assert block["max_drawdown"] == pytest.approx(0.80), "the worst hour this account ever had"
    assert block["deepest_at"] == "2026-09-20T01:00:00+00:00"


def test_a_rebaselined_cycle_resets_the_mark() -> None:
    """A demo reset arrives as a TRANSFER; carrying a pre-reset peak reports a drawdown nobody suffered."""
    rows = [
        _cycle(0, equity=10_000.0, usdt=5_000.0),
        _cycle(1, equity=4_000.0, usdt=2_000.0, rebaselined=True),
        _cycle(2, equity=3_800.0, usdt=1_900.0),
    ]

    block = usdt_drawdown_state(rows, PARAMS)

    assert block["peak"] == 2_000.0
    assert block["value"] == pytest.approx(0.05), "5% below the post-reset mark, not 62% below the pre-reset one"


# --- the refusals -------------------------------------------------------------------------------------


def test_a_record_with_no_usdt_reading_refuses_rather_than_reporting_zero() -> None:
    """Every row written before the engine recorded the split is this case, and 0.0 would read as calm."""
    rows = [{"bar_open_ms": BAR, "at": "2026-09-20T00:00:00+00:00", "equity": 10_000.0}]

    block = usdt_drawdown_state(rows, PARAMS)

    assert block["enforced"] is False
    assert block["value"] is None
    assert "usdt_equity" in block["why"]
    assert _tradable_drawdown_line(block).startswith("not enforced")


def test_a_zero_usdt_balance_is_not_a_reading() -> None:
    """Divides no better than a missing one; `margin_and_rejections` already takes this rule."""
    rows = [_cycle(0, equity=10_000.0, usdt=0.0)]

    assert usdt_drawdown_state(rows, PARAMS)["enforced"] is False


# --- the rung conversion, which is the part the ruling needs -------------------------------------------


def test_the_shipped_rungs_convert_to_more_than_a_total_loss_and_that_is_reported_not_clamped() -> None:
    """At 1.86x, `rollback_at` 0.70 lands at 130% of the tradable money - past zero.

    Not a defect in the ladder: it is calibrated on the operator's whole capital under cross margin,
    where the collateral really does absorb losses.  It is the number the 2026-09-20 ruling needs, and
    clamping it to 100% would hide exactly the fact that makes it a decision - that in this denominator
    the rung has no reachable crossing at all.
    """
    rows = [_cycle(0, equity=10_000.0, usdt=5_000.0), _cycle(1, equity=9_000.0, usdt=4_000.0)]

    rungs = usdt_drawdown_state(rows, PARAMS)["rungs_in_this_denominator"]

    assert rungs["deescalate_at"] == PARAMS.deescalate_at * 2.0
    assert rungs["rollback_at"] == PARAMS.rollback_at * 2.0
    assert rungs["rollback_at"] > 1.0, "a rung past a total loss stays visible"


def test_the_conversion_uses_each_series_own_peak_not_the_latest_ratio() -> None:
    """The factor is `total_peak / usdt_peak`; taking it off the last bar would move with the drawdown."""
    rows = [
        _cycle(0, equity=10_000.0, usdt=5_000.0),
        _cycle(1, equity=8_000.0, usdt=3_000.0),  # last-bar ratio is 2.67, peak ratio is 2.00
    ]

    assert usdt_drawdown_state(rows, PARAMS)["vs_total_equity"] == 2.0


# --- what the page shows ------------------------------------------------------------------------------


def test_the_status_block_carries_it_without_turning_the_summary_blind() -> None:
    """It gates nothing, so an unreadable one must not spend the status that says a GATE went unchecked."""
    rows = [{"bar_open_ms": BAR, "at": "2026-09-20T00:00:00+00:00", "equity": 10_000.0}]

    block = risk_budget_status(rows, [], PARAMS, [])

    assert block["usdt_drawdown"]["enforced"] is False
    assert "usdt_drawdown" not in {row["metric"] for row in block["unreadable"]}


def test_the_p13_block_prints_both_drawdowns_adjacent() -> None:
    """Adjacent on purpose: a reader who sees one of the two has the wrong number either way."""
    rows = [_cycle(0, equity=10_000.0, usdt=5_000.0), _cycle(1, equity=9_000.0, usdt=4_000.0)]

    lines = _risk_budget_lines(risk_budget_status(rows, [], PARAMS, []))

    assert "drawdown" in lines and "drawdown (可动用 USDT)" in lines
    assert lines["drawdown"].startswith("10.00%"), "the old line is unchanged"
    assert lines["drawdown (可动用 USDT)"].startswith("当前 20.00%"), "10% of equity is 20% of what can trade"


def test_the_mixed_line_now_says_it_is_mixed() -> None:
    """Not recomputed - the arithmetic was never the failure, the name was."""
    keys = _noise_scale_lines({"giveback_since_hwm_in_usdt_pct": 0.0658})

    mixed = [key for key in keys if key.startswith("giveback_since_hwm_in_usdt_pct")]
    assert len(mixed) == 1
    assert "混口径" in mixed[0]
    assert keys[mixed[0]] == "6.58%", "the number is the same one A-GB01 chose"
    assert any("drawdown (可动用 USDT)" in key for key in keys), "and it points at the one that is not"


def test_the_helper_names_where_the_deepest_reading_happened() -> None:
    """A date, because the reading it supersedes was taken on a day the page printed half of it."""
    rows = [
        _cycle(0, equity=10_000.0, usdt=5_000.0),
        _cycle(1, equity=6_000.0, usdt=1_000.0),
        _cycle(2, equity=9_000.0, usdt=4_000.0),
    ]

    line = _tradable_drawdown_line(usdt_drawdown_state(rows, PARAMS))

    assert "当前 20.00%" in line
    assert "历史最大 80.00%" in line
    assert "2026-09-20T01:00:00+00:00" in line


def test_the_field_the_reading_comes_off_is_the_one_the_loop_writes() -> None:
    """`foreign` was read off the wrong file once and returned [] in silence; a key name is a contract.

    `collateral.usdt_equity` is written by the engine per cycle (`test_collateral_share_is_visible`).
    Spelled out here because this module's other readers take it from `collateral` too, and a rename
    would make every one of them report `enforced: false` rather than fail.
    """
    rows = [_cycle(0, equity=10_000.0, usdt=5_000.0)]
    assert "usdt_equity" in rows[0]["collateral"]

    del rows[0]["collateral"]["usdt_equity"]

    assert usdt_drawdown_state(rows, PARAMS)["enforced"] is False
