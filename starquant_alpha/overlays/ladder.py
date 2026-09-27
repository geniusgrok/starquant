"""R8's de-escalation ladder, as a pure state machine (D-035 / D-036).

The ladder that trades lived entirely inside `LiveEngine._risk_ladder`: an `async` private method
reading `self.store`, `self.state`, `self.config` and `self.alerts`, so nothing could evaluate it
without an engine.  Everything else that needed to know what it does therefore rewrote it.  By
2026-09-14 there were four hand-written replays in `scratchpad/` (`p32b`, `p32c`, `p32d`, `p32e`), a
second unread copy of the rung comparison in `risk_budget.attributed_drawdown_state`, and no twin at
all in `starquant_alpha` - and the replays had already drifted from the engine: one omits the
`min(1.0, raw)` clamp, one divides by a module constant rather than the running target, none replays
the blind-reading hold.

That matters beyond tidiness because those replays produced numbers that were then written down.
D-035 cites 20.5pp of CAGR, a 0.4pp rescaling cost and q95 -66.5% from code that provably is not the
code that runs.  D-036 already requires that a book-level guard have ONE semantics which the backtest
replays - satisfied for `daily_loss_pause` and `GROSS_CAPPED` through `exposure.py`, and not for the
ladder, which is the much larger scalar.

So the rule lives here, in `starquant_alpha`, next to the guards that made the same journey: pure, total,
and importing nothing from `starquant_*` so the backtest may use it.  `Policy` keeps the NUMBERS (R10:
thresholds live in code, behind `policy_digest`) and delegates the rule; the engine keeps the I/O it
needs - reading the record, persisting the standing rung, paging the operator - and holds no branch of
its own.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

#: A rung: the attributed drawdown at which it applies (negative), and the ABSOLUTE vol target it asks
#: for.  Absolute rather than a multiplier because that is what the operator declares and what D-035's
#: derivation produces; turning it into a scalar is this module's job and is where the clamp lives.
Rung = tuple[float, float]


def rung_target(drawdown: float, rungs: Sequence[Rung]) -> float | None:
    """The vol target the ladder asks for at this drawdown, or None above the first rung.

    `drawdown` is negative.  Rungs are checked deepest-first so -0.60 gets 0.15, not 0.225.
    """
    for level, target in sorted(rungs, key=lambda rung: rung[0]):
        if drawdown <= level:
            return target
    return None


def rung_scalar(target: float, base: float) -> tuple[float, bool]:
    """The multiplier that carries `base` to `target`, and whether the rung sat above `base`.

    A de-escalation ladder must never ADD size.  `rung_target` returns an absolute vol target, so rungs
    calibrated for a larger k return a scalar above 1 at a smaller one - an amplifier wearing a brake's
    name, firing exactly when the book is already down.  Latent since R8 was wired (0.225 against
    k=0.15 is 1.5x) and surfaced on 2026-09-14 when re-deriving the rungs for k=0.60 made their
    dependence on a k explicit.

    Clamped rather than raised: a rung that asks for more than the book already runs is a
    mis-calibration to report, not a reason to stop the cycle.  The second return value is that report.
    """
    raw = float(target) / base if base > 0 else 1.0
    return min(1.0, raw), raw > 1.0


@dataclass(frozen=True)
class LadderStep:
    """One evaluation: what to record, what to persist, and what to say.

    Separated so the caller performs the effects and this module decides them.  `standing` is the new
    value for the persisted rung - `None` means leave it untouched, which is not the same as `{}`,
    the explicit clear when the book climbs back above the first rung.
    """

    block: dict[str, Any]
    standing: dict[str, Any] | None = None
    alerts: tuple[str, ...] = ()
    warnings: tuple[str, ...] = field(default_factory=tuple)


def ladder_step(
    *,
    reading: Mapping[str, Any],
    standing: Mapping[str, Any],
    base: float,
    rungs: Sequence[Rung],
    grace_cycles: int,
    bar_open_ms: int,
    now: str,
) -> LadderStep:
    """Evaluate R8 for one cycle.

    `reading` is `risk_budget.attributed_drawdown_state`'s output; `standing` is the rung persisted
    from last cycle (`{}` when none).  Nothing here reads a clock, a file or a venue: `now` is passed
    in so a replay can produce the same row as the run it is reproducing.
    """
    block: dict[str, Any] = {
        # Read off the reading rather than asserted here: after 2026-09-14 the ruler carries the book's
        # unrealised P&L whenever the cycles it reads recorded it, and a label hardcoded here would keep
        # saying `attributed_pnl` through the change.
        "ruler": reading.get("ruler", "attributed_pnl"),
        "marked_rows": reading.get("marked_rows"),
        # The drift between this reading's pinned denominator and the equity the positions are sized
        # off (see `attributed_drawdown_state`).  Carried per cycle rather than recomputed later, for
        # the same reason `asset_vol` is: recomputing it from the archive answers a question about a
        # different bar.
        "equity_over_peak": reading.get("equity_over_peak"),
        "enforced": bool(reading.get("enforced")),
        "drawdown": reading.get("value"),
        "attributed": reading.get("attributed"),
        "base_vol_target": base,
        "grace_cycles": grace_cycles,
        "scalar": 1.0,
        "acting": False,
    }

    if not reading.get("enforced"):
        # A blind reading does not lift a breach that is already standing: "cannot compute" is not
        # "recovered".  It also cannot start one.
        block["why"] = reading.get("why")
        if standing.get("acting"):
            block.update(
                {
                    "scalar": float(standing["scalar"]),
                    "acting": True,
                    "vol_target": float(standing["vol_target"]),
                    "cycles": int(standing.get("cycles", 0)),
                    "held_blind": True,
                }
            )
        return LadderStep(block=block)

    drawdown = float(reading["value"])
    target = rung_target(drawdown, rungs)
    if target is None:
        if standing:
            return LadderStep(
                block=block,
                standing={},
                alerts=(f"StarQuant：归因回撤回到 {drawdown:.2%}，已在 R8 梯的第一档之上——vol_target 恢复 {base}",),
                warnings=(f"risk ladder cleared at attributed drawdown {drawdown:.4f}",),
            )
        return LadderStep(block=block)

    cycles = int(standing.get("cycles", 0)) + 1
    scalar, rung_above_base = rung_scalar(target, base)
    acting = cycles > grace_cycles
    fresh = {
        "cycles": cycles,
        "rung": target,
        "vol_target": target,
        "scalar": scalar,
        # True means the rung sits ABOVE the running vol_target, so the ladder asked for no cut at all.
        # Reported so a mis-calibrated ladder reads as mis-calibrated instead of as quiet.
        "rung_above_base": rung_above_base,
        "acting": acting,
        "drawdown": drawdown,
        "since_bar_ms": int(standing.get("since_bar_ms") or bar_open_ms),
        "at": now,
    }
    block.update({"cycles": cycles, "rung": target, "vol_target": target})

    alerts: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    if acting:
        block.update({"scalar": scalar, "acting": True})
        if not standing.get("acting") or standing.get("rung") != target:
            warnings = (f"risk ladder acting: vol_target -> {target} (scalar {scalar:.4f})",)
            alerts = (
                f"StarQuant：归因回撤 {drawdown:.2%} 连续 {cycles} 个周期在 R8 梯上，"
                f"vol_target {base} → {target}（scalar {scalar:.4f}）已生效",
            )
    elif cycles == 1:
        warnings = (f"risk ladder first crossing at attributed drawdown {drawdown:.4f}",)
        alerts = (
            f"StarQuant：归因回撤 {drawdown:.2%} 触及 R8 梯（vol_target → {target}）。"
            f"按 {grace_cycles} 周期宽限，本周期**不缩仓**",
        )

    return LadderStep(block=block, standing=fresh, alerts=alerts, warnings=warnings)
