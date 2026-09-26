"""§3's three limits beside D-018's six checks: slippage stress, correlation, turnover.

`lifecycle.Facts` has read four fields at `validated -> booked` since Phase 0, and only the first of
them - `book_checks_pass` - ever came off an artefact.  The other three were set to their passing
values in `replay.py` and listed as suspended, because **no book report carried them**: `slippage_stress`
appeared in seven validation reports and zero book reports, and correlation and turnover had no field
at all - `research correlate` wrote its own report with nothing linking it back to a book.  Three of
the four conditions on the transition were therefore decided by a literal `True` in the replay.

The arithmetic is here rather than in the CLI for two reasons.  It is pure - series in, numbers out -
so each of the three can be tested against a hand-built panel instead of against a two-hour book run;
and a limit that decides a promotion belongs beside the rules it serves rather than inside the command
that happens to print it.

**The definitions are the ones already pre-registered**, not new ones.  Every pre-registration in
`docs/RESEARCH_LOG.md` that names these limits (P27 缠论, P28's carry/xsmom arms, the funding family)
states them the same way: correlation of the candidate's NET RETURN STREAM against each running book,
signed and one-sided; and turnover as the ratio of `turnover_units` measured on the candidate ALONE,
unscaled, against the main book on the same bars ("换手 ≤ 3× tsmom（tsmom 今天 415.2 单位）").
Implementing a different normalisation - even a stricter one - would mean the artefact reports a
number the operator has never judged against, so the stricter reading is reported BESIDE the gated one
(`turnover_per_gross_ratio`) and gates nothing.  See `turnover_ratio_to_main`.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pandas as pd

#: The level §3 names.  It is not the model's assumption (2.0 bps) but the one the venue delivered:
#: 101 filled demo orders, notional-weighted 5.52 bps (`config/costs.yaml`).  A book is admitted on a
#: marginal contribution priced at 2.0; this asks whether that contribution survives being priced at
#: what the fills actually cost.
DECISION_SLIPPAGE_BPS = 5.5


def _drawdown(net: pd.Series) -> float:
    equity = (1.0 + net).cumprod()
    return float((equity / equity.cummax() - 1.0).min())


def _equal_risk_worsening(total_oos: pd.Series, main_oos: pd.Series) -> float | None:
    """The total book's drawdown cost after it is scaled back to the main book's volatility.

    Operator ruling 2026-09-14 (Q3).  D-018 subtracts the main book's out-of-sample drawdown from the
    total book's, and those two books do not carry the same risk: adding a stream correlated 0.236 took
    the 2026-09-07 book from 32.24% vol to 35.66%, +10.6%.  Any sleeve that can add Sharpe adds vol and
    therefore adds drawdown, so the 1pp allowance was being charged against a bigger book than the one
    it was written for - the part of the cost that is SCALE rather than the sleeve.

    Scaling the returns and recomputing, rather than scaling the drawdown itself: a drawdown is a path
    statistic and multiplying it by a vol ratio is an approximation.  The two agree to a few basis
    points on the 2026-09-07 numbers, and this one needs no caveat.
    """
    main_vol, total_vol = float(main_oos.std()), float(total_oos.std())
    if not (main_vol > 0.0 and total_vol > 0.0):
        return None
    scaled = total_oos * (main_vol / total_vol)
    return _drawdown(main_oos) - _drawdown(scaled)


def marginal_metrics(
    total: Mapping[str, Any],
    main: Mapping[str, Any],
    *,
    total_oos: pd.Series | None = None,
    main_oos: pd.Series | None = None,
) -> dict[str, Any]:
    """D-018's marginal block: what the sleeve adds to the main book, fold by fold.

    Both mappings are `_fold_metrics`-shaped (full/oos Sharpe, oos MDD, oos return, fold Sharpes) and
    must come from the same fold list, or the per-fold deltas are between different periods.

    The two streams are optional, and when they are given the block also carries
    `oos_mdd_worsening_equal_risk` (Q3).  Optional on purpose: it is what makes the ruling apply to
    later candidates only, structurally rather than by a date.  An archived report has no such field,
    `marginal_checks` therefore judges it on the raw difference exactly as before, and no verdict in the
    archive moves.  The raw difference is kept beside the new number rather than replaced - a ruling
    that deletes its own evidence cannot be argued with afterwards.
    """
    deltas = [
        None if t is None or m is None else t - m
        for t, m in zip(total["fold_sharpes"], main["fold_sharpes"], strict=True)
    ]
    wins = [d for d in deltas if d is not None]
    main_sharpe, total_sharpe = main["oos_sharpe"], total["oos_sharpe"]
    block: dict[str, Any] = {
        "delta_full_sharpe": (
            None
            if total["full_sharpe"] is None or main["full_sharpe"] is None
            else total["full_sharpe"] - main["full_sharpe"]
        ),
        "delta_oos_sharpe": (None if total_sharpe is None or main_sharpe is None else total_sharpe - main_sharpe),
        "oos_mdd_worsening": main["oos_mdd"] - total["oos_mdd"],
        "delta_oos_return": total["oos_return"] - main["oos_return"],
        "fold_deltas": deltas,
        "fold_win_rate": float(sum(d > 0 for d in wins) / len(wins)) if wins else None,
    }
    if total_oos is not None and main_oos is not None:
        equal_risk = _equal_risk_worsening(total_oos, main_oos)
        if equal_risk is not None:
            block["oos_mdd_worsening_equal_risk"] = equal_risk
    return block


def marginal_checks(marginal: Mapping[str, Any], rule: Mapping[str, float]) -> dict[str, bool]:
    """The three D-018 checks that read the marginal block, applied at whatever cost it was priced at.

    Shared between the report's own `checks` and the slippage stress precisely so the stress cannot
    quietly use a different bar than the decision it is stressing.
    """
    delta = marginal.get("delta_oos_sharpe")
    win = marginal.get("fold_win_rate")
    return {
        "delta_oos_sharpe": delta is not None and delta >= rule["min_delta_oos_sharpe"],
        # Q3: the equal-risk number when the report carries one, the raw difference when it does not.
        # That fallback IS "later candidates only" - an archived report has no such field and is judged
        # exactly as it was, with no date to remember and no migration to run.
        "oos_mdd_worsening": (
            marginal.get("oos_mdd_worsening_equal_risk", marginal["oos_mdd_worsening"]) <= rule["max_oos_mdd_worsening"]
        ),
        "fold_win_rate": win is not None and win >= rule["min_fold_win_rate"],
    }


def slippage_stress_decision(
    by_level: Mapping[float, Mapping[str, Any]],
    rule: Mapping[str, float],
    *,
    level: float = DECISION_SLIPPAGE_BPS,
) -> dict[str, Any]:
    """`Facts.slippage_stress_pass`: D-018's marginal checks, re-priced at the measured slippage.

    Why the MARGINAL checks and not the sleeve's own Sharpe.  D-018 already stresses the sleeve alone
    at doubled cost (14.0 bps against this level's 10.5), and cost enters the net stream monotonically,
    so a sleeve-Sharpe bar at 5.5 bps could never bite after `cost_x2` passed - it would be a condition
    that reads as a gate and refuses nothing.  What D-018 never priced at the venue's slippage is the
    REASON to book: the marginal contribution over the main book.  That is what this asks, at exactly
    D-018's own three thresholds, so the stress invents no number of its own.

    ``pass`` is None - not False - when `costs.yaml` declares no such level: an artefact that could not
    ask the question must be suspended by its reader, not read as an answer.
    """
    marginal = by_level.get(level)
    if marginal is None:
        return {
            "decision_slippage_bps": level,
            "checks": {},
            "pass": None,
            "reasons": [f"costs.yaml declares no {level:g} bps slippage level, so the 5.5 gate was not evaluated"],
        }
    checks = marginal_checks(marginal, rule)
    failed = [name for name, ok in checks.items() if not ok]
    return {"decision_slippage_bps": level, "checks": checks, "pass": not failed, "reasons": failed}


def correlations_with_running(sleeve_net: pd.Series, running: Mapping[str, pd.Series]) -> dict[str, float | None]:
    """Correlation of the candidate's net stream with each running book's, on their common bars.

    Signed, not absolute: §3's condition is one-sided (`< 0.5`) and a sleeve at -0.9 to a running book
    is the diversifier the rule is trying to find, not a violation of it.  `None` for a pair with fewer
    than two overlapping bars or a constant stream, so "cannot be measured" stays distinct from 0.0.
    """
    out: dict[str, float | None] = {}
    for name, other in running.items():
        aligned = pd.concat([sleeve_net, other], axis=1, join="inner").dropna()
        left, right = aligned.iloc[:, 0], aligned.iloc[:, 1]
        if len(aligned) < 2 or left.std() == 0 or right.std() == 0:
            out[name] = None  # a flat stream correlates with nothing; asking pandas returns NaN and a warning
            continue
        value = left.corr(right)
        out[name] = None if pd.isna(value) else float(value)
    return out


def max_correlation(correlations: Mapping[str, float | None]) -> float | None:
    """The worst of them, or None when nothing measurable was compared.

    None rather than 0.0 for an empty set.  0.0 is the passing value and would turn "there was nothing
    to compare against" into "it correlates with nothing", which is the fail-open this whole block
    exists to remove: the reader suspends the condition instead.
    """
    measured = [value for value in correlations.values() if value is not None]
    return max(measured) if measured else None


def turnover_per_gross(summary: Mapping[str, Any]) -> float | None:
    """Share of a book's own gross notional replaced per bar - the scale-free reading.

    Reported, never gated.  It is invariant to `--fraction` (halving a sleeve halves both its turnover
    and its exposure) and to how hard a book is vol-targeted, which is what makes it comparable between
    two books of different sizes; the gated ratio below is not, and the difference between them is
    worth having in the artefact.  On `book-tsmom-flow-20260908T105322Z` the two disagree by a factor
    of 3.7 in the direction that matters - 0.56x on units against 2.04x per unit of gross.
    """
    bars = summary.get("bars")
    gross = summary.get("average_absolute_exposure")
    units = summary.get("turnover_units")
    if not bars or not gross or units is None:
        return None
    return float(units) / float(bars) / float(gross)


def turnover_ratio_to_main(sleeve: Mapping[str, Any], main: Mapping[str, Any]) -> float | None:
    """`Facts.turnover_ratio_to_main`: the candidate's turnover units over the main book's.

    The candidate is measured ALONE and UNSCALED.  Scaling by `--fraction` would make the ratio a
    statement about the portfolio decision rather than about the strategy, and it would make the limit
    trivial: at 1/3 of the main risk budget a sleeve would have to trade nine times as fast as the main
    book to reach 3x.  Every pre-registration that has ever cited this limit compares the standalone
    number ("旧值 612.6 / 276.6，对 415.2 是 1.5× / 0.7×"), so this is the number the operator has been
    judging against and not a new definition of it.
    """
    numerator = sleeve.get("turnover_units")
    denominator = main.get("turnover_units")
    if numerator is None or not denominator:
        return None
    return float(numerator) / float(denominator)


__all__ = [
    "DECISION_SLIPPAGE_BPS",
    "correlations_with_running",
    "marginal_checks",
    "marginal_metrics",
    "max_correlation",
    "slippage_stress_decision",
    "turnover_per_gross",
    "turnover_ratio_to_main",
]
