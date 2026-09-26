"""DL-K2 for the search a SIGNAL runs: `research validate --strategy pairs` pays for its pairs.

`pairs-validation-20260908T172303Z.json` recorded `oos_selection.n_trials: 4` and
`multiple_testing.prior_trials: 0` for a run that had chosen its partners out of 19,578 distinct symbol
pairs.  The verdict was FAIL on five other grounds and is not what changed here - the mechanism is: a
search nobody charges is a denominator wrong in the one direction that flatters it, and the next
pair-type candidate would have inherited the same free lunch.

The four properties: the enumeration reaches the ledger, it reaches THIS run's gate rather than the next
one's, re-running the same search charges nothing again, and the rows land in the shared `pairs_search`
bucket instead of burying the four scored configurations under 19,578 rows of a different kind.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from click.testing import CliRunner

from starquant_alpha.validation.ledger import PAIR_SEARCH_STRATEGY, ledger_scope, parse_ledger, unique_trials
from starquant_alpha.validation.multiple_testing import max_sharpe_quantile
from starquant_cli import main
from starquant_data.store import KlineStore

FOLD_DAYS = 7  # caliber 4's granularity; production reads Policy, tests pin it

SYMBOLS = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT")
PAIRS = len(SYMBOLS) * (len(SYMBOLS) - 1) // 2
# The fixture is 720 bars, so the pre-registered 720-bar formation window would never refit at all.
# Scaled down, not relaxed: the shape under test is the enumeration, which is the same at any window.
SHORT_WINDOWS = '{"formation_bars": 120, "refit_bars": 120, "z_window": 48}'
GRID = '{"entry_z": [1.5, 2.0]}'


def _store_from_fixtures(august_dir: Path, root: Path) -> None:
    store = KlineStore(root)
    for symbol in SYMBOLS:
        frame = pd.read_parquet(august_dir / symbol / "1h.parquet")
        frame["close_time"] = frame["open_time"] + 3_600_000 - 1
        store.append(symbol, "1h", frame)


def _validate(root: Path, out: Path, strategy: str = "pairs", *extra: str) -> tuple[dict, str]:
    result = CliRunner().invoke(
        main,
        [
            "research", "validate",
            "--strategy", strategy,
            "--root", str(root),
            "--symbols", ",".join(SYMBOLS),
            "--out", str(out),
            "--no-funding",
            "--params", SHORT_WINDOWS if strategy == "pairs" else '{"horizons": [5, 20, 50], "crowding_window": 0}',
            "--grid", GRID if strategy == "pairs" else "{}",
            "--folds", "3",
            "--min-train", "300",
            "--purge", "5",
            "--cpcv-groups", "4",
            "--min-history", "0",
            *extra,
        ],
    )  # fmt: skip
    assert result.exit_code == 0, result.output
    newest = max(out.glob(f"{strategy}-validation-*.json"), key=lambda p: p.stat().st_mtime)
    return json.loads(newest.read_text()), result.output


def _rows(ledger: Path, strategy: str) -> list[dict]:
    if not ledger.exists():
        return []
    rows = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [row for row in rows if row["strategy"] == strategy]


def test_every_pair_the_search_examined_reaches_the_ledger(
    tmp_path: Path, august_dir: Path, isolated_trials_ledger: Path
) -> None:
    """Four symbols is six hypotheses, whatever the grid did afterwards."""
    root = tmp_path / "data"
    _store_from_fixtures(august_dir, root)

    report, _ = _validate(root, tmp_path / "reports")

    charged = _rows(isolated_trials_ledger, PAIR_SEARCH_STRATEGY)
    assert len(charged) == PAIRS
    assert {row["param_key"] for row in charged} == {
        f"{left}|{right}" for i, left in enumerate(sorted(SYMBOLS)) for right in sorted(SYMBOLS)[i + 1 :]
    }
    assert report["signal_search"]["candidates"] == PAIRS
    assert report["signal_search"]["bucket"] == PAIR_SEARCH_STRATEGY
    assert 0 < report["signal_search"]["selected"] < PAIRS


def test_the_run_that_did_the_searching_is_the_one_that_pays_for_it(
    tmp_path: Path, august_dir: Path, isolated_trials_ledger: Path
) -> None:
    """Charged before the denominator is read, so the FIRST report carries it.

    `mine` writes its rows at the end because a shortlist is not a verdict.  This command decides a
    PASS/FAIL: charging afterwards would ship the un-charged number and hand the bill to the next run.
    """
    root = tmp_path / "data"
    _store_from_fixtures(august_dir, root)

    report, _ = _validate(root, tmp_path / "reports")

    assert report["prior_trials_declared"] == 0, "nothing was declared by hand; the search is the denominator"
    assert report["ledger"]["ledger_trials"] == PAIRS
    assert report["multiple_testing"]["n_trials"] == PAIRS + len(report["trial_sharpes"])
    assert report["oos_selection"]["n_trials"] == report["multiple_testing"]["n_trials"]


def test_the_gate_gets_stricter_and_that_is_the_point(
    tmp_path: Path, august_dir: Path, isolated_trials_ledger: Path
) -> None:
    """D-028's threshold at the honest N against the threshold at the grid alone, on this run's own null.

    On the 2026-09-08 panel the same arithmetic runs 0.98 -> 2.01 annualised at 19,582 trials against 4.
    A gate that does not move when the denominator does is not reading it.
    """
    root = tmp_path / "data"
    _store_from_fixtures(august_dir, root)

    report, _ = _validate(root, tmp_path / "reports")

    selection = report["oos_selection"]
    grid_only = max_sharpe_quantile(len(report["trial_sharpes"]), selection["variance"], selection["alpha"])
    assert selection["threshold_annual"] > grid_only * (8760**0.5)


def test_looking_at_the_same_pairs_again_is_not_a_second_search(
    tmp_path: Path, august_dir: Path, isolated_trials_ledger: Path
) -> None:
    """`mine`'s replay rule, unchanged: a search is a set of hypotheses, not an event."""
    root = tmp_path / "data"
    _store_from_fixtures(august_dir, root)

    first, _ = _validate(root, tmp_path / "r1")
    again, output = _validate(root, tmp_path / "r2")

    assert len(_rows(isolated_trials_ledger, PAIR_SEARCH_STRATEGY)) == PAIRS
    assert first["signal_search"]["family_prior"] == {"strategy": PAIR_SEARCH_STRATEGY, "before": 0, "after": PAIRS}
    assert again["signal_search"] == {**first["signal_search"], "charged": 0, "family_prior": {
        "strategy": PAIR_SEARCH_STRATEGY, "before": PAIRS, "after": PAIRS,
    }}  # fmt: skip
    assert f"+0 charged now, family prior {PAIRS} -> {PAIRS}" in output


def test_the_search_has_its_own_bucket_and_the_denominator_reads_both(
    tmp_path: Path, august_dir: Path, isolated_trials_ledger: Path
) -> None:
    """Why not one bucket: the two answer different questions, and 19,578 rows would bury the other four.

    `pairs` holds the configurations that were SCORED - their Sharpes are the DSR's variance - and
    `pairs_search` the candidates that were only looked at.  The gate sums them through `ledger_scope`,
    which is also what makes the next pair-type formalisation inherit this search instead of starting
    from zero.
    """
    root = tmp_path / "data"
    _store_from_fixtures(august_dir, root)

    report, _ = _validate(root, tmp_path / "reports")

    lines = isolated_trials_ledger.read_text(encoding="utf-8").splitlines()
    assert len(_rows(isolated_trials_ledger, "pairs")) == len(report["trial_sharpes"])
    assert len(
        unique_trials(parse_ledger(lines, ledger_scope("pairs")), range_end_granularity_days=FOLD_DAYS)
    ) == PAIRS + len(report["trial_sharpes"])
    # A second pair-type id pays for this search without having run it, which is the point of sharing.
    assert (
        len(unique_trials(parse_ledger(lines, ledger_scope("pairs_coint")), range_end_granularity_days=FOLD_DAYS))
        == PAIRS
    )


def test_a_candidate_pair_carries_no_construction_and_no_sharpe(
    tmp_path: Path, august_dir: Path, isolated_trials_ledger: Path
) -> None:
    """Both omissions are load-bearing.

    The pair search runs on `panel.close` before any weight exists, so it enumerates the identical
    candidates under every vol target and exit stack: a construction digest would charge the same
    hypotheses again at the next target, which is this bug mirrored.  And the candidates were never
    scored one at a time - they are selected on formation-window correlation, not on their own P&L -
    so a Sharpe here would be invented, and `dsr_inputs` pools only the rows that have one.
    """
    root = tmp_path / "data"
    _store_from_fixtures(august_dir, root)

    report, _ = _validate(root, tmp_path / "reports")

    charged = _rows(isolated_trials_ledger, PAIR_SEARCH_STRATEGY)
    assert all(row["sharpe_annual"] is None for row in charged)
    assert all(row["construction_digest"] == "" and row["overlay_digest"] == "" for row in charged)
    assert all(row["symbol_set_hash"] for row in charged), "WHICH symbols were pairable is part of the search"
    # The scored configurations still carry theirs, so the variance the DSR uses is unaffected.
    assert report["multiple_testing"]["sharpe_variance_period"] > 0
    assert all(row["construction_digest"] for row in _rows(isolated_trials_ledger, "pairs"))


def test_a_signal_that_searches_nothing_is_charged_nothing(
    tmp_path: Path, august_dir: Path, isolated_trials_ledger: Path
) -> None:
    """Eight of the nine signals score every symbol they are handed; their reports must not grow a block."""
    root = tmp_path / "data"
    _store_from_fixtures(august_dir, root)

    report, output = _validate(root, tmp_path / "reports", "tsmom")

    assert "signal_search" not in report
    assert "signal search" not in output
    assert _rows(isolated_trials_ledger, PAIR_SEARCH_STRATEGY) == []
