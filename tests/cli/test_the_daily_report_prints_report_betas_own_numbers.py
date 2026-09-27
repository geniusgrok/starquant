"""G3: the daily report's `beta` block is `report beta`'s reading, bit for bit.

Until 2026-09-23 the D-045 decomposition lived inside the `report beta` command, so it was read only
when somebody ran it by hand.  The daily report now prints it every hour.  Two readers of one number
are safe only while they share one computation: the first four answers to D-045's question differed
because the benchmark did, and a second copy of the price fill is how that would come back quietly.

So the two commands are run here end to end, on a state whose prices are the real August 2026 klines
read through the real parquet layout, and their JSON is compared as text.  JSON writes each float as
the shortest repr that round-trips, so equal text is equal bits.

The state carries every trap `report beta` handles at least once: `closes` missing from the older
cycle rows (the archive fills them), a symbol leaving the universe mid-window, a symbol whose parquet
cannot be parsed (a gap, never an error), one bar of the operator's own fills, and a change of net
exposure halfway through.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from click.testing import CliRunner

import starquant_live.report_beta as report_beta
import starquant_live.reports as reports
from starquant_cli import main
from starquant_data.store import KlineStore
from starquant_live.benchmark import (
    NW_LAGS,
    beta_decomposition,
    beta_reading,
    foreign_bars,
    pit_benchmark,
    series_from_cycles,
    signal_state,
)
from starquant_live.reports import _store_closes, daily_alerts, daily_markdown, daily_payload, market_beta
from starquant_live.state import StateStore

SYMBOLS = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT")  # the four the August fixture carries
BARS = 260  # above 4 x NW_LAGS, so neither regression runs a clamped kernel
CLOSES_FROM = 120  # cycle rows carry `closes` only from here on, as the live record does
LEAVES_AT = 150  # BNBUSDT drops out of the universe here
FOREIGN_AT = 60  # the operator's own fills land on this bar
EXPOSURE_STEP_AT = 130  # the net exposure the loop carries rises here (a `vol_target` move)
DEAD = "DEADUSDT"  # in the universe for the whole window; its parquet is zero bytes
DAY = "2026-08-05"


def _prices(august_dir: Path) -> dict[str, pd.Series]:
    return {
        symbol: pd.read_parquet(august_dir / symbol / "1h.parquet").set_index("open_time")["close"].astype(float)
        for symbol in SYMBOLS
    }


def _archive(august_dir: Path, root: Path) -> Path:
    """The fixture klines written by the store's own writer, plus one parquet nothing can parse."""
    for symbol in SYMBOLS:
        frame = pd.read_parquet(august_dir / symbol / "1h.parquet")
        frame["close_time"] = frame["open_time"] + 3_600_000 - 1
        KlineStore(root).append(symbol, "1h", frame)
    (root / "klines" / DEAD).mkdir(parents=True)
    (root / "klines" / DEAD / "1h.parquet").write_bytes(b"")
    return root


def _state(august_dir: Path, directory: Path, bars: int = BARS) -> StateStore:
    """A book on real prices: net-long the basket, with a small residual of its own."""
    prices = _prices(august_dir)
    stamps = [int(stamp) for stamp in prices["BTCUSDT"].index[:bars]]
    store = StateStore(directory)
    usdt = 10_000.0
    for i, stamp in enumerate(stamps):
        held = [s for s in SYMBOLS if s != "BNBUSDT" or i < LEAVES_AT]
        net = 0.9 if i < EXPOSURE_STEP_AT else 1.6
        if i:
            before = [s for s in SYMBOLS if s != "BNBUSDT" or i - 1 < LEAVES_AT]
            market = sum(prices[s][stamp] / prices[s][stamps[i - 1]] - 1.0 for s in before) / len(before)
            carried = 0.9 if i - 1 < EXPOSURE_STEP_AT else 1.6
            usdt *= 1.0 + carried * 1.25 * market + 0.0004 * math.sin(i / 9.0)
        row: dict[str, Any] = {
            "bar_open_ms": stamp,
            "equity": usdt * 1.25,
            "collateral": {"usdt_equity": usdt, "equity": usdt * 1.25},
            "universe": [*held, DEAD],
            "targets": {"BTCUSDT": net / 2.0, "ETHUSDT": net / 2.0},
            "contributions": {"tsmom": {s: -1.0 if s == "SOLUSDT" and i % 40 < 10 else 1.0 for s in held}},
            "skip": False,
            "guard_reasons": [],
            "orders": [],
        }
        if i >= CLOSES_FROM:
            row["closes"] = {s: float(prices[s][stamp]) for s in held}
        store.append_cycle(row)
    for i, total in ((FOREIGN_AT, 25.0), (FOREIGN_AT + 1, 0.0)):
        if i < len(stamps):
            store.append_attribution({"bar_open_ms": stamps[i], "foreign": {"total": total, "rows": int(total > 0)}})
    return store


def _profile(tmp_path: Path) -> Path:
    (tmp_path / "registry.yaml").write_text("strategies: []\n", encoding="utf-8")
    profile = tmp_path / "profile.yaml"
    profile.write_text(
        f"paths:\n  state_dir: {tmp_path / 'live'}\n  reports_dir: {tmp_path / 'reports'}\n"
        f"registry: {tmp_path / 'registry.yaml'}\n",
        encoding="utf-8",
    )
    return profile


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True)


def _as_report_beta_computed_it_before_the_move(
    rows: Sequence[Mapping[str, Any]],
    attribution: Sequence[Mapping[str, Any]],
    loader: Callable[[str], pd.Series],
    strategy: str = "tsmom",
) -> dict[str, Any]:
    """The body of `report beta` at e80b1335, verbatim apart from the I/O it received as arguments.

    Kept as the reference the shared function must reproduce - D-033's technique.  The one deliberate
    difference in `beta_reading` is that it copies only the window's bars out of the archive, and this
    copies every row; nothing is ever looked up outside the window, so the two must agree to the bit.
    """
    series = series_from_cycles(list(rows))
    bars = series["bars"]
    prices = {symbol: dict(points) for symbol, points in series["prices"].items()}
    for symbol in {s for names in series["universe"].values() for s in names}:
        try:
            closes = loader(symbol)
        except Exception:
            continue
        archived = prices.setdefault(symbol, {})
        for stamp, price in zip(closes.index.astype("int64"), closes.astype(float), strict=True):
            archived.setdefault(int(stamp), float(price))
    benchmark = pit_benchmark(bars, series["universe"], prices)
    excluded = foreign_bars(list(attribution))
    decomposition = beta_decomposition(
        series["equity"], benchmark["level"], series["exposure"], excluded_bars=excluded, bars=bars
    )
    return {
        "window": {
            "from": datetime.fromtimestamp(bars[0] / 1000, UTC).isoformat(),
            "to": datetime.fromtimestamp(bars[-1] / 1000, UTC).isoformat(),
            "days": (bars[-1] - bars[0]) / 86_400_000,
            "cycles": len(bars),
        },
        "benchmark": {k: v for k, v in benchmark.items() if k != "level"},
        "signal": signal_state(list(rows), strategy, bars),
        "decomposition": decomposition,
    }


def test_the_daily_block_is_report_betas_json_to_the_bit(tmp_path: Path, august_dir: Path) -> None:
    """Both commands, end to end, on one state: the daily JSON's `beta` block IS the `report beta` JSON."""
    _state(august_dir, tmp_path / "live")
    data_root = _archive(august_dir, tmp_path / "data")
    profile = _profile(tmp_path)
    runner = CliRunner()

    common = ["--profile", str(profile), "--data-root", str(data_root)]
    page_run = runner.invoke(main, ["report", "beta", *common, "--out", str(tmp_path / "beta")])
    assert page_run.exit_code == 0, page_run.output
    daily_run = runner.invoke(main, ["report", "daily", *common, "--date", DAY, "--out", str(tmp_path / "daily")])
    assert daily_run.exit_code == 0, daily_run.output

    (page_path,) = (tmp_path / "beta").glob("beta-*.json")
    page = json.loads(page_path.read_text(encoding="utf-8"))
    block = json.loads((tmp_path / "daily" / f"{DAY}.json").read_text(encoding="utf-8"))["beta"]
    assert _canonical(block) == _canonical(page)

    # Not a comparison of two empty readings.  Every symbol-bar the basket skipped is DEADUSDT's, one
    # per bar pair: had the archive fill not run, the four real symbols would be missing before
    # `CLOSES_FROM` as well.  Had the dead parquet raised, `report beta` would have exited non-zero.
    decomposition = page["decomposition"]
    assert decomposition["measured"] is True
    assert decomposition["bars"] == BARS - 2, "every bar pair but the operator's one"
    assert page["benchmark"]["prices_missing"] == BARS - 1
    assert decomposition["constant"]["nw_lags"] == NW_LAGS
    # The book moves by exactly the exposure it carried times the basket, so the regression that
    # multiplies the market by that exposure has to find a beta of one - on real prices.
    assert decomposition["conditional"]["beta"] == pytest.approx(1.0, abs=0.05)

    # And the two pages print the same rounded numbers.
    section = (tmp_path / "daily" / f"{DAY}.md").read_text(encoding="utf-8").split("## Market beta")[1]
    section = section.split("\n## ")[0]
    for kind, label in (("constant", "constant beta"), ("conditional", "conditional（敞口 × 市场）")):
        row = decomposition[kind]
        line = next(text for text in section.splitlines() if text.startswith(f"| {label} |"))
        assert f"beta {row['beta']:.2f}（t {row['beta_t']:.2f}）" in line
        assert f"alpha {row['alpha_bps_per_hour']:.2f} bps/h（t {row['alpha_t']:.2f}）" in line
        assert f"残差部分 {100.0 * row['residual_part']:.2f}%" in line
    assert f"| 回归样本 | {BARS - 2} 根 bar" in section


def test_report_beta_reads_to_the_bit_what_it_read_before_the_move(tmp_path: Path, august_dir: Path) -> None:
    """`beta_reading` against the command body it replaced, on the same rows and the same archive."""
    store = _state(august_dir, tmp_path / "live")
    loader = _store_closes(_archive(august_dir, tmp_path / "data"), "1h")
    rows = store.read_jsonl(store.cycles_path)
    attribution = store.read_jsonl(store.attribution_path)

    moved = beta_reading(rows, attribution, loader)

    assert _canonical(moved) == _canonical(_as_report_beta_computed_it_before_the_move(rows, attribution, loader))
    assert moved["benchmark"]["prices_missing"] == BARS - 1


def test_a_block_that_cannot_be_computed_says_why_and_the_rest_of_the_report_stands(
    tmp_path: Path, august_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The hourly check must not lose its other readings to one that gates nothing."""
    store = _state(august_dir, tmp_path / "live")
    data_root = _archive(august_dir, tmp_path / "data")
    healthy = daily_payload(store, DAY, data_root=data_root)

    def broken(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("the archive answered with something that is not a price")

    # Patched where the reading calls it.  Since 2026-09-25 that is `report_beta`, not `reports`; a
    # patch left on `reports` raises AttributeError instead of silently missing (see `reports`' docstring).
    monkeypatch.setattr(report_beta, "beta_reading", broken)
    payload = daily_payload(StateStore(tmp_path / "live"), DAY, data_root=data_root)

    assert payload["beta"] == {
        "measured": False,
        "reason": "RuntimeError: the archive answered with something that is not a price",
    }, "the patch reached the block and the block said what happened"
    assert healthy["beta"]["decomposition"]["measured"] is True, "the control half read a number"
    assert set(payload) == set(healthy), "every other block is still there"
    text, control = daily_markdown(payload), daily_markdown(healthy)
    assert [h for h in text.splitlines() if h.startswith("## ")] == [
        h for h in control.splitlines() if h.startswith("## ")
    ], "and every section still renders"
    assert "RuntimeError: the archive answered" in text
    assert daily_alerts(payload) == daily_alerts(healthy), "the block reports; it never pages"


def test_too_short_a_record_is_the_same_refusal_on_both_pages(tmp_path: Path, august_dir: Path) -> None:
    """One bar with USDT equity: `report beta` refuses, and the daily block carries the same sentence."""
    _state(august_dir, tmp_path / "live", bars=1)
    data_root = _archive(august_dir, tmp_path / "data")

    refused = CliRunner().invoke(
        main, ["report", "beta", "--profile", str(_profile(tmp_path)), "--data-root", str(data_root)]
    )
    block = market_beta(StateStore(tmp_path / "live"), root=data_root)

    assert refused.exit_code == 1
    assert block == {"measured": False, "reason": "周期记录里还没有两根带 usdt_equity 的 bar，无法分解"}
    assert block["reason"] in refused.output
    assert block["reason"] in daily_markdown(daily_payload(StateStore(tmp_path / "live"), DAY, data_root=data_root))


def test_a_clamped_kernel_is_named_on_the_line_it_produced(tmp_path: Path, august_dir: Path) -> None:
    """The short window's t comes from a narrower kernel, and the compact line has to say so too."""
    data_root = _archive(august_dir, tmp_path / "data")
    short = market_beta(_state(august_dir, tmp_path / "short", bars=80), root=data_root)
    full = market_beta(_state(august_dir, tmp_path / "full"), root=data_root)

    short_lines = reports._market_beta_lines(short)
    full_lines = reports._market_beta_lines(full)

    assert short["decomposition"]["constant"]["nw_covers_intended_horizon"] is False
    assert "NW 带宽被夹到" in short_lines["constant beta"]
    assert "NW 带宽被夹到" not in full_lines["constant beta"]
