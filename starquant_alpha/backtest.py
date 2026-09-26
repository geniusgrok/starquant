"""Vectorised, causal backtest.

Weights are decided at bar ``t`` from information through bar ``t`` and
executed at bar ``t+1``.  Two return conventions:

* ``open_to_close`` (default, matches the frozen August 2026 baseline):
  PnL_{t+1} = w_t * (close_{t+1} / open_{t+1} - 1).  The gap from close_t to
  open_{t+1} is excluded symmetrically for strategy and benchmark.  This is
  conservative about the entry price - a fill at the next open is later, and
  therefore harder to get, than the close the decision was made on - and it is
  **not about the holding return**, where the same exclusion silently drops a
  real component of a position held across the boundary.  Measured on the
  point-in-time book (2026-09-08 audit): the gap carries 2.36% of total
  absolute price movement, and re-earning it by scoring the same weights
  ``close_to_close`` moves OOS Sharpe by -0.029, so what is dropped is mildly
  ADVERSE to this book rather than in its favour.  ``validate`` prices both
  conventions and records the comparison; the default is kept for continuity,
  not because the omission is free.
* ``close_to_close``: PnL_{t+1} = w_t * (close_{t+1} / close_t - 1), i.e. fills
  at the decision close.

Costs charged on the execution bar: ``turnover_bps`` per unit of |Δw|,
``carry_bps_per_bar`` per unit of |w| (flat adverse carry, legacy diagnostic)
and, when ``use_funding``, the actual settled funding ``w * rate`` (longs pay
positive funding).

When ``guards`` replays the book, it also reports a margin buffer: post-bar equity
over the maintenance requirement ``gross * maintenance_margin_rate``, so 1.0 is the
liquidation line.  It is an instrument, not a guard - nothing reads it back into the
book.  Its limit is the same continuous-rebalancing assumption the replay already
makes: the book is a fraction of *current* equity and returns are close-to-close, so
the buffer cannot see an intra-bar path that liquidates and recovers inside one bar.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import numpy as np
import pandas as pd

from starquant_alpha.overlays.exposure import BookGuardParams, clamp_book, hold_or_reduce
from starquant_alpha.panel import Panel
from starquant_alpha.validation.metrics import summarize_returns

Execution = Literal["open_to_close", "close_to_close"]


@dataclass(frozen=True)
class CostModel:
    turnover_bps: float = 7.0
    carry_bps_per_bar: float = 0.0
    use_funding: bool = False

    def __post_init__(self) -> None:
        if self.turnover_bps < 0 or self.carry_bps_per_bar < 0:
            raise ValueError("cost parameters must be non-negative")


@dataclass(frozen=True)
class ImpactModel:
    """KILL-A / DL-C1: the cost of an order that is large relative to what trades.

    Everything else in this module is scale-free, and that is an arithmetic property rather than a
    finding: gross P&L, turnover cost and funding are all linear in the weights, so scaling every
    weight by k leaves the Sharpe exactly unchanged (measured on k in {1, 1.5, 2, 2.5, 3, 4, 5}:
    identical to the last digit).  The flat 7 bps charges the same for a 40 USDT order and a 4M one.
    That is a good approximation at demo notional and it is the assumption that fails with real money,
    which is why KILL-Q12 has held real capital out of scope since 2026-09-05.

    The square-root law is the standard first model: the price paid moves as the square root of the
    fraction of daily volume the order takes, scaled by the asset's own volatility.

        impact_fraction = coefficient * sigma_daily * sqrt(order_notional / ADV)

    **The coefficient is an assumption, not a measurement, and it cannot be calibrated here.**  The
    only fills this system has are demo, 54-762 USDT.  Measured per fill over all 121 of them
    (2026-09-09, `scratchpad/vwap_participation_measurement.py`), order/ADV is 4.3e-07 at the median
    and the model predicts 0.48 bps notional-weighted - small, but two orders of magnitude above the
    1e-8 / "hundredth of a basis point" this docstring asserted until then.  That figure was DL-C1's
    pre-run estimate, taken from the liquid names' ADV rather than the book's; DL-C1's own run
    retracted it and the retraction did not reach here.  The conclusion survives the correction and
    the reason changes: 0.48 bps sits inside the [2.01, 9.19] bps interval of the same fills' measured
    slippage, so impact is not too small to matter, it is too small to SEPARATE from spread.  A number
    from the equities literature (Almgren et al.; coefficient near 1 with sigma daily and
    participation as defined above) is therefore what ships, declared E5 for this venue, and the
    honest output of this model is a **capacity curve** - where cost starts to bend - rather than a
    prediction of what a fill will cost.

    ``capital`` of 0 turns it off exactly: sqrt(0) is 0, so the flat model is this model's own limit
    rather than a separate branch, which is what makes every archived report still reproducible.
    """

    capital: float = 0.0  # USDT the book runs; 0 means the flat, scale-free model
    coefficient: float = 1.0
    adv_window: int = 720  # bars of trailing quote volume (30 days hourly)
    vol_window: int = 720

    def __post_init__(self) -> None:
        if self.capital < 0 or self.coefficient < 0:
            raise ValueError("impact parameters must be non-negative")

    @property
    def enabled(self) -> bool:
        return self.capital > 0.0 and self.coefficient > 0.0


def impact_costs(
    turnover: pd.DataFrame, rets: pd.DataFrame, panel: Panel, columns: list[str], model: ImpactModel
) -> pd.DataFrame:
    """Per-symbol impact, in book units, charged on top of the flat per-unit cost.

    Both inputs are taken as of the bar BEFORE execution: the trailing volume mean and the trailing
    return standard deviation are shifted, so nothing here reads a bar the decision could not have.
    """
    if not model.enabled:
        return turnover * 0.0
    bars_per_day = max(1.0, panel.bars_per_year / 365.0)
    adv = (average_quote_volume(panel, columns, model.adv_window) * bars_per_day).shift(1).reindex(turnover.index)
    sigma_daily = rets.rolling(model.vol_window, min_periods=model.vol_window // 4).std().shift(1) * np.sqrt(
        bars_per_day
    )
    participation = (turnover * model.capital).div(adv).replace([np.inf, -np.inf], np.nan).fillna(0.0).clip(lower=0.0)
    charged = turnover * model.coefficient * sigma_daily.fillna(0.0) * np.sqrt(participation)
    return pd.DataFrame(charged, index=turnover.index, columns=turnover.columns)


@dataclass(frozen=True)
class ParticipationModel:
    """The live participation cap (T-S03), measured but never applied.

    ``starquant_live.rebalancer.plan_rebalance`` truncates any non-closing order above
    ``max_participation * average quote volume``.  The backtest does not apply it - re-deriving the
    vol-target k under an impact-aware cost model is recorded as out of scope in
    ``config/live.demo.yaml`` - so this reports how much of the target turnover live would have
    refused, and changes nothing about the book that is scored.

    ``capital`` exists because the cap is the first thing here that is not scale-free: weights, costs
    and funding are all fractions of equity, while the cap is an absolute notional.

    ``exempt_reductions`` must be flipped together with ``starquant_live.rebalancer.RebalanceParams``.
    This replay is only an instrument for the live cap while both halves encode the same rule; flipping
    one alone makes the measurement describe a loop that does not exist - KILL-027's shape.
    """

    capital: float
    max_participation: float
    window: int = 24  # bars averaged, matching `LiveEngine.liquidity_window`
    # False = today's scope (only a full close escapes the cap), matching `plan_rebalance`'s `closing`.
    # True = every reduce-only row escapes it, matching `plan_rebalance`'s `reduce_only`.
    exempt_reductions: bool = False

    def __post_init__(self) -> None:
        if self.capital <= 0:
            raise ValueError("capital must be positive")
        if self.max_participation <= 0:
            raise ValueError("max_participation must be positive")
        if self.window < 1:
            raise ValueError("window must be at least one bar")


def average_quote_volume(panel: Panel, columns: list[str], window: int) -> pd.DataFrame:
    """Trailing mean quote volume per bar, the same quantity ``LiveEngine._liquidity`` sends live."""
    source = panel.quote_volume
    if source is None:
        source = panel.volume * panel.close
    return source[columns].rolling(window, min_periods=1).mean()


@dataclass
class BacktestResult:
    execution: Execution
    weights: pd.DataFrame
    asset_returns: pd.DataFrame
    gross: pd.DataFrame
    costs: pd.DataFrame
    net: pd.DataFrame
    turnover: pd.Series
    bars_per_year: float
    guard_events: pd.DataFrame | None = None

    @property
    def portfolio_gross(self) -> pd.Series:
        return self.gross.sum(axis=1)

    @property
    def portfolio_net(self) -> pd.Series:
        return self.net.sum(axis=1)

    @property
    def equity_curve(self) -> pd.Series:
        return (1.0 + self.portfolio_net).cumprod()

    def summary(self) -> dict[str, Any]:
        out = summarize_returns(self.portfolio_gross, self.portfolio_net, self.weights, self.bars_per_year)
        if self.guard_events is not None:
            out["guards"] = {
                "replayed": True,
                "gross_capped_bars": int(self.guard_events["gross_capped"].sum()),
                "daily_loss_pause_bars": int(self.guard_events["daily_loss_pause"].sum()),
                "bars": len(self.guard_events),
                "min_margin_buffer": float(self.guard_events["margin_buffer"].min()),
                "liquidation_touches": int((self.guard_events["margin_buffer"] <= 1.0).sum()),
            }
            if "refused_notional" in self.guard_events.columns:
                desired = float(self.guard_events["desired_notional"].sum())
                refused = float(self.guard_events["refused_notional"].sum())
                out["guards"]["participation_capped_bars"] = int((self.guard_events["refused_notional"] > 0).sum())
                out["guards"]["refused_turnover_share"] = refused / desired if desired > 0 else 0.0
        return out

    def per_symbol_summary(self) -> dict[str, dict[str, Any]]:
        return {
            str(symbol): summarize_returns(
                self.gross[symbol], self.net[symbol], self.weights[symbol], self.bars_per_year
            )
            for symbol in self.weights.columns
        }


def asset_returns(panel: Panel, execution: Execution) -> pd.DataFrame:
    if execution == "open_to_close":
        return panel.close / panel.open - 1.0
    if execution == "close_to_close":
        return panel.close / panel.close.shift(1) - 1.0
    raise ValueError(f"unknown execution convention {execution!r}")


def run_backtest(
    panel: Panel,
    weights: pd.DataFrame,
    cost: CostModel | None = None,
    execution: Execution = "open_to_close",
    guards: BookGuardParams | None = None,
    maintenance_margin_rate: float = 0.005,
    participation: ParticipationModel | None = None,
    impact: ImpactModel | None = None,
) -> BacktestResult:
    """``weights``: decision-time target weights (fraction of equity), index = decision bars.

    ``guards`` replays the two book-level guards the live loop applies after the model and before
    the rebalancer (D-004).  Leave it None for the historical path; pass it to score the book the
    loop would actually hold.  The replay is causal and path dependent - the daily-loss pause reads
    the equity this same replay produced - so it cannot be vectorised.

    It is a no-op only when neither guard binds, and on the book that is actually shipped they both
    do.  This sentence used to read "the shipped book at ``vol_target 0.15``: zero pauses in 5.6
    years", and that book stopped being the shipped one when the target moved to 0.60: measured on
    ``tsmom-validation-20260913T182325Z.json``, the report the live registry cites, 491 of 49,240
    bars pause on the daily loss and 4,070 (8.3%) are gross-capped.  A "no-op" the reader carries
    forward from this docstring is therefore a claim about a book four times smaller than the one in
    front of them, and the replay's own path dependence is what makes the difference impossible to
    read off a scaled number.
    """
    cost = cost or CostModel()
    columns = [symbol for symbol in weights.columns if symbol in panel.close.columns]
    decided = weights[columns].reindex(panel.close.index)
    first_valid = decided.dropna(how="all").index.min() if decided.notna().any().any() else None
    if first_valid is None:
        raise ValueError("weights contain no valid decisions")
    executed = decided.shift(1).loc[first_valid:].iloc[1:].fillna(0.0)
    if executed.empty:
        raise ValueError("no execution bars after the first decision")
    rets = asset_returns(panel, execution)[columns].reindex(executed.index).fillna(0.0)
    funding = (
        panel.funding[columns].reindex(executed.index).fillna(0.0)
        if cost.use_funding and panel.funding is not None
        else None
    )
    guard_events: pd.DataFrame | None = None
    if guards is not None:
        decision_times = pd.DatetimeIndex(panel.close.index[panel.close.index.get_indexer(executed.index) - 1])
        liquidity = (
            average_quote_volume(panel, columns, participation.window).reindex(decision_times).to_numpy(dtype=float)
            if participation is not None
            else None
        )
        executed, guard_events = _replay_book_guards(
            executed, decision_times, rets, funding, cost, guards, maintenance_margin_rate, participation, liquidity
        )
    gross = executed * rets
    delta = executed.diff()
    delta.iloc[0] = executed.iloc[0]
    turnover = delta.abs()
    costs = turnover * (cost.turnover_bps / 10_000.0) + executed.abs() * (cost.carry_bps_per_bar / 10_000.0)
    if impact is not None and impact.enabled:
        # Stated limit: the guard replay above priced its own equity path at the flat rate, so a
        # daily-loss pause is decided without impact.  At demo notional impact is under 0.01 bps and the
        # difference is unmeasurable; at the capital where this model bends, the pause would fire
        # slightly earlier than replayed here.  Recorded rather than fixed, because moving impact inside
        # the replay makes it path dependent on a quantity the replay is itself producing.
        costs = costs + impact_costs(turnover, rets, panel, columns, impact)
    if funding is not None:
        costs = costs + executed * funding
    net = gross - costs
    return BacktestResult(
        execution=execution,
        weights=executed,
        asset_returns=rets,
        gross=gross,
        costs=costs,
        net=net,
        turnover=turnover.sum(axis=1),
        bars_per_year=panel.bars_per_year,
        guard_events=guard_events,
    )


def _replay_book_guards(
    executed: pd.DataFrame,
    decision_times: pd.DatetimeIndex,
    rets: pd.DataFrame,
    funding: pd.DataFrame | None,
    cost: CostModel,
    params: BookGuardParams,
    maintenance_margin_rate: float,
    participation: ParticipationModel | None = None,
    liquidity: np.ndarray | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Bar-by-bar replay of the caps and the daily-loss pause on the equity path they themselves produce.

    ``decision_times`` are the bars the weights were decided on, not the bars they execute on: the live
    loop rolls ``day_start_equity`` on the decision bar, and at an hourly interval the two straddle UTC
    midnight once a day.  Equity entering iteration ``t`` is the equity through the decision bar, which
    is what ``Snapshot.equity`` reports to ``evaluate_guards``.  The one approximation against live: the
    held row here is the previous target rather than the venue position drifted by price, which is the
    continuous-rebalancing assumption the rest of this module already makes.
    """
    values = executed.to_numpy(dtype=float)
    returns = rets.to_numpy(dtype=float)
    fees = None if funding is None else funding.to_numpy(dtype=float)
    turnover_rate = cost.turnover_bps / 10_000.0
    carry_rate = cost.carry_bps_per_bar / 10_000.0
    out = np.empty_like(values)
    capped = np.zeros(len(values), dtype=bool)
    paused = np.zeros(len(values), dtype=bool)
    buffers = np.full(len(values), np.inf)
    desired_notional = np.zeros(len(values))
    refused_notional = np.zeros(len(values))
    days = pd.DatetimeIndex(decision_times).normalize().to_numpy()
    held = np.zeros(values.shape[1])
    equity = 1.0
    day_start = 1.0
    day: object = None
    for t in range(len(values)):
        if days[t] != day:
            day = days[t]
            day_start = equity
        row, gross_capped = clamp_book(values[t], params.max_weight, params.max_gross)
        capped[t] = gross_capped
        if day_start > 0 and equity > 0 and equity / day_start - 1.0 < params.daily_loss_pause:
            row = hold_or_reduce(row, held)
            paused[t] = True
        out[t] = row
        realised = float(row @ returns[t])
        charge = float(np.abs(row - held).sum()) * turnover_rate + float(np.abs(row).sum()) * carry_rate
        if fees is not None:
            charge += float(row @ fees[t])
        if participation is not None and liquidity is not None:
            wanted = np.abs(row - held) * participation.capital * equity
            cap = liquidity[t] * participation.max_participation
            # live exempts a full close (`closing`: target 0 while holding) and never caps a symbol
            # whose liquidity is unknown, because `plan_rebalance` requires `cap is not None and cap > 0`
            exempt = ((row == 0.0) & (held != 0.0)) | ~np.isfinite(cap) | (cap <= 0.0)
            if participation.exempt_reductions:
                # The other half of `RebalanceParams.exempt_reductions`, written to the same rule:
                # live's `reduce_only` is `closing` (above) OR `pure_reduction`, and `pure_reduction`
                # is same-side and strictly smaller.  The sign test is `(target > 0) == (current > 0)`
                # there, so it is `(row > 0) == (held > 0)` here - quirk included, since a short being
                # taken to zero satisfies both and is already `closing`.
                same_side = (held != 0.0) & ((row > 0.0) == (held > 0.0))
                exempt = exempt | (same_side & (np.abs(row) < np.abs(held)))
            desired_notional[t] = float(wanted.sum())
            refused_notional[t] = float(np.where(exempt, 0.0, np.maximum(0.0, wanted - cap)).sum())
        maintenance = float(np.abs(row).sum()) * maintenance_margin_rate
        if maintenance > 0.0:
            buffers[t] = (1.0 + realised - charge) / maintenance
        equity *= 1.0 + (realised - charge)
        held = row
    columns: dict[str, np.ndarray] = {
        "gross_capped": capped,
        "daily_loss_pause": paused,
        "margin_buffer": buffers,
    }
    if participation is not None:
        columns["desired_notional"] = desired_notional
        columns["refused_notional"] = refused_notional
    events = pd.DataFrame(columns, index=executed.index)
    return pd.DataFrame(out, index=executed.index, columns=executed.columns), events


def benchmark_returns(
    panel: Panel,
    execution: Execution = "open_to_close",
    symbols: list[str] | None = None,
    membership: pd.DataFrame | None = None,
) -> pd.Series:
    """Equal-weight, always-long, zero-cost comparator (an opportunity-cost benchmark, not investable).

    ``membership`` (bars x symbols, `--universe pit`) keeps each bar to the symbols the book could hold
    at it - the rule the live `pit_benchmark` follows (D-045).  `validate`, `backtest` and `decompose`
    all pass the run's own (None when static).

    Without it every priced column counts, and on a pit panel that is hindsight, not just a wider
    basket: the panel IS every symbol that was ever a member, so at bar t it holds names picked for a
    membership still in their future.  Volume ranks follow price - the 30 days before a symbol's first
    membership return a median +70% - so those names are there because they were about to have run.
    Measured 2026-09-23 (pit, 2021-06..2026-09): not-yet-members are a median 15% of the basket (51% in
    2021) and their pre-entry bars earn an equal-weight Sharpe of +2.32; the basket read Sharpe +0.38
    where the members read -0.10.  D-045's lesson, arriving through selection instead of survival.
    """
    chosen = symbols or panel.symbols
    returns = asset_returns(panel, execution)[chosen]
    if membership is not None:
        returns = returns.where(membership.reindex(index=returns.index, columns=returns.columns, fill_value=False))
    return returns.mean(axis=1)


def benchmark_basket(membership: pd.DataFrame | None) -> str:
    """Which basket `benchmark_returns` averaged, named in every report that prints a benchmark.

    Since 2026-09-23 `research backtest` and `decompose` pass the run's `membership`, as `validate`'s
    regime split already did.  On a pit run that changed the basket and not the key, so a report with
    no `basket` predates it: its benchmark averaged every priced column, hindsight included (see
    `benchmark_returns`).  Five archived pit reports are that shape.
    """
    return "pit members at each bar" if membership is not None else "every panel symbol"
