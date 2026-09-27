"""`research book` writes the three §3 limits, so `validated -> booked` stops reading a literal True.

The gap this closes was not an argument about thresholds.  `starquant_governance.lifecycle` has read
`slippage_stress_pass`, `max_correlation_with_running` and `turnover_ratio_to_main` since Phase 0, and
`replay.py` supplied `True / 0.0 / 0.0` for all three because **no book report carried the fields**:
seven validation reports had `slippage_stress` and zero book reports did, and `research correlate`
wrote a separate artefact with nothing linking it back to a book.  A rule that reads a field nothing
writes cannot run, however well it is argued.

The end-to-end run matters more than the unit tests beside it, because the failure mode was never in
the arithmetic - it was in the wiring.
"""

from __future__ import annotations

import json
from itertools import pairwise
from pathlib import Path

import pandas as pd
import yaml
from click.testing import CliRunner

from starquant_cli import main
from starquant_data.store import KlineStore
from starquant_governance.lifecycle import Book, Candidate, Event, State, evaluate
from starquant_governance.policy import Policy
from starquant_governance.replay import _facts_for
from starquant_shared.config import load_yaml

ROOT = Path(__file__).resolve().parents[2]
SYMBOLS = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT")

#: `research book --profile` defaults to `config/live.demo.yaml`, so until this was pinned every
#: expectation in this file was re-run against a different book each time the operator re-priced risk -
#: and not one of them is about the live risk budget.  2026-09-14: `vol_target` 0.30 -> 0.60 (96d659ae)
#: turned the slippage arm below red, and it read as a wiring bug for exactly as long as it took to
#: bisect the config.  The caps are still read from the shipped profile, because the report's treatment
#: of `max_weight`/`max_gross` IS under test here; only the knob that is not gets pinned.
PINNED_VOL_TARGET = 0.30


def _profile(tmp_path: Path) -> Path:
    payload = load_yaml(ROOT / "config" / "live.demo.yaml")
    payload.setdefault("portfolio", {})["vol_target"] = PINNED_VOL_TARGET
    path = tmp_path / "profile.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return path


#: tsmom on the main book, meanrev as a running probe.  Two books rather than one, because the limit
#: `research correlate` could never answer for a book is the MAXIMUM over what is running - a report
#: that only ever looked at the main book would pass this test with one.
REGISTRY = """
version: 1
ensemble:
  method: mean
books:
  probe_a:
    fraction: 0.333333
strategies:
  - id: tsmom
    enabled: true
    params:
      horizons: [5, 20, 50]
      crowding_window: 0
  - id: meanrev
    enabled: true
    book: probe_a
"""


def _store(august_dir: Path, root: Path) -> None:
    store = KlineStore(root)
    for symbol in SYMBOLS:
        frame = pd.read_parquet(august_dir / symbol / "1h.parquet")
        frame["close_time"] = frame["open_time"] + 3_600_000 - 1
        store.append(symbol, "1h", frame)


def _book(tmp_path: Path, august_dir: Path, sleeve: str) -> tuple[dict, str]:
    root, out = tmp_path / "data", tmp_path / "reports"
    _store(august_dir, root)
    registry = tmp_path / "registry.yaml"
    registry.write_text(REGISTRY, encoding="utf-8")
    result = CliRunner().invoke(
        main,
        [
            "research", "book",
            "--main", "tsmom", "--sleeve", sleeve,
            "--root", str(root), "--symbols", ",".join(SYMBOLS),
            "--registry", str(registry), "--profile", str(_profile(tmp_path)),
            "--out", str(out), "--no-funding", "--universe", "static",
            "--folds", "3", "--min-train", "300", "--purge", "5", "--cpcv-groups", "4",
            "--min-history", "0", "--sensitivity", "",
        ],
    )  # fmt: skip
    assert result.exit_code == 0, result.output
    newest = max(out.glob("book-*.json"), key=lambda p: p.stat().st_mtime)
    return json.loads(newest.read_text(encoding="utf-8")), result.output


def test_the_report_carries_all_three_limits_and_the_state_machine_reads_them(tmp_path: Path, august_dir: Path) -> None:
    report, output = _book(tmp_path, august_dir, "breakout")
    limits = report["book_limits"]

    assert isinstance(limits["slippage_stress"]["pass"], bool)
    assert isinstance(limits["max_correlation_with_running"], float)
    assert isinstance(limits["turnover_ratio_to_main"], float)
    assert "§3 limits" in output, "the operator sees them without opening the JSON"
    # The block belongs to the decision universe; the robustness arm is a sensitivity of the evidence,
    # not a second book to admit, and must not carry a second answer to the same question.
    assert limits == report["universes"][report["universe_mode"]]["book_limits"]

    # And the whole point: the same artefact, through the replay, reaches the state machine.
    event, facts, suspended = _facts_for(report, acknowledged=False)
    assert event is Event.BOOK and suspended == ()
    assert facts.turnover_ratio_to_main == limits["turnover_ratio_to_main"]
    assert facts.max_correlation_with_running == limits["max_correlation_with_running"]


def test_the_turnover_limit_refuses_a_sleeve_that_trades_far_faster_than_the_main_book(
    tmp_path: Path, august_dir: Path
) -> None:
    """breakout against weekly-scale tsmom on this fixture is 11x, and §3 stops at 3x.

    A limit whose only test is a passing case is a limit nobody has watched refuse anything.
    """
    report, _ = _book(tmp_path, august_dir, "breakout")
    assert report["book_limits"]["turnover_ratio_to_main"] > 3.0

    _event, facts, _suspended = _facts_for(report, acknowledged=True)
    decision = evaluate(Book(), Candidate(id="breakout", state=State.VALIDATED), Event.BOOK, facts, Policy())
    assert not decision.allowed
    assert "§3: turnover above 3x the main book" in decision.reasons


def test_the_slippage_arm_re_prices_the_same_decision_rather_than_a_different_one(
    tmp_path: Path, august_dir: Path
) -> None:
    """Two properties, both of which a wrong wiring breaks.

    The 2.0 bps row must reproduce the report's own marginal block to the digit - that level IS the
    baseline cost model (5.0 fee + 2.0 slippage = the 7.0 every archived report was priced at), so any
    difference means the stress is re-pricing something other than the decision.  And every Sharpe CURVE
    the arm reports must decay monotonically as slippage rises, because cost enters each net stream one
    way.

    Monotonicity is asserted of the curves and NOT of the marginal, and the difference is the whole
    lesson of 2026-09-14.  The marginal is a DIFFERENCE of two Sharpes, so its slope in cost is
    `tau_main / sigma_main - tau_booked / sigma_booked`: it falls only while the booked pair is the more
    cost-sensitive of the two, which is an empirical fact about this fixture and not a property of the
    wiring.  At `vol_target` 0.60 it inverts.  Four symbols at `max_weight` 0.15 cap gross at 0.60, so
    both books clip, clipping pins weights and pins turnover, and the main book then loses 0.2204 of
    Sharpe across this bps range against the booked pair's 0.2014 - the marginal RISES by 0.019 while
    both curves still fall.  The old assertion read that as `paying more cannot help`, which made a risk
    re-pricing look like a wiring bug.  (The clipping is not a fixture artefact of no interest: on the
    live universe `config/live.demo.yaml` records 111/293 cycles clipping at k=0.60, though only
    BTCUSDT.  It is the four-symbol fixture that turns it from partial into total.)
    """
    report, _ = _book(tmp_path, august_dir, "breakout")
    by_level = report["book_limits"]["slippage_stress"]["marginal_by_level"]
    baseline = report["universes"][report["universe_mode"]]["by_fraction"][f"{report['fraction']:.4f}"]["marginal"]

    assert by_level["slip2"]["total_cost_bps"] == report["costs"]["turnover_bps"]
    assert by_level["slip2"]["delta_oos_sharpe"] == baseline["delta_oos_sharpe"]
    assert by_level["slip2"]["fold_deltas"] == baseline["fold_deltas"]

    # The sleeve's own Sharpe curve is the same shape validation reports carry, so the two artefacts
    # can be read against each other rather than only within themselves.  The levels come from
    # `costs.yaml`, not from a tuple here: a second copy of the declaration goes red the day the grid
    # gains a cell, and it gained one (4.43, the fills' own measured centre) on 2026-09-17.  Sorted by
    # the bps they price rather than by their string, or `slip4.43` would sort before `slip2`.
    declared = sorted(float(v) for v in load_yaml(ROOT / "config" / "costs.yaml")["slippage_stress_bps"])
    levels = tuple(f"slip{level:g}" for level in declared)
    sleeve = report["book_limits"]["slippage_stress"]["sleeve_standalone_sharpe"]
    assert set(sleeve) == set(levels)

    curves = {
        "main book": [by_level[key]["main_oos_sharpe"] for key in levels],
        "booked pair": [by_level[key]["main_oos_sharpe"] + by_level[key]["delta_oos_sharpe"] for key in levels],
        "sleeve standalone": [sleeve[key] for key in levels],
    }
    # STRICTLY decreasing, not merely non-increasing: a flat curve means the extra basis points reached
    # no net stream at all, which is the wiring failure this test is named for and would otherwise pass.
    for name, curve in curves.items():
        assert all(a > b for a, b in pairwise(curve)), f"paying more must cost the {name} something: {curve}"


def test_a_candidate_that_is_already_a_running_book_is_not_correlated_with_itself(
    tmp_path: Path, august_dir: Path
) -> None:
    """Re-validating a sleeve that is already running would otherwise measure corr 1.0 and refuse it.

    The exclusion is recorded rather than silent: an exclusion nobody can see is indistinguishable
    from a limit that does not bite, which is the state all three of these were in until today.
    """
    report, output = _book(tmp_path, august_dir, "meanrev")
    limits = report["book_limits"]

    assert limits["running_books"] == ["main"], "probe_a is meanrev; correlating it with itself says nothing"
    assert any("probe_a" in note and "meanrev" in note for note in limits["running_books_notes"])
    assert "running book: probe_a" in output
    assert limits["max_correlation_with_running"] == limits["correlation_with_running"]["main"]
