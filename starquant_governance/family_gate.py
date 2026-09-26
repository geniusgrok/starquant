"""R0 recomputed against today's ledger: the `probe -> main` condition §3 named and nothing computed.

§3 gives `probe -> main` three conditions - nine surviving windows, never stopped, and **家族门重算仍过**
- and `probe -> retired` one, which is that same recomputation failing.  The first two were implemented.
The third had no branch in `lifecycle.evaluate` at all, and `Event.FAMILY_GATE_FAILED` had a definition,
a handler, and no producer anywhere in the tree.  Found by the 2026-09-09 audit.

**2026-09-23: what failing does, and who says so.**  The operator ruled that a failed recomputation sends
a main back to probe instead of retiring it, and leaves a probe a probe (`lifecycle.evaluate`).  The
event was still produced by nothing - the 09-19 refusal of tsmom sat in the verdict ledger with no
consequence - so `refusals` now derives it from the `refuse` rows `governance gate` writes, and
`governance advance` folds them.

**What "recompute" means, and why it is not a re-run.**  The D-028 gate is `max_sharpe_quantile(N,
variance, alpha)` - the 95th percentile of the best of N draws from a null with the candidate's own
sampling variance.  Everything in it except N is a property of the evidence and does not change after
the report is written.  N is the strategy's ledger bucket, it is append-only, and it grows every time
anybody searches in that family.  So the gate a strategy passed at adoption is not the gate it faces
today, and the recomputation holds the evidence fixed and moves only the denominator.

That is the whole mechanism, and it is worth stating plainly because it cuts both ways: **searching more
demotes your own incumbents.**  tsmom was adopted against a threshold of 1.4884 at N=148 and faces
1.5136 at N=183 five days later, on the same 1.8087.  The gate rises as sqrt(2 ln N), so it saturates -
that is why the incumbent survives - but a strategy adopted with a thin margin does not get to keep it
by standing still.

**The scale is taken from the report rather than recomputed.**  `threshold_annual` is the raw quantile
times `sqrt(bars_per_year)`, and the report does not store `bars_per_year`.  Backing the scale out of
the stored pair - threshold / quantile(N_at_adoption) - reproduces the adoption threshold exactly by
construction, which is the point: any difference between then and now is then attributable to N and to
nothing else.  A second implementation of the annualisation would put its own arithmetic into a number
whose whole job is to isolate one variable.

**Absent knowledge is False.**  A strategy whose evidence cannot be read does not pass; it is UNREADABLE,
which is a different operator action from FAIL and is reported as such.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from starquant_alpha.panel import bars_per_year
from starquant_alpha.registry import Registry
from starquant_alpha.validation.ledger import ledger_scope, parse_ledger, unique_trials
from starquant_alpha.validation.multiple_testing import SELECTION_GATE, max_sharpe_quantile
from starquant_governance.lifecycle import Event
from starquant_governance.tenure import Derived
from starquant_governance.verdicts import REFUSE, Verdict

PASS = "PASS"
FAIL = "FAIL"
UNREADABLE = "UNREADABLE"
VERDICT_KIND = "family_gate"  # the `kind` `governance gate` records its rulings under, and `refusals` reads


@dataclass(frozen=True)
class GateReading:
    """One strategy's gate, then and now, with everything needed to argue with the verdict."""

    strategy: str
    status: str
    why: str
    oos_sharpe: float | None = None
    n_at_adoption: int | None = None
    threshold_at_adoption: float | None = None
    n_today: int | None = None
    threshold_today: float | None = None

    @property
    def passes(self) -> bool:
        return self.status == PASS

    @property
    def margin(self) -> float | None:
        if self.oos_sharpe is None or self.threshold_today is None:
            return None
        return self.oos_sharpe - self.threshold_today


def _selection(report: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """R0's caliber: the per-strategy bucket, never the whole-library block reported beside it.

    Reading `oos_selection_whole_library` here would be a threshold change wearing a recomputation's
    clothes - the operator ruled the bucket is the gate (R0, KILL-AR-01) and this is not the place to
    revisit that.
    """
    block = report.get("oos_selection")
    return block if isinstance(block, Mapping) else None


def read_gate(
    strategy: str,
    report: Mapping[str, Any],
    ledger_lines: Sequence[str],
    *,
    range_end_granularity_days: int,
) -> GateReading:
    """Recompute one strategy's gate at today's bucket size, holding its evidence fixed."""
    block = _selection(report)
    if block is None:
        return GateReading(strategy, UNREADABLE, "the report carries no `oos_selection` block")
    labelled = block.get("gate")
    if labelled is not None and str(labelled) != SELECTION_GATE:
        # KILL-Q3's leftover: a stored threshold outliving the rule that made it.  Refuse rather than
        # recompute under today's rule, which would compare two numbers that mean different things.
        # An explicit wrong label is a STATEMENT, and the identity below does not get to overrule one.
        return GateReading(strategy, UNREADABLE, f"the report's gate is {labelled!r}, not {SELECTION_GATE}")

    sharpe = block.get("oos_sharpe_annual")
    variance = block.get("variance")
    threshold = block.get("threshold_annual")
    n_then = block.get("n_trials")
    alpha = float(block.get("alpha", 0.05))
    # Spelled out per name rather than `all(isinstance(v, int | float) for v in (...))`, which is what
    # stood here.  A narrowing made inside a generator does not reach the caller, so every `float(sharpe)`
    # and `int(n_then)` below stayed `Any | None` and mypy 2.x failed this file on 22 arg-type errors -
    # the type step is ahead of the test step in CI, so that one line kept the tests from running for four
    # days.  Same four checks, same message, same verdict; only the spelling moved.  Do not fold it back.
    if (
        not isinstance(sharpe, int | float)
        or not isinstance(variance, int | float)
        or not isinstance(threshold, int | float)
        or not isinstance(n_then, int | float)
    ):
        return GateReading(strategy, UNREADABLE, "the selection block is missing sharpe/variance/threshold/n")

    quantile_then = max_sharpe_quantile(int(n_then), float(variance), alpha)
    if quantile_then <= 0.0:
        return GateReading(strategy, UNREADABLE, "the report's quantile is not positive; scale is unrecoverable")
    scale = float(threshold) / quantile_then

    if labelled is None:
        # Operator ruling 2026-09-14 (Q1).  Every report written before KILL-Q3 added `gate` carries no
        # label, which made the recheck total: all seven mined validations were UNREADABLE, including
        # the only candidate this pipeline has ever passed.  The ruling is that the IDENTITY may stand
        # in for the label, and it may because it is falsifiable - `threshold_annual` is the raw
        # quantile times `sqrt(bars_per_year)`, so a threshold produced by any other rule leaves a
        # different scale behind.  Measured on the seven before this was written: 594a12f9 implies
        # 93.594872 = sqrt(8760) exactly; the other six imply 0.805x that, which is
        # `E[max] / quantile(0.95)` - the expectation KILL-Q3 replaced because it "admitted pure noise
        # at 43.5%".  So this admits one report and refuses six, which is the discrimination `gate` was
        # added to make, recovered from the numbers.
        interval = report.get("interval")
        try:
            expected = math.sqrt(bars_per_year(str(interval)))
        except (KeyError, ValueError, TypeError):
            return GateReading(
                strategy,
                UNREADABLE,
                f"the report carries no `gate` and no usable `interval` ({interval!r}), so its "
                "annualisation cannot be checked against the rule it claims",
                float(sharpe),
                int(n_then),
                float(threshold),
            )
        if abs(scale - expected) > 1e-6 * expected:
            return GateReading(
                strategy,
                UNREADABLE,
                f"the report carries no `gate` and its annualisation is {scale:.6f}, not the "
                f"{expected:.6f} that {SELECTION_GATE} at {interval} implies: it was produced by a "
                "different rule",
                float(sharpe),
                int(n_then),
                float(threshold),
            )

    # N is NOT the bucket count.  `dsr_inputs` builds it as ledger + this run's grid + the declared
    # pre-ledger trials, so tsmom's 183 is 86 + 2 + 95 and the bucket alone reads 88.  Only the ledger
    # term can move after the fact - the grid and the declaration are properties of that run - so the
    # recomputation adds the DELTA and leaves the other two where the report put them.  Reading the
    # bucket as N would have handed tsmom 88 against 183 and called the record impossible, which is
    # what the first version of this function did.
    ledger_block = report.get("ledger")
    ledger_then = ledger_block.get("ledger_trials") if isinstance(ledger_block, Mapping) else None
    if not isinstance(ledger_then, int):
        return GateReading(
            strategy,
            UNREADABLE,
            "the report records no `ledger.ledger_trials`, so the ledger term of N cannot be separated",
            float(sharpe),
            int(n_then),
            float(threshold),
        )
    bucket_today = len(
        unique_trials(
            parse_ledger(ledger_lines, ledger_scope(strategy)),
            range_end_granularity_days=range_end_granularity_days,
        )
    )
    if bucket_today < ledger_then:
        # The ledger is append-only, so this means the file being read is not the one the report was
        # written against.  Deciding on it would retire or spare a book on a truncated record.
        return GateReading(
            strategy,
            UNREADABLE,
            f"the bucket holds {bucket_today} trials, fewer than the {ledger_then} the report recorded; "
            "append-only says that cannot happen, so this is not the ledger the report was written against",
            float(sharpe),
            int(n_then),
            float(threshold),
        )
    n_today = int(n_then) + (bucket_today - ledger_then)

    threshold_today = max_sharpe_quantile(n_today, float(variance), alpha) * scale
    passes = float(sharpe) >= threshold_today
    return GateReading(
        strategy,
        PASS if passes else FAIL,
        f"OOS {float(sharpe):.4f} vs {threshold_today:.4f} at N={n_today} (adopted against "
        f"{float(threshold):.4f} at N={int(n_then)})",
        float(sharpe),
        int(n_then),
        float(threshold),
        n_today,
        threshold_today,
    )


def recheck(
    registry: Registry,
    read_report: Any,
    ledger_lines: Sequence[str],
    *,
    only: Iterable[str] | None = None,
    range_end_granularity_days: int,
) -> tuple[GateReading, ...]:
    """Every enabled strategy's gate at today's N.  `read_report` maps an evidence path to its payload."""
    wanted = set(only) if only is not None else None
    out: list[GateReading] = []
    for entry in registry.strategies:
        if not entry.enabled or (wanted is not None and entry.id not in wanted):
            continue
        path = (entry.evidence or {}).get("report") if isinstance(entry.evidence, Mapping) else None
        if not path:
            out.append(GateReading(entry.id, UNREADABLE, "the registry entry cites no evidence report"))
            continue
        try:
            report = read_report(str(path))
        except (OSError, ValueError) as error:
            out.append(GateReading(entry.id, UNREADABLE, f"{path}: {error}"))
            continue
        out.append(read_gate(entry.id, report, ledger_lines, range_end_granularity_days=range_end_granularity_days))
    return tuple(out)


def failures(readings: Sequence[GateReading]) -> tuple[GateReading, ...]:
    """FAIL only.  UNREADABLE is not a failure of the gate, it is a failure to ask it."""
    return tuple(reading for reading in readings if reading.status == FAIL)


def refusals(verdicts: Iterable[Verdict], strategy: str) -> tuple[Derived, ...]:
    """One strategy's `refuse` rulings in the verdict ledger, oldest first, as events `advance` folds.

    Read from the ledger rather than from a fresh `recheck` for the reason `tenure` reads `cycles.jsonl`:
    a ruling has an instant and an id, so the watermark folds it once and every demotion names its row.
    ALLOW rows produce nothing - passing again does not promote; the nine windows do.
    """
    rows = [v for v in verdicts if v.kind == VERDICT_KIND and v.subject == strategy and v.ruling == REFUSE]
    return tuple(
        Derived(at=v.at, event=Event.FAMILY_GATE_FAILED, why=f"R0: verdict {v.id} refused: {'; '.join(v.reasons)}")
        for v in sorted(rows, key=lambda v: datetime.fromisoformat(v.at))
    )
