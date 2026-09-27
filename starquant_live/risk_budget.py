"""P13's pre-registered monitoring: is the book still inside the risk budget it was sized for?

`vol_target` is 0.60 against a declared 70% drawdown budget (2026-09-14, D-035); before that, 0.30 against
50%, from a bootstrap whose q95 sat at -43.7%/-49.5%.  That bootstrap resamples weekly blocks, so it keeps
within-week autocorrelation and destroys the multi-month regime structure real bear markets have — it is
optimistic by construction, and the de-escalation ladder below is what covers the gap.  The thresholds were
written before the change went live and are not renegotiated when they fire.  Acting on the EQUITY reading
is deliberately not automated; R8 acts on the attributed one, in the loop (`LiveEngine._risk_ladder`).

Every metric here refuses to read zero when it cannot be computed (the failure this project keeps
finding): a window with too few bars, or one straddling a construction change, reports `enforced: false`
with the reason rather than a number that looks like a pass.
"""

from __future__ import annotations

import math
from bisect import bisect_left
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise
from typing import Any

from starquant_alpha.registry import MAIN_BOOK
from starquant_live.construction import canonical_construction
from starquant_live.cycle_record import latest

DAY_MS = 86_400_000


@dataclass(frozen=True)
class RiskBudgetParams:
    # 2026-09-14: re-derived for the -70% budget declared when `vol_target` went to 0.60, by the
    # shipped rule transcribed (see `Policy.drawdown_ladder`, which is what ACTS - these four are the
    # reporting copy and the two must not disagree).  A mismatch here does not raise; it just makes
    # `action` describe a rung the ladder does not have.
    deescalate_at: float = 0.49  # drawdown from the high-water mark -> step vol_target down
    rollback_at: float = 0.70  # -> all the way back
    deescalate_to: float = 0.45
    rollback_to: float = 0.30
    vol_band: tuple[float, float] = (0.52, 0.76)  # k=0.60, x2 of the k=0.30 pair; profile is authority
    vol_window_days: int = 30
    min_vol_bars: int = 240  # ten days of hourly cycles before the vol estimate says anything
    # M-Q08 states the bar as "slippage <= 2x model", so it is expressed that way rather than as a
    # standalone number: a constant drifts away from the model it is supposed to track.  The old
    # `max_slippage_bps: 10.0` was set "against the cost model's 7 bps" - but 7 is `turnover_bps`,
    # which bundles the 5 bps taker fee with 2 bps of slippage, while this instrument measures price
    # slippage alone.  A fee-inclusive budget judging a fee-exclusive measurement, at 2.5x the stated
    # bar, could not fail: the measured +4.3 bps sat outside M-Q08's 4 and well inside the gate's 10.
    model_slippage_bps: float = 2.0  # what the backtest's cost model charges for slippage
    slippage_multiple: float = 2.0  # M-Q08's "2x"
    slippage_window_days: int = 30
    min_slippage_fills: int = 30
    # M-Q03 (DL-L4 / RISK-P2).  Transcribed from the 2026-09-06 remediation plan's own row - baseline
    # "稳态 0/8", bar "<= 5% / 0" - rather than chosen here, for the same reason `model_slippage_bps`
    # is: the numbers existed, in force, in a document, with nothing reading them.  The share is
    # counted PER CYCLE, which is the reading KILL-R6 explicitly allowed ("或至少按周期计") and the
    # reading its own 0/8 baseline was taken in; the plan's preferred bar-hour weighting needs how long
    # a late-entered position was HELD, and no file records that.  See `reports.restart_cost`.
    max_late_cycle_share: float = 0.05
    max_missed_rebalances: int = 0
    guard_window_days: int = 90
    bars_per_year: float = 8760.0

    def __post_init__(self) -> None:
        if not 0 < self.deescalate_at < self.rollback_at < 1:
            raise ValueError("need 0 < deescalate_at < rollback_at < 1")
        if not 0 < self.vol_band[0] < self.vol_band[1]:
            raise ValueError("vol_band must be an increasing positive pair")

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> RiskBudgetParams:
        if "max_slippage_bps" in payload:
            raise ValueError(
                "max_slippage_bps is retired: the bar is M-Q08's '<= 2x model', so set model_slippage_bps "
                "and slippage_multiple instead.  Left as a plain key it would be dropped here without a "
                "word, and a threshold that silently does nothing is worse than no threshold (L1-04)"
            )
        known = {key: payload[key] for key in cls.__dataclass_fields__ if key in payload}
        if "vol_band" in known:
            low, high = known["vol_band"]
            known["vol_band"] = (float(low), float(high))
        return cls(**known)

    @property
    def max_slippage_bps(self) -> float:
        return self.model_slippage_bps * self.slippage_multiple


def _latest_ms(rows: Sequence[Mapping[str, Any]]) -> int:
    return int(rows[-1].get("bar_open_ms") or 0) if rows else 0


def _latest_collateral_share(rows: Sequence[Mapping[str, Any]]) -> float | None:
    """The newest cycle that recorded one; ``None`` when none did (the field is newer than the log)."""
    block = latest(rows, "collateral")
    share = block.get("share") if isinstance(block, Mapping) else None
    return float(share) if isinstance(share, int | float) else None


def collateral_drift(rows: Sequence[Mapping[str, Any]], attribution: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """How much of the window's equity change was collateral being repriced rather than the book trading.

    The operator ruled on 2026-09-08 (audit question 3) that the denominator stays total equity: it is
    the venue's own margin basis, and under cross margin the collateral really does absorb losses.  That
    ruling makes a pro-cyclical amplifier a NAMED accepted risk rather than an oversight - every weight
    is a fraction of an equity that is 52% non-USDT, so collateral up 10% is every target notional up
    5.2%, and the backtest models no collateral at all.

    An accepted risk with no instrument is a sentence, which is the failure this repository keeps
    finding, so this is the instrument.  It measures and changes nothing.

    The reading is NOT a stable level, and saying so is the point of `direction` below.  Over the first
    23 cycles that recorded a collateral reading (2026-09-07T15:00Z onward) it was 73% - equity -60.11
    against attributed P&L -16.19 - and that number was written into this docstring, into the governance
    plan's §12 and into a test's `assert 0.72 < share < 0.74` as though it described the account.  Over
    the 47 cycles available on 2026-09-09 the same instrument reads 106.8%: equity +36.41 while the book
    was DOWN 2.48.  Both readings are correct and they are not the same kind of statement, so what is
    reported beside the number is which SIDE of 1.0 it sits on, which is a fact about signs rather than
    a level: above 1 the account's equity direction no longer tells you the book's P&L direction.

    Reported, never subtracted.  Subtracting it would silently turn this into the USDT-denominator book
    the operator did not choose.
    """
    priced = [row for row in rows if isinstance((row.get("collateral") or {}).get("equity"), int | float)]
    if len(priced) < 2:
        return {"enforced": False, "reason": f"needs 2 cycles with a collateral reading, has {len(priced)}"}
    first, last = priced[0]["collateral"], priced[-1]["collateral"]
    equity_change = float(last["equity"]) - float(first["equity"])
    since = int(priced[0].get("bar_open_ms") or 0)
    attributed = sum(float(row.get("total") or 0.0) for row in attribution if int(row.get("bar_open_ms") or 0) >= since)
    repriced = equity_change - attributed
    # `None` rather than 0.0 or 1.0 on a flat window: a share of nothing is not a share, and zero
    # would read as "none of it was collateral", which is the opposite of what it would mean.
    share = None if equity_change == 0.0 else repriced / equity_change
    direction = _drift_direction(share)
    return {
        "enforced": True,
        "cycles": len(priced),
        "equity_change": equity_change,
        "attributed_pnl": attributed,
        "collateral_repricing": repriced,
        "repricing_share": share,
        "direction": direction,
        # The one thing a reader of the equity line needs to be told, and the only line this instrument
        # draws.  It is definitional, not calibrated: see `ACCOUNT_MISLEADS_ABOVE`.
        "account_misleads": direction == "book_opposed",
        "collateral_share": _latest_collateral_share(rows),
    }


# The only boundary in this instrument, and there is nothing here to tune.  At `repricing_share` above
# 1 the collateral moved further than the whole equity change, which is the same statement as "the
# book's P&L and the account's equity have OPPOSITE signs" - so below it the equity line still tells a
# reader which way the book went, and above it that reading is wrong.  Moving this off 1.0 would be
# choosing a level, which is exactly the mistake the pinned "73%" made.
ACCOUNT_MISLEADS_ABOVE = 1.0


def _drift_direction(share: float | None) -> str:
    """Which of the three things a window can be, by sign rather than by magnitude.

    ``book_opposed`` is the flagged one because it is the only one that makes the account's own equity
    line misleading about the book.  ``collateral_opposed`` (share below 0) is the other disagreement -
    the book carried more than the whole move and the collateral pushed back - and it is deliberately
    NOT flagged: the equity sign still tells you the book's sign there, so folding the two together
    would leave the flag meaning "the parts disagree", which nobody can act on.
    """
    if share is None:
        return "flat"
    if share > ACCOUNT_MISLEADS_ABOVE:
        return "book_opposed"
    if share < 0.0:
        return "collateral_opposed"
    return "same_direction"


def drawdown_state(rows: Sequence[Mapping[str, Any]], params: RiskBudgetParams) -> dict[str, Any]:
    """Drawdown from the high-water mark, with the mark reset at every re-baselined cycle.

    Re-basing matters on this venue: the demo account resets, and a reset shows up as a TRANSFER row
    rather than as a loss.  Carrying a pre-reset peak forward would report a drawdown nobody suffered.
    Note the direction of the remaining error honestly: the mark is NOT reset on a construction change,
    so a drawdown that began under the old vol target still counts here.  That is deliberate — the budget
    is the operator's capital, not this construction's track record — but it does mean the ladder can
    fire on a loss the current book did not cause.
    """
    peak = drawdown = 0.0
    equity = None
    baseline_at: str | None = None
    bars = 0
    for row in rows:
        value = row.get("equity")
        if not isinstance(value, int | float) or value <= 0:
            continue
        if (row.get("external_flows") or {}).get("rebaselined"):
            peak = float(value)
            baseline_at = str(row.get("at") or "")
        equity = float(value)
        bars += 1
        if baseline_at is None:
            baseline_at = str(row.get("at") or "")
        peak = max(peak, equity)
        drawdown = max(drawdown, 0.0 if peak <= 0 else 1.0 - equity / peak)
    action: str | None = None
    if drawdown >= params.rollback_at:
        action = f"vol_target -> {params.rollback_to}"
    elif drawdown >= params.deescalate_at:
        action = f"vol_target -> {params.deescalate_to}"
    return {
        "value": drawdown,
        "equity": equity,
        "peak": peak or None,
        "baseline_at": baseline_at,
        "bars": bars,
        "deescalate_at": params.deescalate_at,
        "rollback_at": params.rollback_at,
        "action": action,
        # L1-10 measured this and the daily report printed it four blocks away from the ladder that
        # divides by the same equity.  On 2026-09-07, 52.3% of it was non-USDT collateral, so a -35%
        # reading here can belong to BTC rather than to the book.  Reported beside the reading, never
        # subtracted from it: that denominator is a construction decision, not a bug fix (L1-10).
        # `None` rather than 0.0 when no cycle recorded it - zero would read as "none of it is".
        "collateral_share": _latest_collateral_share(rows),
    }


def usdt_drawdown_state(rows: Sequence[Mapping[str, Any]], params: RiskBudgetParams) -> dict[str, Any]:
    """The drawdown of the money that can actually trade: USDT equity against its OWN high-water mark.

    A fourth ruler on a page whose stated problem was that it already carried three, and the decision it
    overturns said exactly that: on 2026-09-15 a high-water mark recomputed on the USDT series "would be
    a FOURTH ruler" (`reports.giveback_check`), so A-GB01 kept both numerators on total equity and moved
    only the denominator.  What that bought is `giveback_since_hwm_in_usdt_pct`: a total-equity giveback
    over a USDT base, measured on neither series.

    Operator ruling, 2026-09-20 - the drawdown that matters is the one the tradable capital suffered,
    numerator and denominator both.  Collateral cannot open a position, which is the argument that
    already moved M-007's denominator; a percentage of an equity half of which cannot trade is not a
    reading about this book's risk.

    The four readings on the day this was added, all of the same account:

    ==============================================  =======
    `drawdown_state` (total equity, historical max)   5.92%
    `drawdown_vs_hwm_pct` (total equity, current)     3.33%
    `giveback_since_hwm_in_usdt_pct` (mixed)          6.58%
    this, current                                     6.00%
    this, historical max                             11.40%
    ==============================================  =======

    The mixed reading is not merely imprecise.  The two series have DIFFERENT high-water marks - 13 hours
    apart on 2026-09-20, total equity 12,368.22 and USDT 6,647.18 - so its numerator and its denominator
    are not measured from the same moment.  And the gap is not cosmetic at depth: at 2026-09-16T02:00Z,
    where this ruler reads its historical max of 11.40%, the page printed 5.92%.

    `value` is CURRENT and `max_drawdown` is the deepest ever, both positive.  Stated because the two
    functions above disagree about which one `value` means - `drawdown_state` reports the historical max
    there and `attributed_drawdown_state` the current distance, negative - and that disagreement is how
    "回撤是多少" was answered with 5.92% when the question was about today.

    Reported, never acted on.  `rungs_in_this_denominator` says what P13's ladder would be asking for if
    the budget were declared in this unit, so that ruling can be made with the number in hand rather than
    after the fact - the shape `attributed_drawdown_state.equity_over_peak` already keeps, and for the
    same reason: moving a rung changes when the book de-risks, which is a risk decision and not a
    reporting one.  The conversion assumes the loss lands in USDT, which is what settlement does and what
    the record shows: over the 269 cycles carrying both readings, 5.25% of the summed absolute equity
    moves were the collateral line moving (range 62.09 U, 1.09% of its mean, against BTC's own 7.28%).
    """
    peak = current_dd = max_dd = 0.0
    usdt: float | None = None
    peak_at = deepest_at = baseline_at = None
    bars = 0
    for row in rows:
        value = (row.get("collateral") or {}).get("usdt_equity")
        if not isinstance(value, int | float) or value <= 0:
            continue
        usdt = float(value)
        if (row.get("external_flows") or {}).get("rebaselined"):
            peak = usdt
            baseline_at = str(row.get("at") or "")
        bars += 1
        if baseline_at is None:
            baseline_at = str(row.get("at") or "")
        if usdt >= peak:
            peak, peak_at = usdt, str(row.get("at") or "")
        current_dd = 0.0 if peak <= 0 else 1.0 - usdt / peak
        if current_dd > max_dd:
            max_dd, deepest_at = current_dd, str(row.get("at") or "")
    if usdt is None:
        return {
            "enforced": False,
            "why": "没有周期记录 collateral.usdt_equity，可动用资金没有序列可以量",
            "value": None,
            "max_drawdown": None,
            "bars": 0,
        }
    # How much deeper the same loss reads here than on total equity, from each series' OWN peak - which
    # is the whole difference between this ruler and the mixed one.  1.86 on 2026-09-20.
    total_peak = max(
        (float(row["equity"]) for row in rows if isinstance(row.get("equity"), int | float) and row["equity"] > 0),
        default=0.0,
    )
    factor = (total_peak / peak) if peak > 0 and total_peak > 0 else None
    return {
        "enforced": True,
        "value": current_dd,
        "max_drawdown": max_dd,
        "equity": usdt,
        "peak": peak,
        "peak_at": peak_at,
        "deepest_at": deepest_at,
        "baseline_at": baseline_at,
        "bars": bars,
        "vs_total_equity": factor,
        # What the shipped rungs ask for once converted, and the reason this block exists: at 1.86 the
        # rollback rung sits ABOVE a total loss of the tradable money, so in this denominator it cannot
        # be reached by the book alone.  Not a defect in the ladder - it is calibrated on the operator's
        # whole capital, under cross margin, where the collateral really does absorb losses - but it is
        # the number the ruling needs, and nothing printed it.
        "rungs_in_this_denominator": None
        if factor is None
        else {
            "deescalate_at": params.deescalate_at * factor,
            "rollback_at": params.rollback_at * factor,
        },
    }


def attributed_drawdown_state(
    rows: Sequence[Mapping[str, Any]],
    attribution: Sequence[Mapping[str, Any]],
    params: RiskBudgetParams,
) -> dict[str, Any]:
    """R8's ruler: the drawdown of the equity path with collateral repricing taken out.

    ``drawdown_state`` above reads venue equity, which is the operator's capital and therefore the
    right denominator for P13's budget.  It is the wrong NUMERATOR for a rule that decides whether the
    book is losing money: 52% of this account is non-USDT collateral and, measured over the 23 cycles
    that carried a collateral reading, 73% of the equity change was repricing rather than trading
    (KILL-AR-05).  Read that 73% as one window's reading and not as a property - on 2026-09-09 the same
    instrument reports 106.8% over 47 cycles, i.e. the equity line was rising while the book lost money,
    which strengthens this argument rather than weakening it.  A -35% equity drawdown can be bitcoin, and
    de-risking a book that never lost anything is a real cost paid for a reading that was never about
    the book.

    So the path here is ``base + cumsum(attributed P&L)``: it starts at the account's equity and moves
    only when the book realises something.  The high-water mark re-bases on the same event
    ``drawdown_state`` uses - a cycle whose external flows were re-baselined - because a demo reset
    arrives as a TRANSFER and carrying a pre-reset peak forward reports a drawdown nobody suffered.

    Like every metric in this file it refuses to report zero when it cannot compute: a record with no
    priced cycle, or with no attribution row inside it, says ``enforced: false`` and why.
    """
    by_bar: dict[int, float] = {}
    for row in attribution:
        bar = row.get("bar_open_ms")
        try:
            key = int(bar)  # type: ignore[arg-type]
            by_bar[key] = by_bar.get(key, 0.0) + float(row.get("total") or 0.0)
        except (TypeError, ValueError):
            continue
    base: float | None = None
    path = peak = 0.0
    drawdown = 0.0
    baseline_at: str | None = None
    bars = 0
    used = 0
    # 2026-09-14: the book's OPEN positions belong in this path.  Taking collateral repricing out is
    # what KILL-AR-05 asked for and is unchanged; taking the book's unrealised P&L out was never part
    # of that and is what made this ladder inert.  Measured over 2021-2026 at k=0.60: the
    # mark-to-market ruler spends 785 bars past the first rung and this one spent 0 - five years and
    # seven months, zero firings, while the book drew down 39.85%.  A momentum book holds its losers,
    # so an income-only ruler learns about a drawdown when it is over.
    #
    # `marked_from` is set at the FIRST row that carries `unrealized`, not at the baseline, so the
    # quantity is continuous across the deploy: the carried term is 0 on that row by construction.
    # Rows written before the field exists contribute nothing and the reading says which ruler it is.
    marked_from: float | None = None
    marked_rows = 0
    for row in rows:
        value = row.get("equity")
        if not isinstance(value, int | float) or value <= 0:
            continue
        equity = float(value)
        if base is None or (row.get("external_flows") or {}).get("rebaselined"):
            base = path = peak = equity
            baseline_at = str(row.get("at") or "")
            bars = 0
            marked_from = None  # a re-baselined path re-anchors the open-position term too
        bars += 1
        try:
            bar_key = int(row.get("bar_open_ms"))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            bar_key = None
        if bar_key is not None and bar_key in by_bar:
            path += by_bar.pop(bar_key)
            used += 1
        mark = row.get("unrealized")
        if isinstance(mark, int | float):
            marked_rows += 1
            if marked_from is None:
                marked_from = float(mark)
            carried = float(mark) - marked_from
        else:
            carried = 0.0
        marked = path + carried
        peak = max(peak, marked)
        current = 0.0 if peak <= 0 else marked / peak - 1.0
        drawdown = min(drawdown, current)
    if base is None:
        return {
            "enforced": False,
            "why": "no cycle carried an equity reading, so there is no path to draw down from",
            "value": None,
            "action": None,
            "rows": 0,
        }
    if used == 0:
        return {
            "enforced": False,
            "why": "no attribution row lands on a priced cycle: the book has realised nothing to measure",
            "value": None,
            "action": None,
            "rows": 0,
            "base": base,
            "baseline_at": baseline_at,
        }
    # Attribution that landed on a bar no priced cycle covers is P&L this path never saw, and dropping
    # it silently would understate the drawdown - the permissive direction.  Zero on the live record as
    # of 2026-09-09; reported rather than assumed, because "it is zero today" is not a property.
    orphaned = sum(by_bar.values())
    action: str | None = None
    if current <= -params.rollback_at:
        action = f"vol_target -> {params.rollback_to}"
    elif current <= -params.deescalate_at:
        action = f"vol_target -> {params.deescalate_to}"
    return {
        "enforced": True,
        # `value` is the CURRENT distance below the running peak, because that is what a ladder is: a
        # book that recovered is not still down.  `drawdown_state` above reports the deepest reading
        # ever instead - correct for a monitor answering "was the budget ever breached", wrong for a
        # rule that acts, which would then be pinned to the worst hour this account ever had.  Both are
        # returned so neither question has to be answered with the other one's number.
        # negative, so it reads the same way as `Policy.throttle_scalar` takes it
        "value": current,
        "max_drawdown": drawdown,
        # WHICH ruler produced `value`, carried with the number rather than assumed by the reader.  A
        # record whose rows predate `unrealized` reads `attributed_pnl` and means exactly what it used
        # to; one whose rows carry it reads `attributed_pnl+unrealized` and is the book's own
        # mark-to-market with collateral still excluded.  The two are not comparable across the
        # boundary, and a name is the only thing that can say so after the fact.
        "ruler": "attributed_pnl+unrealized" if marked_rows else "attributed_pnl",
        "marked_rows": marked_rows,
        "path": path,
        "peak": peak,
        # How far this reading's denominator has drifted from the equity the POSITIONS are sized off.
        # `value` is `marked / peak - 1`, and `peak` moves only when the book makes a new high; the
        # loss that lands in its numerator is `weight x CURRENT equity`, and 52.65% of this account is
        # BTC collateral.  So a move of x% of the book reads as `x% * equity / peak`: above 1 the rung
        # fires EARLIER than the book's own move, below 1 later.  While the book sits under its own
        # high-water mark the factor has no path back to 1 - `peak` is pinned and equity keeps floating.
        # Measured 2026-09-14 over 287 live cycles: 1.000 at the baseline, 1.0154 eleven days later,
        # above 1 on 261 of them (`scratchpad/r8_denominator_drift.py`).
        #
        # Reported, never applied.  Dividing by current equity instead would change WHEN the ladder
        # fires, which is a risk decision and not a reporting one; this exists so that decision is
        # taken with the number in hand rather than after the drift has already moved the rung.
        "equity_over_peak": (equity / peak) if peak > 0 else None,
        "base": base,
        "attributed": path - base,
        "baseline_at": baseline_at,
        "bars": bars,
        "rows": used,
        "deescalate_at": -params.deescalate_at,
        "rollback_at": -params.rollback_at,
        "orphaned_rows": len(by_bar),
        "orphaned_pnl": orphaned,
        "action": action,
    }


def realised_vol(rows: Sequence[Mapping[str, Any]], params: RiskBudgetParams) -> dict[str, Any]:
    """Annualised volatility of the live equity path, enforced only on a single-construction window.

    A bar that absorbed an external cash flow (deposit, demo reset; E-044) is a step in equity, not a
    return, and is skipped - as ``drawdown_state`` and ``reports.drift_check`` already do.  Not
    cosmetic: one +4.7% reset bar adds 0.163 of annualised vol, wider than the [0.26, 0.38] band.
    """
    cutoff = _latest_ms(rows) - params.vol_window_days * DAY_MS
    window = [row for row in rows if int(row.get("bar_open_ms") or 0) >= cutoff]
    priced = [row for row in window if isinstance(row.get("equity"), int | float)]
    # Canonicalised: a fingerprint field-set change is not a construction change, and this gate gave up
    # entirely when it saw two digests (2026-09-07, twice).
    constructions = {canonical_construction(row.get("construction")) for row in window if row.get("construction")}
    returns = [
        float(b["equity"]) / float(a["equity"]) - 1.0
        for a, b in pairwise(priced)
        if float(a["equity"]) > 0 and not (b.get("external_flows") or {}).get("rebaselined")
    ]
    reason = None
    if len(returns) < params.min_vol_bars:
        reason = f"只有 {len(returns)} 根 bar，需要 {params.min_vol_bars} 根"
    elif len(constructions) > 1:
        reason = f"窗口内有 {len(constructions)} 个构造"
    if reason is not None:
        return {"value": None, "band": list(params.vol_band), "bars": len(returns), "enforced": False, "why": reason}
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / max(1, len(returns) - 1)
    annual = math.sqrt(variance * params.bars_per_year)
    low, high = params.vol_band
    return {
        "value": annual,
        "band": [low, high],
        "bars": len(returns),
        "enforced": True,
        "inside": low <= annual <= high,
    }


def books_by_symbol(cycle: Mapping[str, Any] | None) -> dict[str, frozenset[str]]:
    """Which books carry each symbol, from one cycle record.  ``{}`` when the record cannot say.

    `contributions` keys by STRATEGY; `books` (written since 2026-09-12) maps strategy -> book.  A
    record from before that field exists answers "I cannot tell", and every caller then reports one
    undivided population rather than guessing that the strategy id and the book name are the same
    thing - they are not, and assuming so is how a reading about one book gets taken on two.
    """
    # The `if cycle` that used to sit on the first line only guarded THAT line; the walk below went
    # on to call `cycle.get` on the same possibly-None record.  Unreachable in practice - an empty
    # record has no `books` either, so the return above fires first - but the guard reads as if it
    # covered the function and it did not.  One early return, so it does.
    if not cycle:
        return {}
    books = cycle.get("books")
    if not isinstance(books, Mapping) or not books:
        return {}
    out: dict[str, set[str]] = {}
    for strategy, scores in (cycle.get("contributions") or {}).items():
        book = books.get(strategy)
        if book is None or not isinstance(scores, Mapping):
            continue
        for symbol, value in scores.items():
            if value:
                out.setdefault(str(symbol), set()).add(str(book))
    return {symbol: frozenset(names) for symbol, names in out.items()}


def books_by_bar(rows: Sequence[Mapping[str, Any]]) -> dict[int, dict[str, frozenset[str]]]:
    """`books_by_symbol` for every cycle that recorded `books`, keyed by its bar: what its books carried.

    A row without `books` is skipped, not keyed, because keyed it replaces an earlier row for the same
    bar.  A SKIPPED row written after the bar already traded (what a restart's `--immediate` cycle writes
    outside its window) is that row: fed every row on 2026-09-23, two of them (09-13T20:00Z, 09-17T15:00Z)
    turned 18 fills into "cannot say", 52/15/52 where the report's rows read 67/18/34.  `reports._cycles`
    drops them already; this keeps the helper right for a caller that does not.
    """
    return {
        int(row["bar_open_ms"]): books_by_symbol(row)
        for row in rows
        if isinstance(row.get("bar_open_ms"), int | float)
        and not isinstance(row.get("bar_open_ms"), bool)
        and row.get("books")
    }


def fill_grouper(books_at: Mapping[int, Mapping[str, frozenset[str]]]) -> Callable[[int, str], str]:
    """Which population a fill at (bar, symbol) belongs to: main_only, overlaid, other or unattributed.

    Operator ruling 2026-09-23 (G9): a fill is split by the books of ITS OWN cycle and the cycle
    before it - the books whose targets it moved between - never by the newest cycle's map.  Split by
    the newest, every fill read main-only once the probe went flat: 119 fills judged as the main
    book's on 2026-09-23, of which 67 are, 18 overlaid (at +12.10 bps) and 34 from cycles whose
    record cannot name the books.  Its own cycle alone misses a close: 4 fills traded a name no book carried
    on that bar, and the cycle before names who held it.  A cycle with no `books` cannot say, and
    neither can a name no book carried on either side: both are unattributed, never guessed.
    """
    bars = sorted(books_at)

    def group(bar_ms: int, symbol: str) -> str:
        own = books_at.get(bar_ms)
        if not own:
            return "unattributed"
        at = bisect_left(bars, bar_ms)
        previous = books_at.get(bars[at - 1], {}) if at > 0 else {}
        carried = own.get(symbol, frozenset()) | previous.get(symbol, frozenset())
        if carried == {MAIN_BOOK}:
            return "main_only"
        if len(carried) > 1:
            return "overlaid"
        return "other" if carried else "unattributed"

    return group


# What the paging line calls each `fill_grouper` population.  It had two names until G9 added `other`
# and `unattributed`, and on 2026-09-23 17:10Z it paged the 34 unattributed fills as 共载.
SPLIT_LABELS = {"main_only": "主书独有", "overlaid": "两本书共载", "other": "其它书独有", "unattributed": "分不出书"}


def _weighted(values: Sequence[float], sizes: Sequence[float]) -> dict[str, Any]:
    """Notional-weighted mean with the standard error the point estimate never carried.

    `n_eff` is Kish's effective sample size: a weighted mean of 34 fills whose notionals differ by
    6x does not carry 34 fills' worth of information, and dividing by the raw count would understate
    the error bar of the number the alert quotes.
    """
    total = sum(sizes)
    if not values or total <= 0:
        return {"value": None, "fills": len(values), "notional": total, "se": None}
    mean = sum(v * w for v, w in zip(values, sizes, strict=True)) / total
    n_eff = total**2 / sum(w * w for w in sizes)
    variance = sum(w * (v - mean) ** 2 for v, w in zip(values, sizes, strict=True)) / total
    return {
        "value": mean,
        "fills": len(values),
        "notional": total,
        "n_eff": n_eff,
        "sd": math.sqrt(variance),
        "se": math.sqrt(variance / n_eff) if n_eff > 0 else None,
    }


def one_row_per_order(trades: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """The trade log with each venue order once: the row written when it was placed.

    `execute_order` queries before it submits, and a restart that re-runs a bar whose order is already on
    the venue gets back the ack it found under THIS run's plan: the new side, quantity and price beside
    the old order's `executed_qty` and `avg_price`, and `_record_fill` writes that as a row.  It repeats a
    fill the log already holds and can carry the opposite side - order 869468534 is a SELL of 32,080
    1000PEPEUSDT at 2026-09-03T13:00:15Z and, at 13:37:34, a BUY of 33,010 with the same 32,080 filled
    ("already submitted for this bar").  Read twice it doubles the fill, signed by the second row it
    moves a mean the wrong way.

    Keyed by symbol as well as `order_id`, so two symbols' orders cannot merge even if their ids collide;
    a repeat is always the same symbol.  A row without an `order_id` never got an ack, so nothing marks it
    as a repeat and it carries no fill: it is kept.
    """
    seen: set[tuple[str, str]] = set()
    kept: list[Mapping[str, Any]] = []
    for row in trades:
        if row.get("order_id") not in (None, ""):
            key = (str(row.get("symbol") or ""), str(row["order_id"]))
            if key in seen:
                continue
            seen.add(key)
        kept.append(row)
    return kept


def slippage_bps(
    trades: Sequence[Mapping[str, Any]],
    params: RiskBudgetParams,
    *,
    latest_ms: int,
    books_at: Mapping[int, Mapping[str, frozenset[str]]] | None = None,
) -> dict[str, Any]:
    """Notional-weighted adverse fill vs the DECISION BAR CLOSE, against M-Q08's "2x model" bar.

    ``books_at`` (from `books_by_bar`) splits the reading by the books each fill traded for - see
    `fill_grouper` for the rule and for why it is not the newest cycle's map (G9, 2026-09-23).  The
    2026-09-12 ALERT is why: 5.47 bps against a 4 bps bar, which is neither book's number.  The
    fourteen names only the main book holds filled at **0.80 bps**; the four the flow probe adds
    filled at **16.18** (t = 2.31 against the bar, the only one of the three readings that clears
    its own error bar).  An aggregate over two populations describes neither, and this one was about
    to fail a demo-phase success criterion on behalf of a 1/3-fraction probe book.

    The gate is NOT moved here - `inside` still reads the combined number, because which book M-Q08
    judges is an operator's ruling and a criterion that re-points itself when it fires is the shape
    R10 forbids.  What changes is that the split and the error bar are on the page when that ruling
    is made.

    The reference is the decision bar's close because that is what the backtest enters at: weights
    decided on bar t are executed over bar t+1 at its open (`decided.shift(1)` with `open_to_close`),
    and in a continuous market that open is bar t's close.  The venue mark this used to read is an
    index price sampled when the cycle woke; comparing to it answers a question M-Q08 did not ask.

    Rows without `decision_close` - every row written before this field existed - are counted in
    `without_reference` and excluded.  Falling back to the mark is exactly how the wrong number
    would come back, and history is not backfilled.

    Each venue order is read once (`one_row_per_order`): a restart's "already submitted" row is the same
    fill again, possibly under the other side."""
    cutoff = latest_ms - params.slippage_window_days * DAY_MS
    group_of = fill_grouper(books_at) if books_at else None
    values: list[float] = []
    sizes: list[float] = []
    groups: dict[str, tuple[list[float], list[float]]] = {
        name: ([], []) for name in ("main_only", "overlaid", "other", "unattributed")
    }
    by_symbol: dict[str, tuple[list[float], list[float]]] = {}
    without_reference = 0
    for row in one_row_per_order(trades):
        if int(row.get("bar_open_ms") or 0) < cutoff or row.get("flatten"):
            continue
        reference, filled = row.get("decision_close"), row.get("avg_price")
        if reference is None and filled and row.get("executed_qty"):
            without_reference += 1
            continue
        quantity = row.get("executed_qty")
        if not reference or not filled or not quantity:
            continue
        try:
            reference, filled, quantity = float(reference), float(filled), float(quantity)
        except (TypeError, ValueError):
            continue
        if reference <= 0 or filled <= 0 or quantity <= 0:
            continue
        sign = 1.0 if str(row.get("side", "")).upper() == "BUY" else -1.0
        adverse = sign * (filled - reference) / reference * 10_000.0
        size = filled * quantity
        values.append(adverse)
        sizes.append(size)
        symbol = str(row.get("symbol") or "")
        by_symbol.setdefault(symbol, ([], []))
        by_symbol[symbol][0].append(adverse)
        by_symbol[symbol][1].append(size)
        if group_of is not None:
            key = group_of(int(row.get("bar_open_ms") or 0), symbol)
            groups[key][0].append(adverse)
            groups[key][1].append(size)
    fills = len(values)
    notional = sum(sizes)
    whole = _weighted(values, sizes)
    by_group = {name: _weighted(*group) for name, group in groups.items() if group[0]}
    # 2026-09-12 operator ruling: M-Q08 judges the MAIN BOOK.  Its clause is about the execution
    # fidelity of the book whose evidence the demo phase is testing, and a 1/3-fraction probe sleeve
    # already has its own bar for this - `§3 滑点压力 5.5 档` in `validation/book_limits.py`.  The
    # combined number stays computed and printed (the L3 / M-015 shape); what changes is which one
    # `inside` reads.  Where the record cannot split the books the combined reading is judged
    # instead - an unreadable split is not a pass, and every row written before 2026-09-12 is that case.
    # Since G9 the test is per fill: once any fill can be attributed, the main book's own fills are
    # judged, and too few of them is BLIND rather than a fall back to a number that is not the main book's.
    splittable = any(group[0] for name, group in groups.items() if name != "unattributed")
    judged_name = "main_only" if splittable else "combined"
    judged = (by_group.get("main_only") or _weighted([], [])) if splittable else whole
    judged_fills = int(judged["fills"])
    # `is None`, not falsiness: a notional-weighted slippage of exactly 0.0 is a reading, not a gap.
    if judged_fills < params.min_slippage_fills or judged.get("value") is None or notional <= 0:
        # The ruling's honest cost, said in the same breath as the refusal: the main book holds 19 of
        # the 34 fills, so M-Q08 moves from a FAIL it could not support to a BLIND that says how far
        # off an answer is.  BLIND deliberately does not page; it clears itself when the fills arrive.
        return {
            "value": None,
            "limit": params.max_slippage_bps,
            "fills": judged_fills,
            "fills_all_books": fills,
            "judged": judged_name,
            "by_group": by_group,
            "combined": whole,
            "without_reference": without_reference,
            "enforced": False,
            "why": f"{'主书' if judged_name == 'main_only' else '全书'}只有 {judged_fills} 笔成交，"
            f"需要 {params.min_slippage_fills} 笔"
            + (f"；其中 {without_reference} 笔没有 decision_close" if without_reference else "")
            + (
                f"；另有 {len(groups['unattributed'][0])} 笔分不出书，不计入"
                if splittable and groups["unattributed"][0]
                else ""
            ),
        }
    value = float(judged["value"])
    se = judged["se"]
    # Whether the breach can be told from the noise, reported beside the breach rather than instead
    # of it.  On 2026-09-12 the combined reading is 5.47 against 4.0 with se 2.59 - 0.57 SE, which is
    # not a measurement of anything.  `min_slippage_fills` counts fills; it has never asked how much
    # they disagree, and 34 fills with a 12.7 bps spread answer this question no better than 3 do.
    decisive = None if se is None else abs(value - params.max_slippage_bps) > 2.0 * se
    return {
        "value": value,
        "judged": judged_name,
        "limit": params.max_slippage_bps,
        "fills": judged_fills,
        "fills_all_books": fills,
        "without_reference": without_reference,
        "notional": judged.get("notional"),
        "se": se,
        "sd": judged.get("sd"),
        "n_eff": judged.get("n_eff"),
        "decisive": decisive,
        # The whole book as traded, always, whichever reading the bar was taken on.
        "combined": whole,
        "by_group": by_group,
        "worst_symbols": [
            {"symbol": symbol, **_weighted(*rows)}
            for symbol, rows in sorted(by_symbol.items(), key=lambda item: -abs(_weighted(*item[1])["value"] or 0.0))[
                :5
            ]
        ],
        "enforced": True,
        "inside": value <= params.max_slippage_bps,
    }


def guard_firings(rows: Sequence[Mapping[str, Any]], params: RiskBudgetParams) -> dict[str, Any]:
    """How often the two formerly dormant guards actually fire (M-003).

    Reported, never enforced here: the pre-registered test is against the backtest's own frequency, and
    that number lives in a research report rather than in the live state files.  A count that says
    nothing about its comparator is still worth having, because at vol_target 0.15 both were zero.
    """
    cutoff = _latest_ms(rows) - params.guard_window_days * DAY_MS
    window = [row for row in rows if int(row.get("bar_open_ms") or 0) >= cutoff]
    counts = {"DAILY_LOSS_PAUSE": 0, "GROSS_CAPPED": 0}
    for row in window:
        for reason in row.get("guard_reasons") or []:
            if reason in counts:
                counts[reason] += 1
    return {
        "daily_loss_pause_bars": counts["DAILY_LOSS_PAUSE"],
        "gross_capped_bars": counts["GROSS_CAPPED"],
        "bars": len(window),
        "window_days": params.guard_window_days,
    }


def risk_budget_status(
    rows: Sequence[Mapping[str, Any]],
    trades: Sequence[Mapping[str, Any]],
    params: RiskBudgetParams,
    attribution: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """The whole P13 monitoring block: ALERT where a threshold is breached, BLIND where one cannot be read.

    Each metric already refuses to invent a number, but the summary used to collapse "inside the bar"
    and "no reading at all" into the same ``OK``.  On 2026-09-07 that is exactly what it did: L1-04 had
    just re-pointed the slippage instrument at ``decision_close``, no trade row carried one yet, and the
    top line of the report said OK while M-Q08 - one of the demo phase's two success criteria - had zero
    usable fills.  ``BLIND`` is not a lesser ALERT; it says the question was not answered.

    A breach still outranks a blind metric, and BLIND deliberately does not page: it clears itself once
    the readings arrive, which is the "unactionable standing fact" ``daily_alerts`` keeps as a notice.
    """
    drawdown = drawdown_state(rows, params)
    # Both rulers, side by side, because the gap between them IS the reading: on 2026-09-09 the equity
    # path was 1.30% below its mark and the attributed path 0.23%, a factor of 5.6 on the same record.
    # R8 acts on the second one; this block is where a reader can see why that choice is not cosmetic.
    attributed = attributed_drawdown_state(rows, attribution, params)
    # The third, added 2026-09-20 by the ruling in `usdt_drawdown_state`.  Deliberately NOT added to
    # `unreadable` below: that list drives BLIND, which says a GATE could not be answered, and this
    # metric gates nothing.  Letting a reporting-only reading turn the whole block BLIND would make the
    # status mean "something here is unreadable" instead of "a threshold went unchecked", which is the
    # same erosion in the other direction - a status that fires on things nobody acts on gets ignored
    # on the day it fires on something somebody must.
    tradable = usdt_drawdown_state(rows, params)
    volatility = realised_vol(rows, params)
    slippage = slippage_bps(trades, params, latest_ms=_latest_ms(rows), books_at=books_by_bar(rows))
    guards = guard_firings(rows, params)
    reasons: list[str] = []
    if attributed["enforced"] and attributed["action"]:
        reasons.append(f"归因回撤 {attributed['value']:.1%}（R8 口径），已执行：{attributed['action']}")
    if drawdown["action"]:
        # Kept as a reason but named for what it is: this one is a notice, R8 does not act on it.
        reasons.append(f"权益自高水位回撤 {drawdown['value']:.1%}（含抵押品重估，R8 不据此动作）")
    if volatility["enforced"] and not volatility["inside"]:
        low, high = volatility["band"]
        reasons.append(f"实现波动率 {volatility['value']:.1%} 已跑出 {low:.0%}-{high:.0%} 区间")
    if slippage["enforced"] and not slippage["inside"]:
        # The breach, its error bar and its split, in the line that pages.  Quoting the point estimate
        # alone is how "5.5 > 4" read as a finding for two days while it sat 0.57 SE from the bar and
        # the main book - the one M-Q08 was written about - filled at 0.80.
        detail = ""
        if slippage.get("se"):
            detail = f"（±{slippage['se']:.1f}，{'可分辨' if slippage.get('decisive') else '与噪声不可分辨'}）"
        split = "；".join(
            f"{SPLIT_LABELS.get(name, name)} {group['value']:.1f} bps/{group['fills']} 笔"
            for name, group in (slippage.get("by_group") or {}).items()
            if group.get("value") is not None
        )
        reasons.append(
            f"滑点（{'主书' if slippage.get('judged') == 'main_only' else '全书合并'}）"
            f"{slippage['value']:.1f} bps 高于假设的 {slippage['limit']:.0f} bps{detail}"
            + (f"；分书读：{split}" if split else "")
        )
    unreadable = [
        {"metric": name, "why": str(block.get("why", ""))}
        for name, block in (("realised_vol", volatility), ("slippage", slippage))
        if not block["enforced"]
    ]
    return {
        "status": "ALERT" if reasons else ("BLIND" if unreadable else "OK"),
        "reasons": reasons,
        "unreadable": unreadable,
        "drawdown": drawdown,
        "attributed_drawdown": attributed,
        "usdt_drawdown": tradable,
        "realised_vol": volatility,
        "slippage": slippage,
        "guards": guards,
    }


__all__ = [
    "ACCOUNT_MISLEADS_ABOVE",
    "RiskBudgetParams",
    "attributed_drawdown_state",
    "books_by_symbol",
    "collateral_drift",
    "drawdown_state",
    "guard_firings",
    "one_row_per_order",
    "realised_vol",
    "risk_budget_status",
    "slippage_bps",
    "usdt_drawdown_state",
]
