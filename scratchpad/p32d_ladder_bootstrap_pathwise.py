"""P32d: the q95 of a path-dependent control, replayed INSIDE each bootstrap path - and read by the
ruler the live loop actually uses.

Supersedes `p32c_rescaled_ladder.py`'s `q95_of` for every q95 / P(breach) number.  `p32c` is left
exactly as it ran, because its numbers are what E-010 and C-006 cite and rewriting the evidence under
a claim is how a record stops being one.

TWO defects, found by the 2026-09-14 audit
(`docs/analysis/2026-09-14-backtest-guard-k060-ladder-audit.md`):

1. `p32c.q95_of` block-bootstraps `thr` - a series whose throttle scalars were decided on the
   HISTORICAL ordering.  A draw that reaches -70% would have tripped the ladder far earlier than
   history did, so the shipped ladder's protection is missing from its own tail estimate.  Replaying
   the ladder inside each draw moves the shipped arm's q95 from -70.8% to -52.6% and reverses C-006.

2. Both arms were replayed against the book's mark-to-market NAV.  R8 does not read that.
   `attributed_drawdown_state` (`starquant_live/risk_budget.py:223`) reads `base + cumsum(attributed)` -
   income rows only, no unrealised P&L - so a book holding losers sees a far shallower drawdown than
   the one the operator is watching.  Measured by `p32e`: on this same panel the mark-to-market ruler
   spends 785 bars past the first rung and the realised ruler spends 0.

So the arms below are (ladder) x (ruler).  The drawdown REPORTED is always the mark-to-market one,
because that is the drawdown the operator's budget is about; the ruler only decides when the ladder
acts.

Inherited approximations, unchanged and stated: the scalar multiplies the realised net series rather
than re-deriving the weight path (P32b); the weekly block bootstrap destroys multi-month regime
structure, so every q95 here is OPTIMISTIC (A-003); and the realised/unrealised split is itself path
dependent, so resampling blocks of an already-split series carries each block's split from history.

    python scratchpad/p32d_ladder_bootstrap_pathwise.py pit|static [draws]
"""

from __future__ import annotations

import copy
import json
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, "scratchpad")

from p32e_ruler_divergence import DATA, K, drawdown_path, realised_split

from starquant_alpha.backtest import run_backtest
from starquant_alpha.overlays.exits import ExitParams, apply_exits
from starquant_alpha.overlays.exposure import BookGuardParams
from starquant_alpha.overlays.ladder import ladder_step
from starquant_cli.research_cmd import _load, _membership, _resolve_symbols
from starquant_governance.policy import Policy
from starquant_live.composition import build_model, cost_model, load_registry
from starquant_shared.config import load_yaml

BUDGET, BLOCK, SEED = 0.70, 168, 20260904


def rescaled(k: float, budget: float = BUDGET) -> tuple[tuple[float, float], ...]:
    """The shipped rule transcribed to a declared budget (P32c's E-010), not a new rule.

    `budget` became a parameter on 2026-09-20 so `p32f` can ask the same rule what it produces when the
    budget is declared in tradable USDT.  The default is unchanged and so is every number this file
    prints: the rule was always a function of the budget, it just had only one caller.
    """
    return ((-0.70 * budget, 0.75 * k), (-1.00 * budget, 0.50 * k))


#: The rungs as they stood BEFORE policy 0.3.3 - calibrated at k=0.30 against a 50% budget and left
#: alone when k doubled.  D-035 cites "a measured median 20.5pp of CAGR" for exactly this arm, and
#: neither of the two arms above is it any more: after 0.3.3 re-derived the shipped rungs for -70%,
#: `rescaled(0.60)` and `Policy().drawdown_ladder` are the same ladder, so the run had no way to
#: reproduce the number its own conclusion rests on.  Added 2026-09-15.
UNRESCALED = ((-0.35, 0.225), (-0.50, 0.15))


def ladder_legacy(mark: np.ndarray, realised: np.ndarray, policy: Policy, ruler: str) -> tuple[np.ndarray, np.ndarray]:
    """The hand-written replay this script shipped with, now FROZEN as a reference, not an alternative.

    Three ways it differed from the loop it claimed to replay, found when `ladder_step` was extracted
    from `LiveEngine._risk_ladder` on 2026-09-15:

    * no `min(1.0, raw)` clamp - a rung above the running target became an amplifier;
    * `standing / K` divides by a module constant rather than by the base actually in force;
    * no blind-reading hold, because a backtest reading never fails to compute.

    All three are latent at k=0.60 under the shipped rungs - 0.45/0.60 and 0.30/0.60 are both below 1,
    `K` IS the base this script runs, and a replay always has a reading - so `scalar_drift_vs_legacy`
    measured 0 on every arm of both universes, and D-035's numbers survived the swap unchanged.

    Kept for exactly one job: if someone edits `ladder_step`, the drift column stops being 0 and this
    run says so.  It is not a second implementation to read the ladder from - nothing calls it but the
    comparison - which is the distinction the four `p32*` replays failed to keep.
    """
    equity = hwm = 1.0
    path = peak = 1.0
    cycles, standing = 0, None
    out = np.empty(len(mark))
    scalars = np.ones(len(mark))
    for t in range(len(mark)):
        drawdown = (equity / hwm - 1.0) if ruler == "mtm" else (path / peak - 1.0 if peak > 0 else 0.0)
        rung = policy.throttle_scalar(drawdown)
        if rung is None:
            cycles, standing = 0, None
        else:
            cycles += 1
            standing = rung if cycles > policy.drawdown_grace_cycles else standing
        scalar = (standing / K) if standing is not None else 1.0
        scalars[t] = scalar
        out[t] = scalar * mark[t]
        path += scalar * realised[t] * equity
        equity *= 1.0 + out[t]
        peak = max(peak, path)
        hwm = max(hwm, equity)
    return out, scalars


def ladder(mark: np.ndarray, realised: np.ndarray, policy: Policy, ruler: str) -> tuple[np.ndarray, np.ndarray]:
    """(throttled mark-to-market returns, scalars), stepped by the SHIPPED state machine.

    `starquant_alpha.overlays.ladder.ladder_step` is what `LiveEngine._risk_ladder` runs; calling it here
    is the whole point of having extracted it.  What stays local is everything the backtest has to
    stand in for: the two rulers, the equity and realised paths, and `enforced: True` - a replay always
    has a reading, so the blind-hold branch is unreachable here by construction rather than by
    omission.
    """
    equity = hwm = 1.0
    path = peak = 1.0
    standing: dict = {}
    out = np.empty(len(mark))
    scalars = np.ones(len(mark))
    for t in range(len(mark)):
        drawdown = (equity / hwm - 1.0) if ruler == "mtm" else (path / peak - 1.0 if peak > 0 else 0.0)
        step = ladder_step(
            reading={"enforced": True, "value": drawdown},
            standing=standing,
            base=K,
            rungs=policy.drawdown_ladder,
            grace_cycles=policy.drawdown_grace_cycles,
            bar_open_ms=t,
            now="",
        )
        if step.standing is not None:
            standing = step.standing
        scalar = float(step.block["scalar"])
        scalars[t] = scalar
        out[t] = scalar * mark[t]
        path += scalar * realised[t] * equity
        equity *= 1.0 + out[t]
        peak = max(peak, path)
        hwm = max(hwm, equity)
    return out, scalars


def panel_series(mode: str, k: float = K) -> tuple[np.ndarray, np.ndarray]:
    """(mark-to-market returns, realised returns) for one universe, as every arm below consumes them.

    Extracted from `main` on 2026-09-20 so `p32f` runs the same panel through the same model rather
    than building a second one beside it - the failure this whole `p32*` family is named after.  Pure
    move: `main` calls it and prints what it printed.

    `k` became a parameter the same day for `p32g`, which sweeps it.  The default is the module's `K`
    and nothing this file prints moves, but note what the parameter actually does: it re-runs the whole
    model at that `vol_target`, so the weights, the guards' binding and the costs are all re-derived.
    Scaling the returned series by `k / K` instead would be a different and wrong thing - `max_weight`,
    `max_gross` and the cost model do not scale with the target, so the cheap version would report a
    book that no `vol_target` produces.
    """
    profile = load_yaml("config/live.demo.yaml")
    registry = load_registry(Path("config/alpha_registry.yaml"))
    panel = _load(DATA, _resolve_symbols(DATA, "", "1h", mode), "1h", None, None, True)
    membership = _membership(DATA, mode, panel, 0)
    cost = cost_model(load_yaml("config/costs.yaml"), use_funding=True)
    exits = ExitParams.from_mapping({**(profile.get("exits") or {}), "bars_per_day": 24})
    pf = profile.get("portfolio", {}) or {}
    guards = BookGuardParams(max_weight=float(pf["max_weight"]), max_gross=float(pf["max_gross"]),
                             daily_loss_pause=float(profile["guards"]["daily_loss_pause"]))
    tuned = copy.deepcopy(profile)
    tuned.setdefault("portfolio", {})["vol_target"] = k
    w, _c, _p = build_model(registry, tuned).evaluate(panel, membership)
    w = apply_exits(w, panel.close, exits).weights if exits.enabled else w
    result = run_backtest(panel, w, cost, guards=guards)
    realised, mark = realised_split(
        np.nan_to_num(result.weights.to_numpy(dtype=float), nan=0.0),
        np.nan_to_num(result.asset_returns.to_numpy(dtype=float), nan=0.0),
        np.nan_to_num(result.costs.to_numpy(dtype=float), nan=0.0),
    )
    return mark, realised


def main(mode: str, draws: int) -> None:
    mark, realised = panel_series(mode)
    n = len(mark)
    blocks = n // BLOCK
    years = (blocks * BLOCK) / 8760.0
    # one seed, one set of block starts, reused by every arm and both methods: the comparison is PAIRED
    rng = np.random.default_rng(SEED)
    starts = np.stack([rng.integers(0, n - BLOCK, size=blocks) for _ in range(draws)])
    print(f"[{mode}] k={K} bars={n} blocks/draw={blocks} draws={draws}")
    print(f"{'ladder':>12}{'ruler':>10}{'A q95':>9}{'A P<-50':>9}{'B q95':>9}{'B P<-50':>9}"
          f"{'B CAGR':>9}{'B cost':>9}{'trip%':>8}{'drift':>10}")
    out = []
    # The two arms are the same ladder at k=0.60, and saying so is worth more than printing it twice:
    # `rescaled(0.60)` is ((-0.49, 0.45), (-0.70, 0.30)) and so is `Policy().drawdown_ladder`, because
    # policy 0.3.3 already re-derived the shipped rungs for the -70% budget.  Kept as two arms so the
    # identity is visible in the output rather than asserted here; they differ only in float noise.
    for name, rungs in (
        ("shipped", Policy().drawdown_ladder),
        ("rescaled", tuple(rescaled(K))),
        ("unrescaled", UNRESCALED),
    ):
        policy = replace(Policy(), drawdown_ladder=tuple(rungs))
        for ruler in ("mtm", "realised"):
            thr, sc = ladder(mark, realised, policy, ruler)
            # Paired against the hand-written replay this script used to carry, on the same series.
            _thr_legacy, sc_legacy = ladder_legacy(mark, realised, policy, ruler)
            drift = float(np.abs(sc - sc_legacy).max())
            a = np.array([drawdown_path(np.cumprod(1.0 + np.concatenate([thr[s:s + BLOCK] for s in row]))).min()
                          for row in starts])
            b = np.empty(draws)
            cagr = np.empty(draws)
            raw = np.empty(draws)
            for d, row in enumerate(starts):
                m = np.concatenate([mark[s:s + BLOCK] for s in row])
                r = np.concatenate([realised[s:s + BLOCK] for s in row])
                stepped, _ = ladder(m, r, policy, ruler)
                b[d] = drawdown_path(np.cumprod(1.0 + stepped)).min()
                cagr[d] = np.prod(1.0 + stepped) ** (1.0 / years) - 1.0
                raw[d] = np.prod(1.0 + m) ** (1.0 / years) - 1.0
            row_out = {
                "ladder": name, "ruler": ruler, "rungs": list(map(list, rungs)),
                "A_q95": float(np.percentile(a, 5)), "A_p_breach_50": float((a <= -0.50).mean()),
                "B_q95": float(np.percentile(b, 5)), "B_p_breach_50": float((b <= -0.50).mean()),
                "B_cagr_median": float(np.median(cagr)),
                "B_cagr_cost_median": float(np.median(raw - cagr)),
                "B_cagr_cost_q90": float(np.percentile(raw - cagr, 90)),
                "historical_throttled_share": float((sc < 1.0 - 1e-9).mean()),
                "B_draws_that_ever_tripped": float(np.mean(raw - cagr > 1e-9)),
                # max |scalar_shipped - scalar_legacy| over the historical path.  0 means replacing the
                # hand-written replay with `ladder_step` moved nothing on this panel at this k.
                "scalar_drift_vs_legacy": drift,
            }
            out.append(row_out)
            print(f"{name:>12}{ruler:>10}{row_out['A_q95']:>9.1%}{row_out['A_p_breach_50']:>9.1%}"
                  f"{row_out['B_q95']:>9.1%}{row_out['B_p_breach_50']:>9.1%}"
                  f"{row_out['B_cagr_median']:>9.1%}{row_out['B_cagr_cost_median']:>9.1%}"
                  f"{row_out['B_draws_that_ever_tripped']:>8.1%}{drift:>10.2e}")
    Path(f"scratchpad/p32d-{mode}.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"wrote scratchpad/p32d-{mode}.json")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "pit", int(sys.argv[2]) if len(sys.argv) > 2 else 2000)
