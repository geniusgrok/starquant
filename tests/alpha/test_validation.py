"""T-A04 / T-A06: validation machinery behaves; overlapping labels are handled honestly."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from starquant_alpha.validation.cpcv import cpcv_splits
from starquant_alpha.validation.labels import execution_forward_returns, forward_returns, non_overlapping
from starquant_alpha.validation.metrics import information_coefficient, newey_west_tstat, normal_cdf, normal_ppf
from starquant_alpha.validation.multiple_testing import (
    benjamini_hochberg,
    deflated_sharpe_ratio,
    holm,
    probability_of_backtest_overfitting,
    sharpe_per_period,
)
from starquant_alpha.validation.walk_forward import walk_forward_evaluate, walk_forward_folds

FOLD_DAYS = 7  # caliber 4's granularity; production reads Policy, tests pin it


def test_walk_forward_folds_purge_and_cover() -> None:
    folds = walk_forward_folds(1000, 5, min_train=500, purge=10)
    assert [f.test_start for f in folds] == [500, 600, 700, 800, 900]
    assert folds[-1].test_end == 1000
    for fold in folds:
        assert fold.train_end == fold.test_start - 10
        assert fold.train_start == 0
    rolling = walk_forward_folds(1000, 4, min_train=400, purge=5, expanding=False, train_window=300)
    assert all(f.train_end - f.train_start <= 300 and f.train_end == f.test_start - 5 for f in rolling)


def test_cpcv_splits_exclude_purge_and_embargo() -> None:
    splits = cpcv_splits(600, n_groups=6, n_test_groups=2, purge=5, embargo=3)
    assert len(splits) == 15
    for split in splits:
        assert not set(split.train_index) & set(split.test_index)
        for start in (split.test_index[0],):
            assert all(index not in split.train_index for index in range(max(0, start - 5), start))


def test_walk_forward_picks_params_on_train_only() -> None:
    index = pd.date_range("2024-01-01", periods=1000, freq="h", tz="UTC")
    rng = np.random.default_rng(1)
    good = pd.Series(rng.normal(0.0005, 0.01, 1000), index=index)
    bad = pd.Series(rng.normal(-0.0005, 0.01, 1000), index=index)
    folds = walk_forward_folds(1000, 4, min_train=400, purge=4)
    result = walk_forward_evaluate({"good": good, "bad": bad}, {"good": {"p": 1}, "bad": {"p": 2}}, folds, 8760.0)
    assert all(outcome.chosen_params == {"p": 1} for outcome in result.folds)
    assert len(result.oos_returns) == 600


def test_normal_helpers() -> None:
    assert math.isclose(normal_cdf(normal_ppf(0.975)), 0.975, abs_tol=1e-7)
    assert math.isclose(normal_ppf(0.5), 0.0, abs_tol=1e-9)


def test_bh_and_holm_are_monotone_and_known_values() -> None:
    p = [0.03, 0.04, 0.049]
    assert holm(p) == pytest.approx([0.09, 0.09, 0.09])
    assert all(value <= 1.0 for value in benjamini_hochberg([0.01, 0.2, 0.03, 0.5]))
    adjusted = benjamini_hochberg([0.001, 0.002, 0.5])
    assert adjusted[0] <= adjusted[1] <= adjusted[2]


def test_dsr_haircuts_the_best_of_many_random_strategies() -> None:
    rng = np.random.default_rng(3)
    n_obs, n_trials = 2000, 100
    matrix = rng.normal(0.0, 0.01, size=(n_obs, n_trials))
    sharpes = [sharpe_per_period(matrix[:, j]) or 0.0 for j in range(n_trials)]
    best = int(np.argmax(sharpes))
    naive_z = sharpes[best] * math.sqrt(n_obs - 1)
    assert normal_cdf(naive_z) > 0.95  # the lucky draw looks significant on its own
    dsr = deflated_sharpe_ratio(
        sharpes[best], n_trials=n_trials, sharpe_variance=float(np.var(sharpes, ddof=1)), n_obs=n_obs
    )
    assert dsr.benchmark_sharpe > 0
    assert dsr.p_value > 0.05


def test_pbo_is_high_for_noise_and_low_for_a_true_edge() -> None:
    rng = np.random.default_rng(5)
    noise = rng.normal(0.0, 0.01, size=(1600, 12))
    assert 0.2 <= probability_of_backtest_overfitting(noise, n_subsets=8).pbo <= 0.8
    edge = noise.copy()
    edge[:, 3] += 0.003
    assert probability_of_backtest_overfitting(edge, n_subsets=8).pbo <= 0.1


def _random_walk_panel(seed: int, n_symbols: int = 12, n_bars: int = 1500) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    index = pd.date_range("2023-01-01", periods=n_bars, freq="h", tz="UTC")
    steps = rng.normal(0.0, 0.01, size=(n_bars, n_symbols))
    prices = 100.0 * np.exp(np.cumsum(steps, axis=0))
    return pd.DataFrame(prices, index=index, columns=[f"S{i}" for i in range(n_symbols)])


def _persistent_noise_scores(close: pd.DataFrame, seed: int, phi: float = 0.95) -> pd.DataFrame:
    rng = np.random.default_rng(seed + 1000)
    shocks = rng.normal(0.0, 1.0, size=close.shape)
    values = np.zeros_like(shocks)
    for t in range(1, shocks.shape[0]):
        values[t] = phi * values[t - 1] + shocks[t]
    return pd.DataFrame(values, index=close.index, columns=close.columns)


def test_a_label_looks_forward_and_the_execution_label_fills_at_the_next_open() -> None:
    """The direction of both labels had no anchor: reversing either shift left the whole suite green.

    Nothing trades on them - `research diagnose` is the only caller - but the SIGN is what that table is
    read for.  KILL-042 is literally "a negative time-series IC alongside a profitable book", so a
    reversed label would not have broken the diagnosis, it would have inverted it.
    """
    close = pd.DataFrame({"X": [100.0, 110.0, 121.0]})
    open_ = pd.DataFrame({"X": [100.0, 100.0, 110.0]})

    fwd = forward_returns(close, 1)
    assert fwd.iloc[0, 0] == pytest.approx(0.10)  # decided on bar 0, earns bar 1
    assert fwd.iloc[1, 0] == pytest.approx(0.10)
    assert pd.isna(fwd.iloc[2, 0])  # the last bar has no future to label with

    executed = execution_forward_returns(open_, close, 1)
    assert executed.iloc[0, 0] == pytest.approx(0.10)  # fills at open_1 = 100, marks at close_1 = 110
    assert pd.isna(executed.iloc[2, 0])


def test_overlapping_labels_inflate_naive_t_but_not_newey_west_or_non_overlapping() -> None:
    """T-A06: persistent noise scores vs 4-bar labels must not look significant (D-011)."""
    horizon = 4
    naive_rejections = nw_rejections = sparse_rejections = 0
    seeds = range(30)
    for seed in seeds:
        close = _random_walk_panel(seed)
        scores = _persistent_noise_scores(close, seed)
        ic = information_coefficient(scores, forward_returns(close, horizon)).dropna()
        naive_t = float(ic.mean() / ic.std(ddof=1) * math.sqrt(len(ic)))
        naive_rejections += abs(naive_t) > 1.96
        nw = newey_west_tstat(ic, max_lags=horizon)
        nw_rejections += nw["p_value"] is not None and nw["p_value"] < 0.05
        sparse = non_overlapping(ic, horizon)
        sparse_t = float(sparse.mean() / sparse.std(ddof=1) * math.sqrt(len(sparse)))
        sparse_rejections += abs(sparse_t) > 1.96
    n = len(seeds)
    assert naive_rejections / n > nw_rejections / n or naive_rejections / n <= 0.15
    assert nw_rejections / n <= 0.2
    assert sparse_rejections / n <= 0.2


def test_prior_trials_make_dsr_stricter() -> None:
    from starquant_alpha.validation.multiple_testing import multiple_testing_report

    rng = np.random.default_rng(9)
    matrix = rng.normal(0.0002, 0.01, size=(3000, 4))
    candidate = matrix[:, int(np.argmax(matrix.mean(axis=0)))]
    fresh = multiple_testing_report(candidate, matrix, bars_per_year=8760.0)
    burdened = multiple_testing_report(candidate, matrix, bars_per_year=8760.0, prior_trials=30)
    assert burdened["n_trials"] == 34 and burdened["prior_trials"] == 30 and fresh["n_trials"] == 4
    assert burdened["dsr_p_value"] >= fresh["dsr_p_value"]
    assert burdened["expected_max_sharpe_annual"] > fresh["expected_max_sharpe_annual"]


def test_ledger_pools_trials_and_verdict_ignores_pbo_for_tiny_grids() -> None:
    from starquant_alpha.validation.ledger import TrialRecord, dsr_inputs, parse_ledger
    from starquant_alpha.validation.verdict import decide

    older = [
        TrialRecord("s", f"k{i}", s, 8760.0, "t", "a", "b", 15, "run0") for i, s in enumerate((0.2, 1.0, -0.3, 0.7))
    ]
    lines = [r.to_json() for r in older] + [
        TrialRecord("other", "z", 2.0, 8760.0, "t", "a", "b", 15, "run0").to_json(),
        "garbage",
    ]
    prior = parse_ledger(lines, "s")
    assert len(prior) == 4
    pooled = dsr_inputs(
        prior,
        {"new1": 1.5 / 8760**0.5, "new2": None},
        8760.0,
        manual_prior_trials=10,
        range_end_granularity_days=FOLD_DAYS,
    )
    assert pooled["n_trials"] == 16 and pooled["pooled_sharpes"] == 5 and pooled["sharpe_variance"] > 0
    base = {
        "walk_forward": {"oos_sharpe": 1.6, "oos_t_stat": 3.1, "fold_consistency": 1.0},
        "multiple_testing": {"dsr_p_value": 0.01, "pbo": 0.67, "grid_trials": 2},
        "cpcv": {"fraction_negative": 0.0},
        "cost_stress": {"x2": 1.3},
    }
    # D-043: the tiny grid still exempts PBO from FAILING - CSCV cannot rank two configurations - but
    # the exemption is no longer free.  It caps the verdict at WEAK_PASS and says so, where it used to
    # return PASS with nothing in the artefact recording that the gate had not run.
    verdict, reasons = decide(base)
    assert verdict == "WEAK_PASS" and any("exempted" in r for r in reasons)
    wide = {**base, "multiple_testing": {**base["multiple_testing"], "grid_trials": 8}}
    verdict, reasons = decide(wide)
    assert verdict == "FAIL" and any("pbo" in r for r in reasons)
    # ...and a small grid whose PBO is fine is untouched: the cap is about the gate not running, not
    # about the grid being small.
    calm = {**base, "multiple_testing": {**base["multiple_testing"], "pbo": 0.1}}
    assert decide(calm) == ("PASS", [])


def test_verdict_is_oos_first_and_dsr_is_informational() -> None:
    """D-020: OOS Sharpe + Newey-West t decide; DSR is reported, never a veto; CPCV negative share is a gate."""
    from starquant_alpha.validation.verdict import decide

    base = {
        "walk_forward": {"oos_sharpe": 1.5, "oos_t_stat": 3.0, "fold_consistency": 0.8},
        "multiple_testing": {"dsr_p_value": 0.9, "pbo": None, "grid_trials": 1},
        "cpcv": {"fraction_negative": 0.0},
        "cost_stress": {"x2": 1.2},
    }
    assert decide(base) == ("PASS", [])  # DSR p 0.9 does not veto
    weak = {**base, "walk_forward": {**base["walk_forward"], "oos_sharpe": 0.8, "oos_t_stat": 1.7}}
    assert decide(weak)[0] == "WEAK_PASS"  # the Sharpe decides the tier, and only the Sharpe
    # D-P2 (2026-09-06): the t is reported, not enforced - on hourly returns it is the Sharpe
    # restated, so a low t next to a passing Sharpe was counting the same evidence twice.
    low_t = {**base, "walk_forward": {**base["walk_forward"], "oos_t_stat": 1.2}}
    assert decide(low_t) == ("PASS", [])
    legacy = {**base, "walk_forward": {"oos_sharpe": 1.5, "fold_consistency": 0.8}}
    assert decide(legacy)[0] == "FAIL"  # but a report that never measured it still cannot pass
    negative_paths = {**base, "cpcv": {"fraction_negative": 0.25}}
    verdict, reasons = decide(negative_paths)
    assert verdict == "FAIL" and any("fraction_negative" in r for r in reasons)


def test_dsr_inputs_count_exact_replays_once() -> None:
    """D-024: duplicate ledger rows and a re-run of the current grid on the same data are one trial each."""
    from starquant_alpha.validation.ledger import TrialRecord, dsr_inputs, unique_trials

    rows = [
        TrialRecord("s", "k1", 1.6, 8760.0, "t1", "2021-01-31", "2026-09-03", 146, "run1"),
        TrialRecord("s", "k1", 1.6, 8760.0, "t2", "2021-01-31", "2026-09-03", 146, "run2"),  # exact replay
        TrialRecord("s", "k1", 1.7, 8760.0, "t3", "2021-01-31", "2026-09-03", 15, "run3"),  # other universe
        TrialRecord("s", "k2", 0.4, 8760.0, "t4", "2021-03-02", "2026-09-03", 146, "run4"),
    ]
    assert [r.run_id for r in unique_trials(rows, range_end_granularity_days=FOLD_DAYS)] == ["run1", "run3", "run4"]
    pooled = dsr_inputs(
        rows,
        {"k2": 0.4 / 8760**0.5},
        8760.0,
        current_range=("2021-03-02", "2026-09-03", 146),
        range_end_granularity_days=FOLD_DAYS,
    )
    assert pooled["ledger_trials"] == 2 and pooled["ledger_rows"] == 4
    assert pooled["duplicate_rows"] == 1 and pooled["replayed_rows"] == 1
    assert pooled["n_trials"] == 3 and pooled["pooled_sharpes"] == 3
    naive = dsr_inputs(rows, {"k2": 0.4 / 8760**0.5}, 8760.0, range_end_granularity_days=FOLD_DAYS)
    assert naive["ledger_trials"] == 3 and naive["n_trials"] == 4


def test_noise_null_is_reported_next_to_the_pooled_dsr() -> None:
    from starquant_alpha.validation.multiple_testing import multiple_testing_report, sampling_variance

    rng = np.random.default_rng(21)
    matrix = rng.normal(0.0002, 0.01, size=(3000, 4))
    candidate = matrix[:, int(np.argmax(matrix.mean(axis=0)))]
    report = multiple_testing_report(candidate, matrix, bars_per_year=8760.0, prior_trials=20)
    noise = report["noise_null"]
    assert 0.0 <= noise["dsr_p_value"] <= 1.0 and noise["expected_max_sharpe_annual"] > 0
    assert math.isclose(noise["sharpe_variance_period"], sampling_variance(0.0, 3000), rel_tol=0.05)
    assert sampling_variance(0.0, 1) == 0.0
    # a wide pooled variance deflates harder than the sampling floor
    wide = multiple_testing_report(
        candidate, matrix, bars_per_year=8760.0, pooled_n_trials=24, pooled_sharpe_variance=1e-2
    )
    assert wide["dsr_p_value"] >= wide["noise_null"]["dsr_p_value"]
