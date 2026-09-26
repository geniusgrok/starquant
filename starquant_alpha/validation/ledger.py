"""Append-only ledger of every configuration ever evaluated per strategy (the DSR denominator).

Selection bias does not reset between research rounds.  Every ``validate``
run records each grid point's full-sample Sharpe here; the next run charges
all of them (plus any manually declared pre-ledger trials) in its Deflated
Sharpe Ratio and uses their dispersion as the Sharpe variance.  An exact
replay of a recorded configuration on the same data (same parameters, same
range, same symbol count) is one trial, not two (D-024).  Pure functions over
a list of records; the CLI does the file I/O.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np

# KILL-Q5: the ledger's address used to be `Path(--out) / "trials.jsonl"`, and `--out` is a flag
# passed for ordinary reasons - point the reports at a scratch directory and the run was charged to a
# fresh, empty ledger.  A loophole nobody has to intend is the kind worth closing, so the address is
# fixed and moving it takes an environment variable whose only possible purpose is to not be charged.
LEDGER_ENV = "STARQUANT_TRIALS_LEDGER"
DEFAULT_LEDGER = Path("reports/research/trials.jsonl")


def _checkout_root(start: Path) -> Path | None:
    """The checkout ``start`` sits in, or None.  A worktree's ``.git`` is a file, and still a root."""
    here = start.resolve()
    for directory in (here, *here.parents):
        if (directory / ".git").exists():
            return directory
    return None


def ledger_redirection() -> str:
    """Where ``LEDGER_ENV`` is pointing the ledger, or "" when it is not set.

    Separate from ``resolve_ledger_path`` because the two answer different questions and only one of
    them has an answer worth printing: the path is what to write, this is whether the shared, tracked
    ledger is being written at all.  The docstring below calls the variable's "only possible purpose
    ... to not be charged", and then nothing downstream could tell.  A command that charges the one
    ledger and a command that charges a scratch file rendered identically, so the one loophole this
    module names out loud was also the one it reported nothing about.

    Reported, never refused: redirecting is legitimate (every test that writes a ledger does it), and
    a guard here would break them.  What it may not be is silent.
    """
    return os.environ.get(LEDGER_ENV, "").strip()


def resolve_ledger_path(*, out: str | Path | None = None, root: Path | None = None, start: Path | None = None) -> Path:
    """The one ledger.  ``out`` is accepted and ignored, which is the entire point of this function.

    Anchored to the checkout rather than to the working directory.  A relative path is L1-07's shape -
    run from ``starquant_alpha/`` and ``reports/research/trials.jsonl`` names a file that does not exist,
    so the run is charged to a fresh empty book and reports ``ledger_trials: 0``.  That is the state
    KILL-Q5 was about, reached by walking into a subdirectory instead of by typing a flag; closing one
    and leaving the other would have been closing the one that is harder to trip over.

    Per checkout, deliberately: the ledger is a tracked file, so a worktree's rows reach the others by
    merging, the same path every other artefact here takes.
    """
    override = ledger_redirection()
    if override:
        return Path(override)
    anchor = root if root is not None else _checkout_root(start or Path.cwd())
    return (anchor / DEFAULT_LEDGER) if anchor is not None else DEFAULT_LEDGER


@dataclass(frozen=True)
class TrialRecord:
    strategy: str
    param_key: str
    sharpe_annual: float | None
    bars_per_year: float
    recorded_at: str
    range_start: str
    range_end: str
    symbols: int
    run_id: str
    # DL-K1.  Optional, defaulting to "", because 145 rows predate them and a ledger that cannot read
    # its own history is not a ledger.  A legacy row therefore never folds into a modern one: folding
    # would assert that the old run used today's construction, which is the ledger claiming knowledge
    # it does not have - worse than charging a trial twice (KILL-P5).
    construction_digest: str = ""  # the portfolio construction the weights were built under (D-026)
    overlay_digest: str = ""  # exits / throttle applied on top of them
    symbol_set_hash: str = ""  # WHICH symbols, not how many: `symbols` is a count and cannot tell two apart
    search_space_version: str = ""  # for mined ids: how wide the search that produced this was

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True)

    @classmethod
    def from_json(cls, line: str) -> TrialRecord | None:
        """A missing REQUIRED field is a broken row; a missing optional one is a legacy row.

        That distinction is the whole of DL-K1's backward compatibility - 145 rows predate the four
        optional fields, and reading them has to yield "" rather than an error or a guess - which is
        why the mapping is spelled out here instead of derived from `fields()`.
        """
        try:
            payload = json.loads(line)
            return cls(
                strategy=payload["strategy"],
                param_key=payload["param_key"],
                sharpe_annual=payload["sharpe_annual"],
                bars_per_year=payload["bars_per_year"],
                recorded_at=payload["recorded_at"],
                range_start=payload["range_start"],
                range_end=payload["range_end"],
                symbols=payload["symbols"],
                run_id=payload["run_id"],
                construction_digest=str(payload.get("construction_digest", "")),
                overlay_digest=str(payload.get("overlay_digest", "")),
                symbol_set_hash=str(payload.get("symbol_set_hash", "")),
                search_space_version=str(payload.get("search_space_version", "")),
            )
        except (ValueError, KeyError, TypeError):
            return None

    def fold_key(self, range_end_granularity_days: int) -> tuple[Any, ...]:
        """`signature`, with `range_end` quantised - what actually decides "same trial" (caliber ④).

        Operator ruling 2026-09-14, on Q4c.  A signal's value at bar t depends on data up to t, so the
        same expression over the same start, symbols and construction produces an IDENTICAL stream on
        the shared index when the range ends a few days later; the extra bars are the only difference
        and the added independence is exactly zero.  That is arithmetic, not an estimate.

        It is not a reason to drop the field.  The same argument holds for a range ending two years
        later, and that really is a second look - the Sharpe it records is a different number.  So the
        fold needs a granularity, and `range_end_granularity_days = 0` means "do not fold", which is
        the rule as it stood before the ruling and has to stay reachable to be comparable against.

        Bucket boundaries mean two runs a day apart can straddle one and not fold.  Known, and it errs
        toward charging MORE - the direction a denominator is allowed to be wrong in.
        """
        return (
            self.param_key,
            self.range_start,
            _range_end_bucket(self.range_end, range_end_granularity_days),
            self.symbols,
            self.construction_digest,
            self.overlay_digest,
            self.symbol_set_hash,
            self.search_space_version,
        )

    @property
    def signature(self) -> tuple[str, str, str, int, str, str, str, str]:
        """What makes two records the same trial.

        Parameters, data range and symbol count were not enough: they cannot see the construction the
        weights were built under, the overlay applied to them, WHICH symbols those were, or how wide
        the search a mined id came from.  Two runs differing in any of those are two trials, and
        folding them charged the DSR denominator less than the selection actually cost (KILL-Q5).
        """
        return (
            self.param_key,
            self.range_start,
            self.range_end,
            self.symbols,
            self.construction_digest,
            self.overlay_digest,
            self.symbol_set_hash,
            self.search_space_version,
        )


# DL-K2: every candidate a `research mine` round evaluated lands here, under one key rather than one
# key each.  The search IS the family - a mined candidate was selected by ranking the whole space on
# the full sample - so its denominator has to be able to read the space back.

#: Caliber ④'s buckets are anchored here, not at the first row seen, so the fold is deterministic and
#: order-independent: an equivalence relation rather than a tolerance, which "within N days of each
#: other" is not (A~B and B~C without A~C).
_FOLD_EPOCH = date(1970, 1, 1)


def _range_end_bucket(range_end: str, granularity_days: int) -> str | int:
    """Which bucket a `range_end` falls in, or the raw string when it must not be folded.

    Granularity 0 returns the string unchanged - the pre-ruling rule.  A date this cannot parse also
    returns unchanged: a value the fold cannot read says nothing about whether two runs are one trial,
    and a denominator resolves its doubt by charging more.
    """
    if granularity_days <= 0:
        return range_end
    try:
        parsed = datetime.fromisoformat(range_end.replace(" ", "T")).date()
    except ValueError:
        return range_end
    return (parsed - _FOLD_EPOCH).days // granularity_days


MINED_SEARCH_STRATEGY = "mined"

# The same rule for a search the SIGNAL runs rather than the operator: `pairs` picks which symbol pairs
# to trade out of every pair its formation window can form (measured 2026-09-09: 19,578 distinct pairs
# examined, 183 traded), and until this key existed that choice was charged nothing at all.  One shared
# bucket for the same reason the mined one is shared: the space belongs to the SEARCH, not to the
# strategy that ran it, so a second pair-type formalisation - cointegration instead of correlation, say -
# starts from what looking at those 19,578 pairs already cost instead of from zero.  Separate from the
# `pairs` key rather than merged into it because the two answer different questions: `pairs` holds the
# configurations that were scored (4 of them, with Sharpes that set the DSR's variance), and this holds
# the candidates that were only looked at (no Sharpe each, and 19,578 rows would bury the other four).
PAIR_SEARCH_STRATEGY = "pairs_search"


#: A mined candidate reaches the ledger under two spellings of one expression.  The search row writes
#: the bare canonical hash; the same candidate validated on its own goes through
#: `walk_forward.param_key`, which spreads `to_signal`'s default_params into
#: `entry_threshold=0.2|expression=...|hash=<that same hash>`.  `ledger_scope` collects both buckets,
#: so the companion count read one hypothesis as two.  Measured 2026-09-20 on the real ledger: four of
#: the seven `mined_*` strategies reported 677 where the bucket holds 676.  The other three report 677
#: correctly - their expressions predate the current search space, so they really are a 677th.
_ALIASED_BY_HASH = re.compile(r"(?:^|\|)hash=([0-9a-f]{16})(?:\||$)")


def hypothesis_key(param_key: str) -> str:
    """The hypothesis a `param_key` is about.  Feeds `distinct_hypotheses` only, never a gate.

    `n_trials` still charges both rows and `signature`'s fold is untouched: two runs are two trials
    whatever they are about (D-024 decides that).  This stops only the companion count from
    inheriting a spelling, which is the one number that claims to count hypotheses.
    """
    aliased = _ALIASED_BY_HASH.search(param_key)
    return aliased.group(1) if aliased else param_key


def ledger_scope(strategy: str) -> tuple[str, ...]:
    """Which ledger keys a strategy's DSR denominator draws from.

    A hand-written strategy pays for its own grid.  A mined candidate pays for the search that found
    it as well: nothing about `mined_594a12f9307a15d9` is remarkable until you know it was the best of
    514, and that number used to be copied off a terminal into `--prior-trials` by hand.

    A pair-type strategy pays for the pair search the same way.  Matched on the id, as the mined rule
    is, so this module stays free of the signal registry; the link that actually has to hold - a signal
    declaring a census is routed to the bucket it declares - is asserted in
    `tests/alpha/test_a_signals_own_search_is_charged.py`, so registering a pair searcher under a name
    this rule does not catch fails a test rather than quietly restoring the free denominator.
    """
    if strategy.startswith("mined_"):
        return (strategy, MINED_SEARCH_STRATEGY)
    if strategy.startswith("pairs") and strategy != PAIR_SEARCH_STRATEGY:
        return (strategy, PAIR_SEARCH_STRATEGY)
    return (strategy,)


def parse_ledger(lines: Iterable[str], strategy: str | Iterable[str]) -> list[TrialRecord]:
    wanted = {strategy} if isinstance(strategy, str) else set(strategy)
    records: list[TrialRecord] = []
    for line in lines:
        record = TrialRecord.from_json(line)
        if record is not None and record.strategy in wanted:
            records.append(record)
    return records


def all_trials(lines: Iterable[str]) -> list[TrialRecord]:
    """Every readable row, whatever strategy it is filed under.

    R0 reports the whole-library trial count beside the per-strategy one and gates on neither of the
    two by accident: the gate stays the strategy bucket (`ledger_scope`), and this exists so the
    artefact can show what the other caliber would have asked for.  Deriving the gate from it would
    FAIL the incumbent on an honest grid, which is the measurement that settled R0 (KILL-AR-01) - a
    number nobody can see is a number nobody can argue with.
    """
    records: list[TrialRecord] = []
    for line in lines:
        record = TrialRecord.from_json(line)
        if record is not None:
            records.append(record)
    return records


def unique_trials(
    records: Iterable[TrialRecord],
    *,
    exclude: Iterable[tuple[Any, ...]] = (),
    range_end_granularity_days: int,
) -> list[TrialRecord]:
    """First record per fold key; keys in ``exclude`` (the current run's own grid) are dropped.

    ``range_end_granularity_days`` has no default on purpose.  It is a governance threshold (R10 keeps
    those in `Policy`, which this layer cannot import), so it is threaded through instead - and a
    default here would let a caller quietly get the pre-ruling rule while believing it had the new one.
    That is the invisible-default shape, which this repo has been bitten by twice in one day.
    """
    skip = set(exclude)
    seen: set[tuple[Any, ...]] = set()
    out: list[TrialRecord] = []
    for record in records:
        key = record.fold_key(range_end_granularity_days)
        if key in skip or key in seen:
            continue
        seen.add(key)
        out.append(record)
    return out


def dsr_inputs(
    prior: list[TrialRecord],
    current_sharpes_period: Mapping[str, float | None],
    bars_per_year: float,
    *,
    manual_prior_trials: int = 0,
    current_range: tuple[str, str, int] | None = None,
    current_context: tuple[str, str, str, str] = ("", "", "", ""),
    range_end_granularity_days: int,
) -> dict[str, Any]:
    """n_trials and per-period Sharpe variance pooled over the ledger and the current grid.

    Exact replays are counted once: duplicate ledger rows collapse to one, and a
    ledger row that is the current grid re-run on the same range and symbols
    (``current_range`` = (range_start, range_end, symbols)) is not charged twice.

    ``current_context`` is the other half of the signature - construction, overlay, symbol set,
    search space - and it must be built here rather than left to default, because an exclusion set
    shorter than a signature matches nothing at all and silently charges every replay twice.
    """
    scale = float(np.sqrt(bars_per_year))
    # Built through `fold_key` rather than assembled by hand in the shape of a signature.  The hand-made
    # version was the trap caliber ④ could have shipped: quantise the fold and leave the exclusion
    # literal, and every replay stops matching and is charged a second time - silently, and in the
    # direction that looks rigorous.  One key, one implementation, no way for the two to disagree.
    exclude = (
        [
            TrialRecord(
                strategy="",
                param_key=key,
                sharpe_annual=None,
                bars_per_year=bars_per_year,
                recorded_at="",
                range_start=current_range[0],
                range_end=current_range[1],
                symbols=current_range[2],
                run_id="",
                construction_digest=current_context[0],
                overlay_digest=current_context[1],
                symbol_set_hash=current_context[2],
                search_space_version=current_context[3],
            ).fold_key(range_end_granularity_days)
            for key in current_sharpes_period
        ]
        if current_range is not None
        else []
    )
    distinct = unique_trials(prior, range_end_granularity_days=range_end_granularity_days)
    unique = unique_trials(distinct, exclude=exclude, range_end_granularity_days=range_end_granularity_days)
    pooled: list[float] = [r.sharpe_annual / scale for r in unique if r.sharpe_annual is not None]
    pooled.extend(v for v in current_sharpes_period.values() if v is not None)
    n_trials = len(unique) + len(current_sharpes_period) + max(0, int(manual_prior_trials))
    variance = float(np.var(pooled, ddof=1)) if len(pooled) >= 2 else 0.0
    return {
        "n_trials": n_trials,
        "sharpe_variance": variance,
        "ledger_trials": len(unique),
        "ledger_rows": len(prior),
        "duplicate_rows": len(prior) - len(distinct),  # exact copies of an earlier row
        "replayed_rows": len(distinct) - len(unique),  # the current grid re-run on the same data
        # How many distinct HYPOTHESES those rows are about.  Reported, never gated - `n_trials` above
        # is untouched, and `signature`'s folding rule is untouched with it.  It exists because the
        # four counts beside it all count rows, so an artefact could say 2,731 four different ways and
        # never once say 676.  An analysis read the former as the latter and judged the miner on it;
        # nothing in any artefact could contradict the reading, which is the failure this closes.
        # Counted per `hypothesis_key`, not per `param_key`: see its note for the two spellings.
        "distinct_hypotheses": len({hypothesis_key(record.param_key) for record in prior}),
        # Which fold produced the counts above.  A fold nobody can see is a fold nobody can argue with.
        "range_end_granularity_days": int(range_end_granularity_days),
        "pooled_sharpes": len(pooled),
    }


def _grid_key(grid: Mapping[str, Any]) -> str:
    """Two grids that enumerate the same cells compare equal, whichever side they were written on.

    One comes from ``--grid`` or ``DEFAULT_GRIDS`` (Python literals), the other off a validation
    report (JSON), so the comparison has to survive that round trip and nothing else: same keys, same
    values, order-insensitive.
    """
    return json.dumps({str(key): grid[key] for key in sorted(grid)}, sort_keys=True, default=str)


def undeclared_charge(
    *,
    strategy: str,
    cells: int,
    grid: Mapping[str, Any],
    cited_grid: Mapping[str, Any] | None,
    declared: int | None,
) -> str:
    """Why this run's ledger charge has not been declared, or ``""`` when it has.

    Every grid cell appends one row per run, and the strategy's own bucket is the denominator of the
    D-028 threshold the SAME strategy's cited evidence has to clear - `family_gate`'s docstring states
    the consequence, "searching more retires your own incumbents".  So a run against an enabled entry
    spends the incumbent's remaining margin, and the amount has to be something the operator said out
    loud rather than something ``--grid``'s default chose.

    **Why this exists as an executing check rather than a line in the RUNBOOK.**  Measured 2026-09-17:
    a two-arm A/B was priced to the operator at "2 trials", ran without ``--grid``, and got
    ``DEFAULT_GRIDS["tsmom"]`` - sixteen cells - on each arm.  It charged 32.  tsmom's family gate went
    N 259 -> 293 and its threshold 1.5572 -> 1.5715, taking the incumbent's margin from +0.0347 to
    +0.0204: about 35% of the remaining headroom, in one command, from a default nobody typed.  The
    control arm also stopped reproducing the shipped pointer, so the evidence could not anchor to it.

    Two ways to be declared, and they are different statements:

    * the run reproduces the grid the cited evidence used - the same experiment, so the charge is the
      one already paid for and dedupes against it (D-024);
    * ``--charge N`` names the exact number of rows, which is a sentence someone had to write.

    ``declared`` that disagrees with ``cells`` is refused rather than accepted as "close enough": the
    whole value of the declaration is that it is the number, and a wrong one is how the 2-against-32
    mistake reads in a commit message afterwards.
    """
    if cited_grid is not None and _grid_key(grid) == _grid_key(cited_grid):
        return ""
    if declared is not None and declared == cells:
        return ""
    cited = (
        f"{len(_cells_of(cited_grid))} cell(s), {json.dumps(cited_grid, sort_keys=True, default=str)}"
        if cited_grid is not None
        else "no grid at all, so the two cannot be compared"
    )
    if declared is not None:
        return (
            f"--charge {declared} does not match this run: it enumerates {cells} cell(s), so it will "
            f"append {cells} row(s) to {strategy}'s ledger bucket.  Declare the number it actually "
            f"spends (--charge {cells}) or change the grid."
        )
    return (
        f"{strategy} is an enabled registry entry and this grid is not the one its cited evidence "
        f"used: {cells} cell(s) here, against {cited}.  Every cell appends a row to the shared trials "
        f"ledger, which is the denominator of the D-028 gate that same evidence has to clear - on "
        f"2026-09-17 a run priced at 2 trials spent 32 this way and took tsmom's headroom from ~92 to "
        f"~58.  Either reproduce the pointer (pass its grid to --grid) or say what this one spends "
        f"with --charge {cells}."
    )


def _cells_of(grid: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The cells a grid enumerates - the same product ``research validate`` builds, for counting only."""
    keys = sorted(grid)
    if not keys:
        return [{}]
    out: list[dict[str, Any]] = [{}]
    for key in keys:
        values = grid[key] if isinstance(grid[key], list) else [grid[key]]
        out = [{**cell, key: value} for cell in out for value in values]
    return out
