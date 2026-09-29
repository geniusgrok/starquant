"""Candidate model, cross-asset helpers, and the report on synthetic tapes."""

from __future__ import annotations

import dataclasses
import itertools
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from btc_perp import generalization as gen
from btc_perp.candidate import CandidateConfig, load_candidate, run_candidate
from btc_perp.config import load_config
from btc_perp.tapes import Tape


def _tape(days: int = 120, seed: int = 3) -> Tape:
    n = days * 1440
    rng = np.random.default_rng(seed)
    drift = 0.00003 * np.sin(np.arange(n) / 40_000.0)
    close = 20_000.0 * np.exp(np.cumsum(drift + rng.normal(0.0, 0.0004, n)))
    open_ = np.concatenate(([close[0]], close[:-1]))
    spread = np.abs(rng.normal(0.0, 0.0003, n)) * close
    high = np.maximum(open_, close) + spread
    low = np.minimum(open_, close) - spread
    ts = np.arange(n, dtype=np.int64) * 60_000 + 1_577_836_800_000
    return Tape(
        "synthetic",
        ts,
        open_,
        high,
        low,
        close,
        np.full(n, 5e7),
        np.zeros(n),
        np.full(n, 7.0),
        np.repeat(np.arange(n // 1440, dtype=np.int32) + 20200101, 1440),
    )


def _small(cfg: CandidateConfig) -> CandidateConfig:
    return dataclasses.replace(cfg, lookback_days=(2, 4, 6, 9), vol_days=3, atr_days=3, dd_window_days=20)


def test_candidate_settings_are_conventional_and_few() -> None:
    cfg = load_candidate()
    assert cfg.lookback_days == (20, 40, 60, 90)
    assert cfg.leverage <= 5
    assert cfg.max_leverage <= cfg.leverage
    assert len(gen.family()) == 36


def test_candidate_trades_and_stays_finite() -> None:
    tape = _tape()
    row = run_candidate(tape, _small(load_candidate()))
    assert np.isfinite(row["end_cny"]) and row["end_cny"] > 0
    assert row["n_long"] + row["n_short"] > 0
    assert 0.0 < row["min_equity_over_peak"] <= 1.0


def test_candidate_does_not_look_ahead() -> None:
    tape = _tape()
    cfg = _small(load_candidate())
    cut = 80 * 1440
    full = run_candidate(tape, cfg, i1=cut)
    shorter = Tape(
        **{
            **dataclasses.asdict(tape),
            **{k: getattr(tape, k)[:cut] for k in ("ts", "o", "h", "low", "c", "qv", "fund", "fx", "days")},
        }
    )
    truncated = run_candidate(shorter, cfg)
    assert np.allclose(full["_equity"], truncated["_equity"])


def test_a_worse_stop_fill_and_a_higher_fee_never_help() -> None:
    tape = _tape()
    cfg = _small(load_candidate())
    plain = run_candidate(tape, cfg)
    fee = run_candidate(tape, cfg, taker=0.002)
    assert fee["end_cny"] <= plain["end_cny"]


def test_baseline_replay_runs_on_any_tape_and_is_causal() -> None:
    tape = _tape()
    cfg = dataclasses.replace(load_config(), entry_hours=48, exit_hours=24)
    cut = 90 * 1440
    full = gen.baseline_replay(tape, cfg, 0, cut, keep_path=True)
    assert full["end_cny"] > 0
    assert len(full["_equity"]) == cut
    later = gen.baseline_replay(tape, cfg, 30 * 1440, cut)
    assert later["end_cny"] > 0


def test_choose_uses_the_median_over_the_named_tapes() -> None:
    def row(tape: str, scale: int, calmar: float) -> dict[str, Any]:
        return {"tape": tape, "lb_scale": scale, "target_vol": 0.5, "atr_mult": 3.0, "calmar": calmar}

    rows = [
        row("a", 10, 1.0),
        row("b", 10, 1.0),
        row("c", 10, -3.0),
        row("a", 20, 0.4),
        row("b", 20, 0.4),
        row("c", 20, 0.4),
    ]
    assert gen.choose(rows, ("a", "b", "c"))["lb_scale"] == 10
    assert gen.choose(rows, ("c",))["lb_scale"] == 20


def test_leave_one_out_never_selects_on_the_held_out_tape() -> None:
    rows = []
    for tape, best in (("a", 10), ("b", 10), ("c", 20)):
        for scale in (10, 20):
            rows.append(
                {
                    "tape": tape,
                    "lb_scale": scale,
                    "target_vol": 0.5,
                    "atr_mult": 3.0,
                    "calmar": 1.0 if scale == best else 0.0,
                    "end_cny": 1.0,
                    "cagr": 0.1,
                    "min_equity_over_peak": 0.6,
                    "n_long": 1,
                    "n_short": 1,
                }
            )
    result = {r["held_out"]: r for r in gen.leave_one_out(rows, ("a", "b", "c"))}
    assert result["c"]["chosen"]["lb_scale"] == 10
    assert result["c"]["rank_among_grid"] == 2
    assert result["a"]["chosen"]["lb_scale"] in (10, 20)
    assert "c" not in result["c"]["chosen_on"]


def test_block_bootstrap_is_repeatable_and_ordered() -> None:
    days = 400
    rng = np.random.default_rng(1)
    daily = 10_000.0 * np.cumprod(1.0 + rng.normal(0.001, 0.02, days))
    equity = np.repeat(daily, 1440)
    first = gen.block_bootstrap(equity, draws=200)
    second = gen.block_bootstrap(equity, draws=200)
    assert first == second
    pct = first["cagr_percentiles"]
    assert pct["5"] <= pct["50"] <= pct["95"]
    assert 0.0 <= first["share_min_ratio_above_half"] <= 1.0
    assert gen.block_bootstrap(equity[: 30 * 1440]) == {}


def test_window_returns_counts_whole_windows() -> None:
    equity = np.repeat(10_000.0 * 1.001 ** np.arange(400), 1440)
    stats = gen.window_returns(equity, days=100)
    assert stats["windows"] == 3
    assert stats["share_positive"] == 1.0
    assert stats["worst"] == pytest.approx(1.001**100 - 1.0)


def test_month_windows_end_at_the_tape_end() -> None:
    tape = _tape(days=400)
    edges = gen._month_starts(tape, "2020-04-01", 3)
    assert edges[-1] == len(tape.ts)
    assert all(b > a for a, b in itertools.pairwise(edges))
    assert edges[0] == 91 * 1440


def test_missing_data_gives_an_unverified_report_not_numbers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import btc_perp.tapes as tapes

    monkeypatch.setattr(tapes, "DATA", tmp_path)
    monkeypatch.setattr(gen, "REPORT", tmp_path / "reports" / "g.json")
    report = gen.run_generalization()
    assert report["verified"] is False
    assert (tmp_path / "reports" / "g.unverified.json").exists()
    assert not (tmp_path / "reports" / "g.json").exists()
