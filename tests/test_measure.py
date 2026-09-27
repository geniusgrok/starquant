"""Full-sample account measurement. Skips when the local tape or numba is absent."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("numba")

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(not (ROOT / "data" / "btcusdt_1m.npz").exists(), reason="local BTCUSDT tape is not in the tree")
def test_full_period_clears_100pct_cagr_and_half_drawdown():
    from btc_perp.measure import TARGET_CNY, run_official

    report = run_official()
    assert report["n_long"] > 0
    assert report["n_short"] > 0
    assert report["end_cny"] >= TARGET_CNY
    assert report["cagr"] >= 1.0
    assert report["min_equity_over_peak"] > 0.5
    assert report["passed"] is True
    assert report["live_orders"] is False
