from __future__ import annotations

import dataclasses
import json
import re
from pathlib import Path

import pandas as pd
import pytest
from click.testing import CliRunner

from starquant_alpha.mining import Funding, Ratio, Ret, Squash, Vol, enumerate_candidates
from starquant_alpha.mining.search import Candidate
from starquant_alpha.signals import SIGNALS, get_signal
from starquant_cli import main
from starquant_cli.research_cmd import _resolve_mined
from starquant_data.store import FundingStore, KlineStore
from starquant_live.state import StateStore

SYMBOLS = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT")


def _store_from_fixtures(august_dir: Path, root: Path) -> None:
    store = KlineStore(root)
    for symbol in SYMBOLS:
        frame = pd.read_parquet(august_dir / symbol / "1h.parquet")
        frame["close_time"] = frame["open_time"] + 3_600_000 - 1
        store.append(symbol, "1h", frame)


def test_help_has_all_groups() -> None:
    result = CliRunner().invoke(main, ["--help"])
    assert result.exit_code == 0
    for group in ("data", "research", "live", "report"):
        assert group in result.output


# `crowding_window: 0` in the `--params` below is not decoration.  These runs pass `--no-funding`, and
# tsmom's registry params turn the funding-reading crowding modifier on, so before E-040 was closed they
# were quietly exercising an inert modifier.  Pinning it off says what they have always actually tested.
def test_research_backtest_and_validate_offline(tmp_path: Path, august_dir: Path, isolated_trials_ledger: Path) -> None:
    root = tmp_path / "data"
    _store_from_fixtures(august_dir, root)
    out = tmp_path / "reports"
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "research",
            "backtest",
            "--strategy",
            "tsmom",
            "--root",
            str(root),
            "--symbols",
            ",".join(SYMBOLS),
            "--out",
            str(out),
            "--no-funding",
            "--params",
            '{"vol_window": 100, "horizons": [5, 20, 50], "crowding_window": 0}',
            "--min-history",
            "0",
        ],
    )
    assert result.exit_code == 0, result.output
    reports = list(out.glob("tsmom-backtest-*.json"))
    assert len(reports) == 1
    payload = json.loads(reports[0].read_text())
    assert payload["summary"]["bars"] > 500 and payload["symbols"] == list(SYMBOLS)
    result = runner.invoke(
        main,
        [
            "research",
            "validate",
            "--strategy",
            "tsmom",
            "--root",
            str(root),
            "--symbols",
            ",".join(SYMBOLS),
            "--out",
            str(out),
            "--no-funding",
            "--params",
            '{"horizons": [5, 20, 50], "crowding_window": 0}',
            "--grid",
            '{"vol_window": [100, 200], "entry_threshold": [0.2, 0.3]}',
            "--folds",
            "3",
            "--min-train",
            "300",
            "--purge",
            "5",
            "--cpcv-groups",
            "4",
            "--min-history",
            "0",
        ],
    )
    assert result.exit_code == 0, result.output
    validation = json.loads(next(out.glob("tsmom-validation-*.json")).read_text())
    assert validation["verdict"] in {"PASS", "WEAK_PASS", "FAIL"}
    assert validation["grid_size"] == 4
    assert "sha256=" in result.output
    # D-024: the report is reproducible from itself and records every trial it charged
    assert validation["folds"] == 3 and validation["min_train"] == 300 and validation["purge"] == 5
    assert validation["grid"] == {"vol_window": [100, 200], "entry_threshold": [0.2, 0.3]}
    # DL-K1: the backtest above is now a trial of its own, so the ledger is not empty by the time
    # validate reads it.  That one row is the whole point - it used to be free.
    assert len(validation["trial_sharpes"]) == 4 and validation["ledger"]["ledger_rows"] == 1
    # D-024: the report says which portfolio construction produced these numbers, so a later band or
    # half-life change in the profile is detectable rather than silent
    assert validation["portfolio"]["no_trade_rel_band"] is not None
    assert validation["portfolio"]["vol_target"] > 0 and validation["portfolio"]["max_weight"] > 0
    assert "noise_null" in validation["multiple_testing"]
    # an exact replay of the same grid on the same data is not charged twice (ledger dedupe)
    result = runner.invoke(
        main,
        [
            "research",
            "validate",
            "--strategy",
            "tsmom",
            "--root",
            str(root),
            "--symbols",
            ",".join(SYMBOLS),
            "--out",
            str(out),
            "--no-funding",
            "--params",
            '{"horizons": [5, 20, 50], "crowding_window": 0}',
            "--grid",
            '{"vol_window": [100, 200], "entry_threshold": [0.2, 0.3]}',
            "--folds",
            "3",
            "--min-train",
            "300",
            "--purge",
            "5",
            "--cpcv-groups",
            "4",
            "--min-history",
            "0",
        ],
    )
    assert result.exit_code == 0, result.output
    replay = json.loads(sorted(out.glob("tsmom-validation-*.json"))[-1].read_text())
    # 5 rows: the backtest's one plus this grid's four.  One trial survives dedup - the backtest, whose
    # parameters are not in this grid; the four are the current grid re-run on the same data (D-024).
    assert replay["ledger"]["ledger_rows"] == 5 and replay["ledger"]["ledger_trials"] == 1
    assert replay["multiple_testing"]["n_trials"] == validation["multiple_testing"]["n_trials"]
    result = runner.invoke(
        main,
        [
            "research",
            "decompose",
            "--strategy",
            "tsmom",
            "--root",
            str(root),
            "--symbols",
            ",".join(SYMBOLS),
            "--out",
            str(out),
            "--no-funding",
            "--params",
            '{"vol_window": 100, "horizons": [5, 20, 50], "crowding_window": 0}',
            "--min-history",
            "0",
            "--folds",
            "3",
            "--min-train",
            "300",
            "--purge",
            "5",
        ],
    )
    assert result.exit_code == 0, result.output
    decomposition = json.loads(next(out.glob("decompose-tsmom-*.json")).read_text())
    assert set(decomposition["variants"]) == {
        "full",
        "constant_long",
        "sign_only",
        "long_only",
        "short_only",
        "equal_notional",
    }
    assert "signal_over_construction" in decomposition["increments"] and "increments:" in result.output


def test_data_status_offline(tmp_path: Path, august_dir: Path) -> None:
    root = tmp_path / "data"
    _store_from_fixtures(august_dir, root)
    result = CliRunner().invoke(main, ["data", "status", "--root", str(root)])
    assert result.exit_code == 0
    assert "BTCUSDT" in result.output


def test_research_pit_universe_and_overlay_offline(tmp_path: Path, august_dir: Path) -> None:
    """--universe pit reads the membership table; research overlay writes the D-017 evidence report."""
    root = tmp_path / "data"
    _store_from_fixtures(august_dir, root)
    index = pd.DatetimeIndex(pd.read_parquet(august_dir / "BTCUSDT" / "1h.parquet")["open_time"], name="open_time")
    stamps = pd.to_datetime(index.to_numpy(), unit="ms", utc=True)
    membership = pd.DataFrame(
        [[True, True, True, False], [True, True, False, True]],
        index=pd.DatetimeIndex([stamps[0], stamps[len(stamps) // 2]]),
        columns=list(SYMBOLS),
    )
    membership.to_parquet(root / "membership.parquet")
    out = tmp_path / "reports"
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "research",
            "backtest",
            "--strategy",
            "tsmom",
            "--root",
            str(root),
            "--universe",
            "pit",
            "--out",
            str(out),
            "--no-funding",
            "--params",
            '{"vol_window": 100, "horizons": [5, 20, 50], "crowding_window": 0}',
            "--min-history",
            "0",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(next(out.glob("tsmom-backtest-*.json")).read_text())
    assert payload["universe_mode"] == "pit" and set(payload["symbols"]) == set(SYMBOLS)
    registry = tmp_path / "registry.yaml"
    registry.write_text(
        "version: 1\n"
        "ensemble: {method: mean}\n"
        "strategies:\n"
        "  - {id: tsmom, enabled: true, params: {vol_window: 100, horizons: [5, 20, 50], horizon_weights: [0.2, 0.3, 0.5]}}\n",
        encoding="utf-8",
    )
    result = runner.invoke(
        main,
        [
            "research",
            "overlay",
            "--root",
            str(root),
            "--symbols",
            ",".join(SYMBOLS),
            "--registry",
            str(registry),
            "--out",
            str(out),
            "--no-funding",
            "--min-history",
            "0",
            "--folds",
            "3",
            "--min-train",
            "300",
            "--exits-grid",
            '{"stop_loss": [0.0, 2.0], "take_profit": [0.0, 4.0]}',
            "--throttle-grid",
            '{"start": [0.02], "stop": [0.10], "floor": [0.5]}',
        ],
    )
    assert result.exit_code == 0, result.output
    overlay = json.loads(next(out.glob("overlay-*.json")).read_text())
    assert overlay["baseline"]["oos_sharpe"] is not None
    assert [row["kind"] for row in overlay["candidates"]] == ["exits", "exits", "exits", "throttle"]
    assert set(overlay["recommendation"]) == {"exits", "throttle"}
    # D-024: the report says which registry it decided against, so a later reader can tell if it expired
    fingerprint = overlay["registry"]
    assert len(fingerprint["digest"]) == 64 and fingerprint["ensemble_method"] == "mean"
    assert set(fingerprint["strategies"]) == set(overlay["strategies"])
    tsmom_params = fingerprint["strategies"]["tsmom"]["params"]
    assert tsmom_params["horizons"] == [5, 20, 50] and tsmom_params["vol_window"] == 100  # what this run used
    assert tsmom_params["conviction_mode"] == "score"  # an unwritten default is filled in, not left absent
    assert overlay["portfolio"]["max_weight"] > 0
    assert f"registry digest: {fingerprint['digest']}" in result.output
    assert "recommendation:" in result.output


def test_research_book_offline(tmp_path: Path, august_dir: Path, isolated_trials_ledger: Path) -> None:
    """research book writes the D-018 evidence report and charges the sleeve's standalone trial once."""
    root = tmp_path / "data"
    _store_from_fixtures(august_dir, root)
    out = tmp_path / "reports"
    registry = tmp_path / "registry.yaml"
    registry.write_text(
        "version: 1\n"
        "ensemble: {method: mean}\n"
        "strategies:\n"
        "  - {id: tsmom, enabled: true, params: {vol_window: 100, horizons: [5, 20, 50], horizon_weights: [0.2, 0.3, 0.5]}}\n"
        "  - {id: xsmom, enabled: false, params: {horizons: [5, 20, 50], horizon_weights: [0.2, 0.3, 0.5]}}\n",
        encoding="utf-8",
    )
    args = [
        "research",
        "book",
        "--main",
        "tsmom",
        "--sleeve",
        "xsmom",
        "--sleeve-params",
        '{"entry_threshold": 0.2}',
        "--root",
        str(root),
        "--symbols",
        ",".join(SYMBOLS),
        "--universe",
        "static",
        "--registry",
        str(registry),
        "--out",
        str(out),
        "--no-funding",
        "--min-history",
        "0",
        "--folds",
        "3",
        "--min-train",
        "300",
        "--purge",
        "5",
        "--cpcv-groups",
        "4",
        "--prior-trials",
        "3",
    ]
    runner = CliRunner()
    result = runner.invoke(main, args)
    assert result.exit_code == 0, result.output
    report = json.loads(next(out.glob("book-tsmom-xsmom-*.json")).read_text())
    assert report["book_verdict"] in {"ACCEPT", "REJECT"}
    assert report["sleeve"]["params"]["entry_threshold"] == 0.2
    decision = report["universes"]["static"]
    assert set(decision["by_fraction"]) == {"0.3333", "0.2000", "0.5000"}
    assert decision["sleeve_standalone"]["multiple_testing"]["n_trials"] == 4  # 3 declared + this one
    assert decision["sleeve_standalone"]["verdict"] in {"PASS", "WEAK_PASS", "FAIL"}
    assert "BOOK VERDICT" in result.output and "robustness universe not evaluated" in result.output
    # DL-K1: the ledger no longer lives under `--out`; pointing the reports elsewhere used to point
    # the accounting elsewhere with them.
    assert not (out / "trials.jsonl").exists()
    ledger = isolated_trials_ledger.read_text().splitlines()
    assert len(ledger) == 1 and json.loads(ledger[0])["strategy"] == "xsmom"
    # an exact replay is not a second trial
    result = runner.invoke(main, args)
    assert result.exit_code == 0, result.output
    assert "exact replay" in result.output
    assert len(isolated_trials_ledger.read_text().splitlines()) == 1
    replay = json.loads(sorted(out.glob("book-tsmom-xsmom-*.json"))[-1].read_text())
    assert replay["universes"]["static"]["sleeve_standalone"]["multiple_testing"]["n_trials"] == 4


def test_validate_reserves_a_holdout_tail(tmp_path: Path) -> None:
    """KILL-006: --holdout-months cuts the tail before folds and records the reservation in the report."""
    import numpy as np

    root = tmp_path / "data"
    store = KlineStore(root)
    step = 3_600_000
    bars = 24 * 30 * 6  # six months of hourly bars, so a one-month tail still leaves a training set
    base = 1_700_000_000_000 // step * step - bars * step
    rng = np.random.default_rng(11)
    for symbol in SYMBOLS:
        close = 100.0 * np.exp(np.cumsum(rng.normal(0.0, 0.004, bars)))
        opens = [base + i * step for i in range(bars)]
        store.append(
            symbol,
            "1h",
            pd.DataFrame(
                {
                    "open_time": opens,
                    "open": close,
                    "high": close * 1.001,
                    "low": close * 0.999,
                    "close": close,
                    "volume": np.full(bars, 1000.0),
                    "close_time": [o + step - 1 for o in opens],
                }
            ),
        )
    out = tmp_path / "reports"
    args = [
        "research",
        "validate",
        "--strategy",
        "tsmom",
        "--root",
        str(root),
        "--symbols",
        ",".join(SYMBOLS),
        "--out",
        str(out),
        "--no-funding",
        "--params",
        '{"horizons": [5, 20, 50], "vol_window": 100, "crowding_window": 0}',
        "--grid",
        "{}",
        "--folds",
        "3",
        "--min-train",
        "1000",
        "--purge",
        "5",
        "--cpcv-groups",
        "4",
        "--min-history",
        "0",
    ]
    runner = CliRunner()
    assert runner.invoke(main, args).exit_code == 0
    full = json.loads(sorted(out.glob("tsmom-validation-*.json"))[-1].read_text())
    assert full["holdout"] is None, "no reservation unless it is asked for"

    result = runner.invoke(main, [*args, "--holdout-months", "1"])
    assert result.exit_code == 0, result.output
    report_path = sorted(out.glob("tsmom-validation-*.json"))[-1]
    held = json.loads(report_path.read_text())
    assert held["holdout"]["months"] == 1 and held["holdout"]["bars_reserved"] > 600
    assert held["range"]["bars"] < full["range"]["bars"], "the reserved tail is genuinely absent from the run"
    assert pd.Timestamp(held["range"]["end"]) <= pd.Timestamp(held["holdout"]["start"])
    assert "Holdout" in report_path.with_suffix(".md").read_text()

    # asking for more than the data can spare is refused rather than silently ignored
    refused = runner.invoke(main, [*args, "--holdout-months", "600"])
    assert refused.exit_code != 0 and "leaves no training data" in str(refused.output) + str(refused.exception)


def test_cost_flag_and_grid_table(tmp_path: Path, august_dir: Path) -> None:
    """KILL-013 asks for a >40% cost share to be flagged; the plan asks the parameter grid to be visible."""
    from starquant_cli.research_cmd import _cost_flag, _grid_table

    assert _cost_flag(0.39) == "" and _cost_flag(None) == ""
    flagged = _cost_flag(0.55)
    assert "55%" in flagged and "KILL-013" in flagged

    params = {"a": {"window": 24, "scale": 0.05}, "b": {"window": 48, "scale": 0.05}}
    rows = _grid_table(params, {"a": 1.2, "b": 0.4})
    assert rows[0].startswith("window=24") and "sharpe=1.20" in rows[0], rows
    assert rows[1].startswith("window=48"), "ranked by Sharpe, best first"
    assert "scale" not in rows[0], "a parameter that does not vary is noise in the table"
    assert _grid_table({"only": {"window": 24}}, {"only": None}) == ["single configuration: sharpe=n/a"]

    root = tmp_path / "data"
    _store_from_fixtures(august_dir, root)
    out = tmp_path / "reports"
    result = CliRunner().invoke(
        main,
        [
            "research",
            "validate",
            "--strategy",
            "tsmom",
            "--root",
            str(root),
            "--symbols",
            ",".join(SYMBOLS),
            "--out",
            str(out),
            "--no-funding",
            "--params",
            '{"horizons": [5, 20, 50], "crowding_window": 0}',
            "--grid",
            '{"vol_window": [100, 200]}',
            "--folds",
            "3",
            "--min-train",
            "300",
            "--purge",
            "5",
            "--cpcv-groups",
            "4",
            "--min-history",
            "0",
        ],
    )
    assert result.exit_code == 0, result.output
    markdown = sorted(out.glob("tsmom-validation-*.md"))[-1].read_text()
    assert "Grid (full-sample Sharpe per configuration)" in markdown
    assert "vol_window=100" in markdown and "vol_window=200" in markdown
    assert "parameter_neighbourhood" in markdown
    # The three caveats have to travel WITH their numbers (2026-09-14 audit): each one existed in the
    # tree already and was quoted without itself.  This grid has two configurations, so the PBO note
    # must be the "not informative" branch - the exact case the audit caught being cited as a cost.
    assert "selection contamination" in markdown, "CPCV's embargo caveat must print beside fraction_negative"
    assert "structural bound, not a measurement" in markdown, "the margin buffer's bound must print beside it"
    assert "NOT informative and NOT enforced at grid_trials=2" in markdown, "PBO below four is a coin flip"
    # The gate is an OOS number and `cost_stress` is a full-sample one; before this they could only be
    # compared by subtracting two different sample sizes.  x1 must reproduce the headline gate exactly.
    assert "Cost stress against that gate" in markdown
    payload = json.loads(sorted(out.glob("tsmom-validation-*.json"))[-1].read_text())
    gate = payload["cost_stress_gate"]
    assert set(gate) == {"x1", "x1.5", "x2"}
    # x1 is the SHIPPED configuration's OOS series (F3), not the fold-selected mixture the headline
    # gate reads - they differ whenever the folds disagreed, which this fixture's grid does.
    assert gate["x1"]["oos_sharpe"] == pytest.approx(payload["best_key_oos_sharpe"])
    assert gate["x2"]["oos_sharpe"] < gate["x1"]["oos_sharpe"], "paying more cannot help the OOS Sharpe"
    for level in gate.values():
        assert level["margin"] == pytest.approx(level["oos_sharpe"] - level["threshold"])


def _mine(root: Path, out: Path, *extra: str) -> tuple[int, str, dict]:
    """Run `research mine` on the August fixtures and read the report back.

    The funding flags are NOT fixed here: F-1's whole subject is what happens when they disagree with the
    panel, so a helper that pinned them would make that case unreachable from the tests.
    """
    result = CliRunner().invoke(
        main,
        [
            "research",
            "mine",
            "--strategy",
            "tsmom",
            "--root",
            str(root),
            "--symbols",
            ",".join(SYMBOLS),
            "--out",
            str(out),
            "--max-lookback",
            "200",
            "--min-history",
            "24",
            "--top",
            "3",
            *extra,
        ],
    )
    reports = sorted(out.glob("mine-shortlist-*.json"))
    payload = json.loads(reports[-1].read_text()) if reports else {}
    return result.exit_code, result.output, payload


def test_mine_records_the_parameters_of_its_own_run(tmp_path: Path, august_dir: Path) -> None:
    """DL-P17-04: the report rebuilds its own command line, which P14's could not (D-024 applied to mine)."""
    root = tmp_path / "data"
    _store_from_fixtures(august_dir, root)
    out = tmp_path / "reports"
    code, output, payload = _mine(root, out, "--no-funding", "--no-include-funding")
    assert code == 0, output

    run = payload["run"]
    assert run["funding"] is False
    assert run["include_funding"] is False
    assert run["execution"] == "open_to_close"
    assert run["max_complexity"] == 10
    assert run["max_lookback"] == 200
    assert run["min_history_bars"] == 24  # the resolved value, not the raw option
    assert run["baseline"] is None
    assert run["root"] == str(root)
    assert "vol_target" in run["portfolio"]
    # The cost model lives at the top level, as it does in every other report this file writes; `run`
    # records the path it was loaded from, not a second copy of the resolved object.
    assert payload["costs"]["use_funding"] is False
    assert run["costs_path"].endswith("costs.yaml")

    # Every enumerated candidate is accounted for exactly once, which is what makes declared_trials honest.
    outcomes = payload["outcomes"]
    assert outcomes["scored"] + outcomes["errored"] + outcomes["never_traded"] == len(payload["candidates"])
    assert outcomes["scored"] > 0  # or the identity above holds vacuously
    # The achievable form of pre-registered rule 2: every counted expression lands in exactly one bucket.
    # `scored == evaluated` as frozen cannot hold, because `evaluated` fires before the caps drop anything.
    assert outcomes["accounted"] == outcomes["evaluated"] == payload["evaluated"]
    assert outcomes["dropped_by_caps"] > 0  # --max-lookback 200 drops most of them, so this is not vacuous
    assert run["ranked_by"] == "sharpe"  # no baseline given
    assert payload["declared_trials"] == payload["evaluated"]
    assert payload["baseline"] is None
    # Stamped: two runs differing only in their flags must not overwrite each other's evidence.
    assert sorted(out.glob("mine-shortlist-*.json"))[-1].name != "mine-shortlist.json"


def test_mine_compares_every_candidate_against_a_named_baseline(tmp_path: Path, august_dir: Path) -> None:
    """DL-P17-05: the question is a second uncorrelated book, so the marginal is the quantity to rank on.

    The baseline here is a mined id rather than ``tsmom``, for two reasons: this fixture is 720 bars and
    tsmom's registry horizons reach 720, so it produces no decisions at all on it; and a mined baseline
    also exercises the ``_resolve_mined`` call, without which ``_entry`` raises a bare ``KeyError``.
    """
    root = tmp_path / "data"
    _store_from_fixtures(august_dir, root)
    out = tmp_path / "reports"
    # A price-only tree on purpose: this fixture carries OHLCV alone, so quote_volume and
    # taker_buy_quote arrive as all-NaN frames and any flow candidate scores nothing.
    mock_candidate = Candidate.of(Squash(Ratio(Ret(24), Vol(48)), 1.0))
    baseline_id, mock_hash, mock_expr = f"mined_{mock_candidate.hash}", mock_candidate.hash, str(mock_candidate.expr)
    # Scoped to the pre-DL-A1 space with --grids.  The fixture's job is to separate a marginal ranking
    # from a standalone one, and the five new families changed which candidates reach the top three -
    # the guard below caught exactly that.  Narrowing here keeps the test testing what it was written
    # for; the new families get their own evidence from the pre-registered run, not from this fixture.
    code, output, payload = _mine(
        root,
        out,
        "--no-funding",
        "--no-include-funding",
        "--baseline",
        baseline_id,
        "--grids",
        '{"include_panel_nodes": false}',
    )
    assert code == 0, output

    assert payload["run"]["baseline"] == baseline_id
    assert payload["baseline"]["strategy"] == baseline_id
    # KILL-P17-06's mitigation: naming the strategy is not enough, because the registry moves and a
    # marginal measured against one configuration is a different number from the same strategy under
    # another, with nothing in the artefact to separate them.
    assert payload["baseline"]["params"] == {"entry_threshold": 0.2, "expression": mock_expr, "hash": mock_hash}
    assert payload["baseline"]["sharpe"] is not None
    assert payload["baseline"]["max_drawdown"] is not None
    assert "NOT the risk-budgeted" in payload["baseline"]["marginal"]

    scored = [row for row in payload["candidates"] if row.get("sharpe") is not None]
    assert scored
    for row in scored:
        assert "baseline_correlation" in row
        assert "baseline_marginal_sharpe" in row
        assert row["baseline_bars"] > 0
    # The error rows must stay clean: `scored` filters on sharpe, so a baseline key there would be a lie.
    for row in payload["candidates"]:
        if "error" in row:
            assert "baseline_correlation" not in row
    assert "| marginal | corr |" in sorted(out.glob("mine-shortlist-*.md"))[-1].read_text()

    # Pre-registered rule 6: with a baseline the shortlist ranks on the MARGINAL, not the full-sample
    # Sharpe.  Ranking on the absolute number is what produces a false "the space is empty" verdict - the
    # best absolute candidate is usually the one most correlated with the book already running.
    assert payload["run"]["ranked_by"] == "baseline_marginal_sharpe"
    by_marginal = [row["hash"] for row in sorted(scored, key=lambda row: -row["baseline_marginal_sharpe"])]
    by_sharpe = [row["hash"] for row in sorted(scored, key=lambda row: -row["sharpe"])]
    printed = [
        line.split("|")[1].strip()
        for line in sorted(out.glob("mine-shortlist-*.md"))[-1].read_text().splitlines()[2:]
        if line.startswith("|")
    ]
    assert printed and printed == by_marginal[: len(printed)]
    assert printed != by_sharpe[: len(printed)], (
        "this fixture no longer separates the two rankings, so the assertion above proves nothing"
    )


def test_mine_narrows_the_space_instead_of_searching_a_family_the_panel_cannot_answer(
    tmp_path: Path, august_dir: Path, fixtures_dir: Path
) -> None:
    """F-1: the carry family is neither searched nor charged when there is nothing to search.

    The flags here are the ones an operator gets by DEFAULT: --funding and --include-funding are both on,
    and the August store has no funding archive.  Three weaker guards would all pass this and let the
    whole family run on constants:

      * checking the CLI flag - it says funding was requested, not that any arrived;
      * checking ``panel.funding is not None`` - ``_load`` returns an all-zero frame, not None;
      * refusing outright - which the contract explicitly did not ask for, and which would make `mine`
        unrunnable on every OHLCV-only panel in this suite.

    What the guard must do instead is narrow, and say in the artefact that it narrowed.  Without that,
    the report records ``include_funding: true`` over 42 expressions that read nothing but zeros while
    still being charged to ``--prior-trials`` - KILL-027 standing inside the guard written to stop it.
    """
    root = tmp_path / "data"
    _store_from_fixtures(august_dir, root)
    out = tmp_path / "reports"
    code, output, payload = _mine(root, out, "--funding")
    assert code == 0, output
    assert "narrowing the search space" in output

    run = payload["run"]
    assert run["include_funding"] is False  # what was searched
    assert run["include_funding_requested"] is True  # what was asked for
    # The evidence for the difference is recorded once, at the top level, where every report carries it.
    assert payload["funding_inputs"]["symbols_settled"] == 0
    assert payload["funding_inputs"]["panel_carried"] is True  # a frame arrived; it just said nothing

    # DL-D5 added a second narrowing of the same kind and this OHLCV-only panel triggers both: it has no
    # settlement AND no spot leg.  So the reference has both dimensions off - keeping it pinned to the
    # enumerator, which is the whole point of not writing a literal here.
    assert run["include_basis"] is False
    assert payload["run"]["spot_symbols"] == 0
    assert "the basis family is neither searched" in output

    # Neither searched nor charged.  Pinned to the enumerator with the carry dimension off, rather than
    # to a literal or to the frozen fixture: DL-A1 added five more families, and an assertion on the
    # absolute total would make "the space grew" and "carry leaked in" the same failure.
    without_carry = enumerate_candidates(include_funding=False, include_basis=False)
    assert payload["evaluated"] == without_carry.evaluated
    assert payload["declared_trials"] == without_carry.evaluated
    assert without_carry.evaluated < enumerate_candidates(include_funding=True, include_basis=False).evaluated
    assert without_carry.evaluated < enumerate_candidates(include_funding=False, include_basis=True).evaluated
    assert not any("funding(" in row["expression"] for row in payload["candidates"])
    assert not any("basis" in row["expression"] for row in payload["candidates"])


def _store_spot_from_fixtures(august_dir: Path, root: Path) -> None:
    """The same August bars one market over, each symbol at its own discount, plus the map pairing them.

    A DIFFERENT discount per symbol and not one shared constant: `basis` is a level whose zero
    no-arbitrage fixes in the same place for every symbol, so a single ratio would make the leaf
    identical across the panel and `cross_sectional_rank` would rank ties.  The family would enumerate
    and score nothing, which looks from the report exactly like the defect these tests are about.
    """
    from starquant_data.spot import SpotMapping, write_spot_map
    from starquant_data.store import SPOT_KLINE_KIND

    store = KlineStore(root, kind=SPOT_KLINE_KIND)
    for index, symbol in enumerate(SYMBOLS):
        frame = pd.read_parquet(august_dir / symbol / "1h.parquet")
        frame["close_time"] = frame["open_time"] + 3_600_000 - 1
        for column in ("open", "high", "low", "close"):
            frame[column] = frame[column] * (1.0 - 0.001 * (index + 1))
        store.append(symbol, "1h", frame)
    write_spot_map(root, {symbol: SpotMapping(symbol, symbol, 1.0) for symbol in SYMBOLS})


def _basis_candidate() -> Candidate:
    """The simplest shape that reads spot: `cs_rank(basis / vol(48))`, pinned by its own predicate."""
    return next(c for c in enumerate_candidates(include_basis=True).candidates if c.expr.reads_spot())


def test_mine_searches_the_basis_family_once_the_root_carries_spot(
    tmp_path: Path, august_dir: Path, isolated_trials_ledger: Path
) -> None:
    """The positive control for the narrowing above, and the DL-D5 defect stated as a test.

    `searched_basis = panel.spot_symbols > 0` was right the whole time; what was wrong was that `_load`
    built no spot store, so no panel `mine` could construct carried spot and the predicate answered
    False on every run.  Eighteen shapes, never enumerated, and the artefact said so truthfully - which
    is why it survived: `include_basis: false` reads as "the family lost", not as "nobody asked it".
    """
    root = tmp_path / "data"
    _store_from_fixtures(august_dir, root)
    _store_spot_from_fixtures(august_dir, root)
    out = tmp_path / "reports"

    code, output, payload = _mine(root, out, "--no-funding", "--no-include-funding")

    assert code == 0, output
    assert payload["run"]["include_basis"] is True
    assert payload["run"]["spot_symbols"] == len(SYMBOLS)
    assert "the basis family is neither searched" not in output

    # Charged as well as searched: the 18 shapes are hypotheses and they raise the bar for everything
    # promoted out of this run.  Pinned to the enumerator, so "the family grew" cannot pass as "the
    # panel changed".
    without_basis = enumerate_candidates(include_funding=False, include_basis=False)
    with_basis = enumerate_candidates(include_funding=False, include_basis=True)
    assert payload["declared_trials"] == with_basis.evaluated
    assert with_basis.evaluated - without_basis.evaluated == 18
    scored = [row for row in payload["candidates"] if "basis" in row["expression"]]
    assert scored, "the family was declared searched and left no row"
    assert not any(row.get("error") for row in scored), [row.get("error") for row in scored]


def test_validate_loads_spot_only_for_a_strategy_that_declares_it_reads_spot(
    tmp_path: Path, august_dir: Path, isolated_trials_ledger: Path
) -> None:
    """`validate` is where a mined candidate becomes evidence, so this is the seam the shortlist walks
    into.  Both directions are asserted: the same command on a root with no spot must FAIL, because a
    guard that cannot be observed to bite is one nobody can tell is wired."""
    from starquant_cli.research_cmd import _wants_metrics, _wants_spot

    basis = _basis_candidate()
    _resolve_mined(f"mined_{basis.hash}", "")
    assert _wants_spot(f"mined_{basis.hash}", {}) is True
    assert _wants_metrics(f"mined_{basis.hash}", {}) is False, "spot must not drag the metrics alignment in"
    assert _wants_spot("tsmom", {}) is False

    def _validate(root: Path) -> tuple[int, str]:
        result = CliRunner().invoke(
            main,
            [
                "research",
                "validate",
                "--strategy",
                f"mined_{basis.hash}",
                "--root",
                str(root),
                "--symbols",
                ",".join(SYMBOLS),
                "--out",
                str(tmp_path / "reports"),
                "--no-funding",
                "--folds",
                "2",
                "--min-train",
                "300",
                "--purge",
                "5",
                "--cpcv-groups",
                "3",
                "--min-history",
                "0",
            ],
        )
        return result.exit_code, str(result.output) + str(result.exception)

    bare = tmp_path / "bare"
    _store_from_fixtures(august_dir, bare)
    code, output = _validate(bare)
    assert code != 0 and "does not carry" in output, output

    carrying = tmp_path / "carrying"
    _store_from_fixtures(august_dir, carrying)
    _store_spot_from_fixtures(august_dir, carrying)
    code, output = _validate(carrying)
    assert code == 0, output


def _store_with_balanced_flow(august_dir: Path, root: Path) -> None:
    """The August bars plus a quote volume whose taker flow is exactly balanced.

    ``takerbuy(w)`` is the taker-buy SHARE minus 0.5, so a store where buys are exactly half of volume
    makes every flow candidate score a constant zero: below ``entry_threshold``, so the weights are all
    zero, the net is all zero, and ``sharpe`` returns None.  That is the "enumerated but never traded"
    state - a candidate charged to ``declared_trials`` that leaves no row in the table and raises no
    error - and it is the only way to exercise it deterministically.
    """
    store = KlineStore(root)
    for symbol in SYMBOLS:
        frame = pd.read_parquet(august_dir / symbol / "1h.parquet")
        frame["close_time"] = frame["open_time"] + 3_600_000 - 1
        frame["quote_volume"] = frame["volume"] * frame["close"]
        frame["taker_buy_quote"] = frame["quote_volume"] * 0.5
        store.append(symbol, "1h", frame)


def test_mine_counts_the_candidates_that_enumerate_but_never_trade(tmp_path: Path, august_dir: Path) -> None:
    """The third bucket, exercised non-zero - the accounting identity is vacuous while it stays at 0.

    Before the `outcomes` block these rows were in `candidates` with a null Sharpe and in no count at
    all: `scored` filtered them out of the table and the only stdout line counted evaluation errors, so
    a family that enumerated and never traded was discoverable only by re-deriving it from the array,
    while every one of its members was billed to `--prior-trials`.
    """
    root = tmp_path / "data"
    _store_with_balanced_flow(august_dir, root)
    out = tmp_path / "reports"
    code, output, payload = _mine(root, out, "--no-funding", "--no-include-funding")
    assert code == 0, output

    outcomes = payload["outcomes"]
    assert outcomes["never_traded"] > 0
    assert outcomes["scored"] + outcomes["errored"] + outcomes["never_traded"] == len(payload["candidates"])
    assert outcomes["scored"] > 0
    assert "enumerated but never traded" in output

    # They are exactly the rows with neither a Sharpe nor an error, and they are billed all the same.
    silent = [row for row in payload["candidates"] if "error" not in row and row.get("sharpe") is None]
    assert len(silent) == outcomes["never_traded"]
    assert all("takerbuy(" in row["expression"] for row in silent)
    assert payload["declared_trials"] == payload["evaluated"]


def test_mine_refuses_a_baseline_that_consumes_funding_the_panel_does_not_have(
    tmp_path: Path, august_dir: Path
) -> None:
    """D-023 holds for `targets` but not for `evaluate`, so the research path needs its own refusal.

    tsmom's registry params carry `crowding_window: 72`, so `needs_funding` is True.  Without this the
    baseline book would be computed with the modifier silently inert - E-040 / KILL-027 - and every
    candidate's marginal Sharpe would be measured against a book nobody validated.
    """
    root = tmp_path / "data"
    _store_from_fixtures(august_dir, root)
    out = tmp_path / "reports"
    code, output, _ = _mine(root, out, "--funding", "--baseline", "tsmom")
    assert code == 1
    assert "tsmom consumes funding history" in output
    assert "holds no settlement for any of the" in output
    # Narrowing runs first and is not a substitute: it removes the carry FAMILY from the search, which
    # says nothing about a baseline the operator named by hand.
    assert "narrowing the search space" in output


def test_a_mined_carry_id_still_resolves_to_a_signal(tmp_path: Path, august_dir: Path) -> None:
    """`_resolve_mined` re-derives an id from a bare `enumerate_candidates()`, carry hashes included.

    It resolves only because `include_funding` defaults True in the library.  Flip that default and every
    carry hash becomes one that `research correlate` reports as gone - silently, because the docstring's
    promise ("a hash that no longer enumerates is reported as gone") reads identically either way.

    Using such an id as a `--baseline` is a separate matter and is refused on a settlement-free panel by
    the test above: a mined carry tree consumes funding exactly as tsmom's modifier does.
    """
    mined_id = f"mined_{Candidate.of(Squash(Ratio(Funding(24), Vol(48)), 1.0)).hash}"
    _resolve_mined(mined_id)  # raises ClickException if the hash no longer enumerates
    assert get_signal(mined_id).needs_funding({}) is True


def test_mine_refuses_to_write_a_report_whose_arithmetic_does_not_close(
    tmp_path: Path, august_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The accounting identity is enforced, not merely reported.

    A defensive check can only be exercised by breaking what it checks, so the enumerator is patched to
    over-report `evaluated` by one.  Without this the `raise` could be deleted and nothing would notice
    until a real run silently produced an artefact that bills more trials than it accounts for - and
    `--prior-trials` is the number the whole promotion gate is scaled by.
    """
    from starquant_cli import research_mine_cmd

    real = research_mine_cmd.enumerate_candidates

    def inflated(**kwargs: object) -> object:
        result = real(**kwargs)  # type: ignore[arg-type]
        return dataclasses.replace(result, evaluated=result.evaluated + 1)

    # M6 之后这个名字读在哪就打在哪：`research_cmd` 只是它的历史地址，打在再导出上不会影响真正的调用点。
    monkeypatch.setattr(research_mine_cmd, "enumerate_candidates", inflated)
    root = tmp_path / "data"
    _store_from_fixtures(august_dir, root)
    code, output, _ = _mine(root, tmp_path / "reports", "--no-funding", "--no-include-funding")
    assert code == 1
    assert "does not account for itself" in output


def test_every_command_can_address_a_mined_candidate(
    tmp_path: Path, august_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`_entry` is the one chokepoint every strategy id passes through, so resolution belongs there.

    It used to be wired into `correlate` alone, so `research validate --strategy mined_<hash>` raised a
    bare KeyError - the wall an operator hits the moment the shortlist hands them something worth
    validating, which is exactly what a shortlist is for.

    The registry entry is removed first, and that is not ceremony: `register` mutates a process-global
    dict, every `research mine` in this file registers all 267 candidates into it, and without this the
    test passes on another test's side effect.  Measured - it did, until the deletion was added.
    """
    root = tmp_path / "data"
    _store_from_fixtures(august_dir, root)
    mined_id = f"mined_{Candidate.of(Squash(Ratio(Ret(24), Vol(48)), 1.0)).hash}"
    monkeypatch.delitem(SIGNALS, mined_id, raising=False)
    result = CliRunner().invoke(
        main,
        [
            "research",
            "backtest",
            "--strategy",
            mined_id,
            "--root",
            str(root),
            "--symbols",
            ",".join(SYMBOLS),
            "--out",
            str(tmp_path / "reports"),
            "--no-funding",
            "--min-history",
            "24",
        ],
    )
    assert result.exit_code == 0, result.output
    assert sorted((tmp_path / "reports").glob(f"{mined_id}-backtest-*.json"))


# --- E-040 / KILL-027 on the research path ---------------------------------------------------------
# `AlphaModel.targets` refuses a funding-consuming model without funding history (D-023); the research
# path did not, so under `--no-funding` tsmom's crowding modifier ran inert and the report cited
# `crowding_window: 72` for a configuration that never ran.  The registry is passed explicitly because
# that is the premise of these tests: tsmom's *registry* params are what set `crowding_window`.
REPO = Path(__file__).resolve().parents[2]
REGISTRY = str(REPO / "config" / "alpha_registry.yaml")
# What the offline fixture (720 bars) can actually score; the registry's weekly horizons cannot.
SHORT_HORIZONS = '{"vol_window": 100, "horizons": [5, 20, 50]}'

# One invocation per research command that offers `--funding/--no-funding`, minus the exemptions below.
# `--min-history 0` is per-command: `correlate` does not take it, and `overlay` does not need it here -
# its guard fires on the panel before any history floor matters.
_SHORT = ["--strategy", "tsmom", "--params", SHORT_HORIZONS, "--min-history", "0"]
FUNDING_COMMANDS: dict[str, list[str]] = {
    "backtest": _SHORT,
    "validate": _SHORT,
    "diagnose": _SHORT,
    "decompose": _SHORT,
    "correlate": ["--strategies", "tsmom"],
    "overlay": [],
    "book": ["--main", "tsmom", "--sleeve", "breakout", "--universe", "static", "--min-history", "0"],
}
# `mine` takes `--funding` but ignores `--strategy`: its candidates are the strategies, and no enumerated
# candidate reads funding on this branch.  Its baseline arm is guarded where the baseline is introduced.
# `list` used to sit here too and never belonged - it carries no `--funding` at all, so subtracting it was
# silently a no-op, which is exactly how an exemption set rots.  The membership assertion below is what
# stops the next stale entry from being invisible.
EXEMPT_FROM_FUNDING_GUARD = {"mine"}


def _research_args(command: str, extra: list[str], root: Path, out: Path) -> list[str]:
    common = ["--root", str(root), "--symbols", ",".join(SYMBOLS), "--registry", REGISTRY, "--out", str(out)]
    return ["research", command, *extra, *common, "--no-funding"]


def test_the_funding_command_table_covers_every_command_that_takes_the_flag() -> None:
    """A new research command with `--funding` must join the table above, not arrive silently unguarded."""
    from starquant_cli import research

    with_flag = {
        name
        for name, command in research.commands.items()
        if any("--funding" in (param.opts + param.secondary_opts) for param in command.params)
    }
    assert with_flag >= EXEMPT_FROM_FUNDING_GUARD, "an exemption for a command that has no flag exempts nothing"
    assert with_flag - EXEMPT_FROM_FUNDING_GUARD == set(FUNDING_COMMANDS)


def test_backtest_does_not_exit_zero_while_the_registry_makes_tsmom_consume_funding(
    tmp_path: Path, august_dir: Path
) -> None:
    """The sharp case: this exact invocation exited 0 and reported a Sharpe of 4.34 for an inert modifier."""
    root = tmp_path / "data"
    _store_from_fixtures(august_dir, root)
    out = tmp_path / "reports"
    result = CliRunner().invoke(main, _research_args("backtest", FUNDING_COMMANDS["backtest"], root, out))
    assert result.exit_code != 0, result.output
    assert "--funding" in result.output and "tsmom" in result.output, result.output
    assert not list(out.glob("*.json")), "a refused run must not leave evidence behind"


@pytest.mark.parametrize(("command", "extra"), sorted(FUNDING_COMMANDS.items()))
def test_every_research_command_refuses_a_funding_consuming_strategy_without_funding(
    command: str, extra: list[str], tmp_path: Path, august_dir: Path
) -> None:
    root = tmp_path / "data"
    _store_from_fixtures(august_dir, root)
    out = tmp_path / "reports"
    result = CliRunner().invoke(main, _research_args(command, extra, root, out))
    # The message, not the exit code, is what proves the guard: several of these commands already fail on
    # this short fixture for unrelated reasons, and a refusal that names `--funding` cannot be one of those.
    assert "--funding" in result.output, f"{command} did not refuse:\n{result.output}"
    assert result.exit_code != 0
    assert not list(out.glob("*.json")), f"{command} wrote evidence it should have refused"


def test_the_control_arm_still_runs_without_funding(tmp_path: Path, august_dir: Path) -> None:
    """`crowding_window: 0` reads no funding, so `--no-funding` *is* the configuration it was judged on."""
    root = tmp_path / "data"
    _store_from_fixtures(august_dir, root)
    out = tmp_path / "reports"
    control = '{"vol_window": 100, "horizons": [5, 20, 50], "crowding_window": 0}'
    args = _research_args("backtest", ["--strategy", "tsmom", "--params", control, "--min-history", "0"], root, out)
    result = CliRunner().invoke(main, args)
    assert result.exit_code == 0, result.output
    assert len(list(out.glob("tsmom-backtest-*.json"))) == 1


def _funding_for(august_dir: Path, root: Path, symbols: tuple[str, ...]) -> None:
    """Settlements every 8 bars for `symbols` only; the rest of the universe gets no archive at all."""
    stamps = pd.read_parquet(august_dir / "BTCUSDT" / "1h.parquet")["open_time"].to_numpy()[::8]
    store = FundingStore(root)
    for symbol in symbols:
        store.append(
            symbol,
            pd.DataFrame(
                {"funding_time": stamps, "funding_rate": [0.0001] * len(stamps), "mark_price": [1.0] * len(stamps)}
            ),
        )


def test_a_report_records_what_the_signals_required_of_funding_and_what_the_panel_carried(
    tmp_path: Path, august_dir: Path
) -> None:
    """The residual hole the guard cannot see: `--funding` against a partial archive is inert again.

    The panel carries a funding frame, so the guard is satisfied, but two of the four symbols have no
    settlement in it - and tsmom's crowding rank reads an unobserved symbol as uncrowded rather than
    failing.  Reports record the cost model's `use_funding` and nothing about the signals' own
    requirement, so nothing on disk distinguished that from a modifier that was never configured.
    """
    root = tmp_path / "data"
    _store_from_fixtures(august_dir, root)
    _funding_for(august_dir, root, ("BTCUSDT", "ETHUSDT"))
    out = tmp_path / "reports"
    args = [
        "research",
        "backtest",
        "--strategy",
        "tsmom",
        "--root",
        str(root),
        "--symbols",
        ",".join(SYMBOLS),
        "--registry",
        REGISTRY,
        "--out",
        str(out),
        "--funding",
        "--min-history",
        "0",
        "--params",
        SHORT_HORIZONS,
    ]
    result = CliRunner().invoke(main, args)
    assert result.exit_code == 0, result.output
    payload = json.loads(next(out.glob("tsmom-backtest-*.json")).read_text())
    assert payload["funding_inputs"] == {
        "required_by": ["tsmom"],
        "panel_carried": True,
        "symbols_settled": 2,
        "panel_symbols": 4,
    }

    assert payload["costs"]["use_funding"] is True  # the cost model's flag stays what it was


def test_a_control_arm_report_says_no_signal_required_funding(tmp_path: Path, august_dir: Path) -> None:
    """`required_by: []` beside `panel: false` is the reading that used to be unavailable: absent, not inert."""
    root = tmp_path / "data"
    _store_from_fixtures(august_dir, root)
    out = tmp_path / "reports"
    control = '{"vol_window": 100, "horizons": [5, 20, 50], "crowding_window": 0}'
    args = _research_args("backtest", ["--strategy", "tsmom", "--params", control, "--min-history", "0"], root, out)
    assert CliRunner().invoke(main, args).exit_code == 0
    payload = json.loads(next(out.glob("tsmom-backtest-*.json")).read_text())
    assert payload["funding_inputs"] == {
        "required_by": [],
        "panel_carried": False,
        "symbols_settled": 0,
        "panel_symbols": 4,
    }


def test_research_refuses_when_the_funding_archive_holds_no_settlement_at_all(tmp_path: Path, august_dir: Path) -> None:
    """`--funding` is the DEFAULT, and against an unsynced archive it is as inert as `--no-funding`.

    `FundingStore.load` returns an empty frame per symbol, so `load_panel` builds a funding frame of all
    zeros - not `None` - and neither `panel.funding is None` guard can tell that from real data.  tsmom's
    crowding rank then reads every symbol as uncrowded and the run writes the exact report E-040 is about:
    exit 0, `params.crowding_window: 72`, and a Sharpe for a modifier that consumed nothing.
    """
    root = tmp_path / "data"
    _store_from_fixtures(august_dir, root)  # klines synced, funding never pulled
    out = tmp_path / "reports"
    args = [
        "research",
        "backtest",
        "--strategy",
        "tsmom",
        "--root",
        str(root),
        "--symbols",
        ",".join(SYMBOLS),
        "--registry",
        REGISTRY,
        "--out",
        str(out),
        "--funding",
        "--min-history",
        "0",
        "--params",
        SHORT_HORIZONS,
    ]
    result = CliRunner().invoke(main, args)
    assert result.exit_code != 0, result.output
    assert "no settlement" in result.output and "tsmom" in result.output, result.output
    assert not list(out.glob("*.json")), "a refused run must not leave evidence behind"


def test_partial_funding_coverage_is_announced_rather_than_left_in_the_json(tmp_path: Path, august_dir: Path) -> None:
    """Some settlement is not zero settlement, so it runs - but the operator is told, not just the file."""
    root = tmp_path / "data"
    _store_from_fixtures(august_dir, root)
    _funding_for(august_dir, root, ("BTCUSDT", "ETHUSDT"))
    out = tmp_path / "reports"
    args = [
        "research",
        "backtest",
        "--strategy",
        "tsmom",
        "--root",
        str(root),
        "--symbols",
        ",".join(SYMBOLS),
        "--registry",
        REGISTRY,
        "--out",
        str(out),
        "--funding",
        "--min-history",
        "0",
        "--params",
        SHORT_HORIZONS,
    ]
    result = CliRunner().invoke(main, args)
    assert result.exit_code == 0, result.output
    assert "2/4" in result.output and "tsmom" in result.output, result.output


def test_validate_guards_the_grid_arms_rather_than_the_base_params(tmp_path: Path, august_dir: Path) -> None:
    """`research validate` deliberately checks the combos, not `entry.params` — in both directions.

    The dangerous half is a base configuration that reads no funding with a grid arm that does: guarding
    the base would let that arm be scored on a panel with none, and write a two-arm validation report —
    the registry's own evidence format — in which the "on" arm consumed nothing and so ties the "off" arm.
    The permissive half matters too: a grid that switches the term off in every arm must not be refused
    for a base configuration it never evaluates.
    """
    root = tmp_path / "data"
    _store_from_fixtures(august_dir, root)
    out = tmp_path / "reports"
    base = [
        "research",
        "validate",
        "--strategy",
        "tsmom",
        "--root",
        str(root),
        "--symbols",
        ",".join(SYMBOLS),
        "--registry",
        REGISTRY,
        "--out",
        str(out),
        "--no-funding",
        "--min-history",
        "0",
        "--folds",
        "3",
        "--min-train",
        "300",
        "--purge",
        "5",
        "--cpcv-groups",
        "4",
    ]
    control = '{"horizons": [5, 20, 50], "vol_window": 100, "crowding_window": 0}'
    # an arm that reads funding is refused even though the base params do not
    refused = CliRunner().invoke(main, [*base, "--params", control, "--grid", '{"crowding_window": [0, 72]}'])
    assert refused.exit_code != 0, refused.output
    assert "--funding" in refused.output and "tsmom" in refused.output, refused.output
    assert not list(out.glob("*.json")), "a refused run must not leave evidence behind"
    # ...and a grid that switches it off in every arm runs, though the base params turn it on
    crowded = '{"horizons": [5, 20, 50], "vol_window": 100, "crowding_window": 72}'
    allowed = CliRunner().invoke(main, [*base, "--params", crowded, "--grid", '{"crowding_window": [0]}'])
    assert allowed.exit_code == 0, allowed.output
    payload = json.loads(next(out.glob("tsmom-validation-*.json")).read_text())
    assert payload["funding_inputs"]["required_by"] == [] and payload["grid_size"] == 1


@pytest.mark.parametrize("command", ["backtest", "validate", "decompose"])
def test_the_funding_block_reaches_the_reports_the_registry_reads(
    command: str, tmp_path: Path, august_dir: Path
) -> None:
    """Only backtest's block was ever produced during a test run; `validate` is what `evidence` points at."""
    root = tmp_path / "data"
    _store_from_fixtures(august_dir, root)
    _funding_for(august_dir, root, ("BTCUSDT", "ETHUSDT"))
    out = tmp_path / "reports"
    extra = ["--folds", "3", "--min-train", "300", "--purge", "5"] if command != "backtest" else []
    extra += ["--grid", "{}"] if command == "validate" else []
    result = CliRunner().invoke(
        main,
        [
            "research",
            command,
            "--strategy",
            "tsmom",
            "--root",
            str(root),
            "--symbols",
            ",".join(SYMBOLS),
            "--registry",
            REGISTRY,
            "--out",
            str(out),
            "--funding",
            "--min-history",
            "0",
            "--params",
            SHORT_HORIZONS,
            *extra,
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(next(out.glob("*.json")).read_text())
    assert payload["funding_inputs"] == {
        "required_by": ["tsmom"],
        "panel_carried": True,
        "symbols_settled": 2,
        "panel_symbols": 4,
    }
    if "dataset" in payload:
        # the two must stay distinguishable: `dataset.funding` counts FILES in the archive (D-040),
        # `funding_inputs` counts settled columns in the panel.  Here both read 2, from different things.
        assert set(payload["dataset"]["funding"]) == {"bytes", "fingerprint", "symbols"}
        assert "funding" not in payload, "a second top-level `funding` block would re-create the collision"


def _short_registry(path: Path, *, crowding: int) -> Path:
    """Two strategies the 720-bar fixture can actually score; tsmom's crowding term is the funding read."""
    path.write_text(
        "version: 1\n"
        "ensemble: {method: mean}\n"
        "strategies:\n"
        f"  - {{id: tsmom, enabled: true, params: {{vol_window: 100, horizons: [5, 20, 50],"
        f" horizon_weights: [0.2, 0.3, 0.5], crowding_window: {crowding}}}}}\n"
        "  - {id: breakout, enabled: true, params: {window: 24, entry_threshold: 0.05}}\n",
        encoding="utf-8",
    )
    return path


def _zero_history_profile(path: Path) -> Path:
    """`correlate` and `mine` take no --min-history, so the fixture needs it lowered via the profile."""
    path.write_text("market_data: {interval: 1h}\nportfolio: {min_history_bars: 0}\n", encoding="utf-8")
    return path


@pytest.mark.parametrize("command", ["correlate", "mine"])
def test_the_cost_stance_reaches_the_reports_that_had_no_costs_block(
    command: str, tmp_path: Path, august_dir: Path
) -> None:
    """Both report cost-NET Sharpes and recorded neither the costs nor the funding stance that produced them.

    That is what made six historical `correlate` reports unknowable when the 2026-09-06 log entry tried to
    settle which evidence had been produced under `--no-funding`: `costs.use_funding` mirrors the flag
    verbatim everywhere else, and these two payloads simply did not carry it.
    """
    root = tmp_path / "data"
    _store_from_fixtures(august_dir, root)
    _funding_for(august_dir, root, ("BTCUSDT", "ETHUSDT"))
    out = tmp_path / "reports"
    common = [
        "--root",
        str(root),
        "--symbols",
        ",".join(SYMBOLS),
        "--out",
        str(out),
        "--funding",
        "--registry",
        str(_short_registry(tmp_path / "reg.yaml", crowding=72)),
        "--profile",
        str(_zero_history_profile(tmp_path / "profile.yaml")),
    ]
    extra = (
        ["--strategies", "tsmom,breakout"]
        if command == "correlate"
        else ["--strategy", "tsmom", "--max-complexity", "3", "--max-lookback", "200"]
    )
    result = CliRunner().invoke(main, ["research", command, *extra, *common])
    assert result.exit_code == 0, result.output
    payload = json.loads(next(out.glob("*.json")).read_text())
    assert payload["costs"]["use_funding"] is True, "the flag every other report records"
    assert set(payload["costs"]) >= {"turnover_bps", "carry_bps_per_bar", "use_funding"}
    assert payload["funding_inputs"]["symbols_settled"] == 2


def test_research_overlay_keeps_book_sleeves_under_min_history(tmp_path: Path, august_dir: Path) -> None:
    """`--min-history` rebuilds the model, and the rebuild has to carry the books over (D-018/D-019).

    It used to restate `AlphaModel`'s fields by hand and omit `books`, so `research overlay
    --min-history N` raised "strategy ... refers to undeclared book" against any registry that runs a
    sleeve - which the shipped config/alpha_registry.yaml has done since flow_short.  The rebuild is
    `replace(model, min_history_bars=...)` now, so the field list cannot go stale again as
    `AlphaModel` grows; this test is what would catch a return to spelling the fields out.

    `exit_code == 0` is the load-bearing assertion, and it stays load-bearing for a reason worth
    recording here: `book_names` is derived from `entries`, not from `books`, so a model that loses its
    books does not quietly shrink to one book - it keeps the sleeve and then cannot price it.  Strip
    `__post_init__` and this same defect surfaces a few frames later as `KeyError: 'sleeve'` in
    `book_weights` (measured, not assumed).  So the validation buys an early and legible failure, not
    the difference between loud and silent.  The `strategies` assertion guards the other direction: it
    is read off `model.entries`, so it would catch a rebuild that dropped the sleeve itself.
    `registry["books"]` is read off the registry rather than the model, so it documents that this
    fixture really is two-book; it does not constrain the run.
    """
    root = tmp_path / "data"
    _store_from_fixtures(august_dir, root)
    out = tmp_path / "reports"
    registry = tmp_path / "registry.yaml"
    registry.write_text(
        "version: 1\n"
        "ensemble: {method: mean}\n"
        "books: {sleeve: {fraction: 0.5}}\n"
        "strategies:\n"
        "  - {id: tsmom, enabled: true, params: {vol_window: 100, horizons: [5, 20, 50], horizon_weights: [0.2, 0.3, 0.5]}}\n"
        "  - {id: meanrev, enabled: true, book: sleeve, params: {window: 48}}\n",
        encoding="utf-8",
    )
    result = CliRunner().invoke(
        main,
        [
            "research",
            "overlay",
            "--root",
            str(root),
            "--symbols",
            ",".join(SYMBOLS),
            "--registry",
            str(registry),
            "--out",
            str(out),
            "--no-funding",
            "--min-history",
            "0",
            "--folds",
            "3",
            "--min-train",
            "300",
            "--exits-grid",
            '{"stop_loss": [2.0], "take_profit": [4.0]}',
            "--throttle-grid",
            '{"start": [0.02], "stop": [0.10], "floor": [0.5]}',
        ],
    )
    assert result.exit_code == 0, result.output
    overlay = json.loads(next(out.glob("overlay-*.json")).read_text())
    assert overlay["strategies"] == ["tsmom", "meanrev"]  # the sleeve reached the evidence, not just the registry
    assert overlay["registry"]["books"] == {"sleeve": 0.5}


def test_mine_can_rescale_the_search_space_and_says_which_one_it_searched(tmp_path: Path, august_dir: Path) -> None:
    """P19: every grid is a bar COUNT, so the same search at another interval must be rescaled.

    Without this the pre-registered daily experiment is unrunnable: `--max-lookback 58` alone truncates
    the 1h-scale grids to 33 of 267 candidates - two families out of seven survive - while all 267 are
    still charged to `declared_trials`.  Paying for a search you did not run is the shape the ledger
    exists to prevent.
    """
    root = tmp_path / "data"
    _store_from_fixtures(august_dir, root)
    out = tmp_path / "reports"
    grids = '{"horizons": [1, 3, 7], "vol_windows": [2, 7], "z_windows": [3, 7], "range_windows": [1, 3]}'
    code, output, payload = _mine(root, out, "--no-funding", "--no-include-funding", "--grids", grids)
    assert code == 0, output

    default = enumerate_candidates(include_funding=False)
    assert payload["evaluated"] != default.evaluated, "the override did not reach the enumerator"
    assert payload["run"]["grids"] == json.loads(grids)  # the space searched, stated in the artefact

    # Every candidate is drawn from the rescaled grids, not the defaults.
    windows = {int(m) for row in payload["candidates"] for m in re.findall(r"ret\((\d+)\)", row["expression"])}
    assert windows and windows <= {1, 3, 7}


def test_mine_refuses_a_grid_key_it_does_not_have(tmp_path: Path, august_dir: Path) -> None:
    """A typo must fail loudly: silently searching the defaults while `run.grids` claims otherwise is
    exactly the artefact-that-lies failure the run block was added to close."""
    root = tmp_path / "data"
    _store_from_fixtures(august_dir, root)
    code, output, _ = _mine(
        root, tmp_path / "reports", "--no-funding", "--no-include-funding", "--grids", '{"horizon": [1, 3]}'
    )
    assert code == 1
    assert "no such parameter" in output and "horizon" in output


def test_the_baseline_params_are_overridable(tmp_path: Path, august_dir: Path) -> None:
    """`--baseline tsmom --interval 1d` on registry params compares against a two-year-horizon book,
    because tsmom's horizons are bar counts.  The override is what makes the baseline expressible at
    the interval the run actually uses."""
    root = tmp_path / "data"
    _store_from_fixtures(august_dir, root)
    out = tmp_path / "reports"
    # Three horizons, because tsmom refuses a set that does not align with `horizon_weights` -
    # the same constraint P19's rescaling has to respect (168/336/720 -> 7/14/30, still three).
    override = '{"horizons": [5, 20, 50], "vol_window": 30, "crowding_window": 0}'
    code, output, payload = _mine(
        root,
        out,
        "--no-funding",
        "--no-include-funding",
        "--baseline",
        "tsmom",
        "--baseline-params",
        override,
    )
    assert code == 0, output
    assert payload["run"]["baseline_params"] == json.loads(override)
    # The recorded params are what the baseline RAN under, not what the registry says.
    assert payload["baseline"]["params"]["horizons"] == [5, 20, 50]
    assert payload["baseline"]["params"]["vol_window"] == 30


def test_mine_refuses_a_grid_key_that_is_also_a_flag(tmp_path: Path, august_dir: Path) -> None:
    """`max_lookback` is a valid enumerator parameter AND a CLI flag, so `--grids` setting it would pass
    the same keyword twice.  Caught by the pre-registered P19 run itself: the first attempt died on a
    `TypeError` traceback, which is loud but says nothing about which of the two to use."""
    root = tmp_path / "data"
    _store_from_fixtures(august_dir, root)
    code, output, _ = _mine(
        root, tmp_path / "reports", "--no-funding", "--no-include-funding", "--grids", '{"max_lookback": 58}'
    )
    assert code == 1
    assert "must not set max_lookback" in output and "--max-lookback" in output


def test_a_mined_id_resolves_under_the_grids_it_was_mined_at(tmp_path: Path, august_dir: Path) -> None:
    """`_resolve_mined` re-derives an id by enumerating, so the space has to be the one it came from.

    Found by running P19: a candidate mined at daily-rescaled grids does not enumerate under the
    defaults, so every command reported it gone - correct by that function's contract, and useless to an
    operator holding the shortlist that had just produced it.  `--grids` is shared for this reason.
    """
    grids = '{"horizons": [1, 3, 7], "vol_windows": [2, 7], "z_windows": [3, 7], "range_windows": [1, 3]}'
    rescaled = enumerate_candidates(horizons=(1, 3, 7), vol_windows=(2, 7), z_windows=(3, 7), range_windows=(1, 3))
    default = {c.hash for c in enumerate_candidates().candidates}
    # Not simply the first candidate: families whose grid was not overridden (`flow_windows` here) emit
    # the same trees either way, so picking blindly can land on one the default space also contains -
    # which would make the "gone" half of this test pass for the wrong reason.
    outside = [c for c in rescaled.candidates if c.hash not in default]
    assert outside, "the fixture grids no longer produce an id outside the default space"
    mined_id = f"mined_{outside[0].hash}"

    root = tmp_path / "data"
    _store_from_fixtures(august_dir, root)
    runner = CliRunner()
    args = [
        "research",
        "backtest",
        "--strategy",
        mined_id,
        "--root",
        str(root),
        "--symbols",
        ",".join(SYMBOLS),
        "--out",
        str(tmp_path / "reports"),
        "--no-funding",
        "--min-history",
        "24",
    ]
    # The control half names its cause: `exit_code == 1` alone would also be satisfied by a bad
    # argument, which would make the `--grids` half's success attributable to nothing in particular.
    gone = runner.invoke(main, args)
    assert gone.exit_code == 1 and f"no candidate hashes to {outside[0].hash}" in gone.output, gone.output
    result = runner.invoke(main, [*args, "--grids", grids])
    assert result.exit_code == 0, result.output


def test_report_daily_asks_about_the_archive_its_data_root_names(tmp_path: Path) -> None:
    """`--data-root` has to reach `data_coverage`, and only the CLI can prove it does.

    The daily report resolved the klines archive against the process's cwd instead of the root it was
    given, so run from anywhere but the repo root - a worktree, say - it named every live symbol as
    having no research data behind it.  That is the one instrument built to catch a symbol trading
    unseen by research (CYSUSDT, sixteen hours), and a unit test of `daily_payload` cannot see the
    break: the parameter existed and the call site simply never passed it.
    """
    store = StateStore(tmp_path / "live")
    state = store.load()
    state.universe = ["AAAUSDT"]
    store.save(state)
    (tmp_path / "registry.yaml").write_text("strategies: []\n", encoding="utf-8")
    (tmp_path / "profile.yaml").write_text(
        f"paths:\n  state_dir: {tmp_path / 'live'}\n  reports_dir: {tmp_path / 'reports'}\n"
        f"registry: {tmp_path / 'registry.yaml'}\n",
        encoding="utf-8",
    )
    (tmp_path / "empty_archive" / "klines").mkdir(parents=True)
    args = [
        "report",
        "daily",
        "--profile",
        str(tmp_path / "profile.yaml"),
        "--date",
        "2026-09-07",
        "--out",
        str(tmp_path / "out"),
    ]

    result = CliRunner().invoke(main, [*args, "--data-root", str(tmp_path / "empty_archive")])
    assert result.exit_code == 0, result.output
    coverage = json.loads((tmp_path / "out" / "2026-09-07.json").read_text(encoding="utf-8"))["data_coverage"]
    assert coverage["missing_klines"] == ["AAAUSDT"], "the empty archive --data-root names holds nothing"

    # The control half: the same run against an archive that does hold the symbol.  Without it, the
    # assertion above is equally satisfied by a report that reads no archive at all.
    stocked = tmp_path / "stocked_archive" / "klines" / "AAAUSDT"
    stocked.mkdir(parents=True)
    (stocked / "1h.parquet").write_bytes(b"")
    result = CliRunner().invoke(main, [*args, "--data-root", str(tmp_path / "stocked_archive")])
    assert result.exit_code == 0, result.output
    coverage = json.loads((tmp_path / "out" / "2026-09-07.json").read_text(encoding="utf-8"))["data_coverage"]
    assert coverage["missing_klines"] == []
