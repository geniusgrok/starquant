"""M-015: the report can tell "sizing adapts per symbol" from "every symbol is treated alike".

The operator asked three times why every order carries the same 5x, because nothing in the report
answered it.  D-037 already established that the exchange leverage is inert here and that adaptation
lives in the weight; these tests are the instrument that says so from the live record, and - the part
that matters - that would stop saying so if stage 1 were ever removed.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from starquant_alpha.portfolio import PortfolioParams, asset_vol, build_weights
from starquant_live.reports import RISK_COMPRESSION_LIMIT, risk_adaptation
from starquant_live.state import LiveState, StateStore

HOUR = 3_600_000
BASE = 1_788_000_000_000
DAY = datetime.fromtimestamp(BASE / 1000, tz=UTC).strftime("%Y-%m-%d")

# Roughly the live book on 2026-09-05: a 12x spread in annualised volatility across 15 names.
VOLS = {
    "BNBUSDT": 0.79,
    "BTCUSDT": 0.81,
    "ETHUSDT": 0.88,
    "SOLUSDT": 0.96,
    "SUIUSDT": 1.16,
    "XRPUSDT": 1.25,
    "DOGEUSDT": 1.25,
    "HYPEUSDT": 1.27,
    "ADAUSDT": 1.50,
    "1000PEPEUSDT": 1.66,
    "TRUMPUSDT": 2.22,
    "ENAUSDT": 2.45,
    "ZECUSDT": 2.50,
    "CYSUSDT": 6.15,
    "AKEUSDT": 9.63,
}


def _store(tmp_path: Path, targets: dict[str, float], vols: dict[str, float] | None) -> StateStore:
    store = StateStore(tmp_path / "live")
    record: dict[str, object] = {"as_of_ms": BASE, "equity": 10_692.0, "targets": targets}
    if vols is not None:
        record["asset_vol"] = vols
    store.append_cycle(record)
    store.save(LiveState(leverage_set=dict.fromkeys(targets, 5)))
    return store


def test_inverse_vol_sizing_compresses_a_12x_market_spread_into_a_small_risk_spread(tmp_path: Path) -> None:
    """The live shape: uniform 5x on the venue, and risk contributions that are nearly flat anyway."""
    targets = {symbol: 0.30 / vol for symbol, vol in VOLS.items()}  # stage 1, alone
    block = risk_adaptation(_store(tmp_path, targets, VOLS), DAY)
    assert block["enforced"] and block["status"] == "OK"
    assert block["vol_spread"] > 12.0, "the markets really are that different"
    assert block["risk_spread"] < 1.01, "and stage 1 takes essentially all of it back out"
    assert block["leverage_distinct"] == 1, "the exchange leverage is uniform, and that is not the alert"


def test_deleting_stage_one_makes_compression_read_one_and_alerts(tmp_path: Path) -> None:
    """The falsifier.  Size every symbol alike and risk_spread converges on vol_spread."""
    targets = dict.fromkeys(VOLS, 0.05)
    block = risk_adaptation(_store(tmp_path, targets, VOLS), DAY)
    assert math.isclose(block["compression"], 1.0, rel_tol=1e-12)
    assert block["status"] == "ALERT" and block["compression"] > RISK_COMPRESSION_LIMIT


def test_the_live_book_sits_far_below_the_limit_rather_than_just_inside_it(tmp_path: Path) -> None:
    """A single-book bar: 0.13 measured 2026-09-05, against a limit that is 0.76 since 2026-09-08.

    The 0.20 asserted here is deliberately NOT the limit.  This test pins what path-dependence alone
    costs on one book, so that a future change which quietly triples it is visible here rather than
    only in whatever the limit happens to be.  The probe overlay's own reading is pinned separately.
    """
    targets = {symbol: 0.30 / vol for symbol, vol in VOLS.items()}
    targets["BNBUSDT"] *= 1.25  # the band holding a stale weight while sigma moved under it
    targets["AKEUSDT"] *= 0.80
    block = risk_adaptation(_store(tmp_path, targets, VOLS), DAY)
    assert block["compression"] < 0.20, "honest path-dependence must not approach the limit"


def test_a_cycle_written_before_asset_vol_existed_refuses_instead_of_passing(tmp_path: Path) -> None:
    """The failure this codebase keeps finding: a number that reads like a pass while measuring nothing."""
    block = risk_adaptation(_store(tmp_path, dict.fromkeys(VOLS, 0.05), None), DAY)
    assert block["enforced"] is False and "predates" in block["reason"]
    assert "status" not in block, "no verdict at all, rather than OK"


def test_a_book_of_two_names_refuses_because_a_spread_over_two_is_noise(tmp_path: Path) -> None:
    targets = {"BTCUSDT": 0.06, "AKEUSDT": 0.005, "ETHUSDT": 0.0}
    block = risk_adaptation(_store(tmp_path, targets, VOLS), DAY)
    assert block["enforced"] is False and "noise" in block["reason"]
    assert len(block["rows"]) == 2, "the zero-weight symbol is not held"


def test_no_cycles_that_day_refuses(tmp_path: Path) -> None:
    block = risk_adaptation(_store(tmp_path, {"BTCUSDT": 0.06}, VOLS), "2020-01-01")
    assert block["enforced"] is False and "no cycles" in block["reason"]


def test_the_reported_divisor_is_the_one_build_weights_actually_divides_by(tmp_path: Path) -> None:
    """Anti-drift: the report's sigma must be the construction's sigma, not a re-derivation.

    Stage 1 is ``target * vol_target / asset_vol``, and stage 2 multiplies the whole row by one
    scalar, so with a constant conviction of 1 and no cap binding, ``weight * asset_vol`` is the
    SAME number for every symbol - ``vol_target`` times that scalar.  Asserting equality across
    symbols rather than equality to ``vol_target`` is deliberate: the scalar legitimately sits
    below 1 whenever the book's own volatility exceeds the target, which it does here.  If a later
    change makes the exported ``asset_vol`` describe a different quantity than the divisor, this
    identity breaks and this test is how it is noticed.
    """
    rng = np.random.default_rng(20260905)
    index = pd.date_range("2026-01-01", periods=600, freq="h", tz="UTC")
    close = pd.DataFrame(
        {
            name: 100.0 * np.exp(np.cumsum(rng.normal(0.0, scale, len(index))))
            for name, scale in (("CALM", 0.002), ("MID", 0.006), ("WILD", 0.020))
        },
        index=index,
    )
    params = PortfolioParams(vol_target=0.30, max_weight=10.0, max_gross=100.0, max_scalar=1.0)
    weights = build_weights(pd.DataFrame(1.0, index=index, columns=close.columns), close, 8760.0, params)
    sigma = asset_vol(close, params, 8760.0)
    risk = weights.iloc[-1] * sigma.iloc[-1]
    assert np.allclose(risk, risk.iloc[0], rtol=1e-9), risk.to_dict()
    assert 0.0 < float(risk.iloc[0]) <= params.vol_target, "the stage-2 scalar only ever shrinks the row"
    assert sigma.iloc[-1]["WILD"] / sigma.iloc[-1]["CALM"] > 5.0, "the fixture must have a real vol spread"
    assert math.isclose(
        float(weights.iloc[-1]["WILD"] / weights.iloc[-1]["CALM"]),
        float(sigma.iloc[-1]["CALM"] / sigma.iloc[-1]["WILD"]),
        rel_tol=1e-9,
    )


# --- the probe book, which the 0.50 bound was calibrated without ---------------------------------

# The 2026-09-08T04:00Z cycle, copied from `.starquant/live/cycles.jsonl`: the worst compression on the
# live record (0.581), and the first reading ever to cross the bound.  Fourteen of the eighteen names
# carry pure stage 1 and read the same risk contribution; the four the `flow_short` probe also holds
# do not, because `combine_books` sums a SECOND independently vol-targeted book onto them (D-019).
LIVE_VOLS = {
    "BTCUSDT": 0.296677,
    "ETHUSDT": 0.397927,
    "BNBUSDT": 0.414227,
    "SOLUSDT": 0.525852,
    "XRPUSDT": 0.536998,
    "HYPEUSDT": 0.581098,
    "ADAUSDT": 0.789115,
    "DOGEUSDT": 0.855633,
    "LINKUSDT": 0.902769,
    "SUIUSDT": 0.914739,
    "1000PEPEUSDT": 0.933262,
    "TRUMPUSDT": 1.119265,
    "ENAUSDT": 1.311337,
    "ZECUSDT": 1.313913,
    "UNIUSDT": 1.383155,
    "CYSUSDT": 1.842893,
    "TUTUSDT": 2.073822,
    "AKEUSDT": 4.810497,
}
LIVE_TARGETS = {
    "BTCUSDT": 0.081531876,
    "ETHUSDT": 0.060786550,
    "BNBUSDT": 0.058394649,
    "SOLUSDT": 0.045998922,
    "XRPUSDT": 0.045044139,
    "HYPEUSDT": 0.041625721,
    "ADAUSDT": 0.030652840,
    "DOGEUSDT": 0.028269871,
    "LINKUSDT": 0.026793807,
    "SUIUSDT": 0.026443196,
    "1000PEPEUSDT": -0.007633895,  # tsmom long, probe short: the two nearly cancel
    "TRUMPUSDT": -0.006433380,  # likewise
    "ENAUSDT": 0.018445775,
    "ZECUSDT": 0.018409614,
    "UNIUSDT": 0.017488009,
    "CYSUSDT": -0.031341788,  # tsmom short, probe short: the two stack
    "TUTUSDT": -0.032347069,  # likewise, and this one is the maximum
    "AKEUSDT": 0.005028301,
}
PROBE_NAMES = {"1000PEPEUSDT", "TRUMPUSDT", "CYSUSDT", "TUTUSDT"}


def _stage_one_deleted(targets: dict[str, float], vols: dict[str, float]) -> dict[str, float]:
    """The same book with stage 1 removed, derived rather than invented.

    Stage 1 is ``w = c * vol_target / sigma`` and stage 2 multiplies the whole row by one scalar, so
    the conviction behind a recorded weight is ``c ∝ w * sigma``.  Delete stage 1 and the weight IS
    the conviction: these are that book's weights on the same bar with the sigma division taken out.
    """
    return {symbol: weight * vols[symbol] for symbol, weight in targets.items()}


def test_the_probe_overlay_on_the_worst_live_cycle_is_not_an_alert(tmp_path: Path) -> None:
    """Stage 1 is working on this bar; the spread is two books disagreeing, which is D-019 by design.

    The fourteen names outside the probe are the proof, and they are what the alert text used to deny:
    they sit at one risk contribution to four decimal places, which is stage 1 doing exactly its job.
    """
    block = risk_adaptation(_store(tmp_path, LIVE_TARGETS, LIVE_VOLS), DAY)
    untouched = [row["risk"] for row in block["rows"] if row["symbol"] not in PROBE_NAMES]
    assert max(untouched) - min(untouched) < 1e-4, "stage 1 is intact on every name the probe does not hold"
    assert block["status"] == "OK", f"compression {block['compression']:.3f} against limit {RISK_COMPRESSION_LIMIT}"


def test_deleting_stage_one_on_that_same_book_still_alerts(tmp_path: Path) -> None:
    """The falsifier has to survive the recalibration, or the limit was raised into uselessness."""
    block = risk_adaptation(_store(tmp_path, _stage_one_deleted(LIVE_TARGETS, LIVE_VOLS), LIVE_VOLS), DAY)
    assert block["status"] == "ALERT"
    assert block["compression"] > 1.0, "a book that ignores sigma reads at or above one, as the docstring says"


def test_the_limit_separates_the_two_by_the_pre_registered_margin(tmp_path: Path) -> None:
    """R3 of ``scratchpad/m015_recalibrate_with_probe.py``, made executable.

    A limit is only a limit if the two states it divides are apart.  Measured over the 88 live cycles
    carrying ``asset_vol``: max(working) 0.581 against min(deleted) 1.000, a ratio of 1.72 against the
    1.5 the rule fixed before it ran.  On this bar the same two readings are 0.581 and 1.290.
    """
    working = risk_adaptation(_store(tmp_path, LIVE_TARGETS, LIVE_VOLS), DAY)["compression"]
    deleted = risk_adaptation(
        _store(tmp_path / "deleted", _stage_one_deleted(LIVE_TARGETS, LIVE_VOLS), LIVE_VOLS), DAY
    )["compression"]
    assert deleted / working >= 1.5, f"working {working:.3f} vs deleted {deleted:.3f}"
    assert working < RISK_COMPRESSION_LIMIT < deleted, "the limit must sit strictly between them"
