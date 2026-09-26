from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pandas as pd
import pytest

from starquant_data.archive import ChecksumMismatch, Month, month_range, parse_checksum, verify_zip, zip_to_frame
from starquant_data.binance_public import drop_unclosed, klines_to_frame
from starquant_data.pool import refresh_selection
from starquant_data.store import FundingStore, KlineStore, funding_per_bar
from starquant_data.universe import UniverseConfig
from starquant_shared.binance_rules import parse_exchange_info
from starquant_shared.types import InstrumentRules


def _rows(start_ms: int, n: int, step_ms: int = 3_600_000) -> list[list[object]]:
    return [
        [
            start_ms + i * step_ms,
            "100",
            "101",
            "99",
            "100.5",
            "10",
            start_ms + (i + 1) * step_ms - 1,
            "1000",
            5,
            "6",
            "600",
            "0",
        ]
        for i in range(n)
    ]


def test_klines_to_frame_normalises_microsecond_timestamps() -> None:
    frame = klines_to_frame(
        [[1_700_000_000_000_000, "1", "2", "0.5", "1.5", "3", 1_700_000_003_599_999, "4", 1, "1", "1", "0"]]
    )
    assert int(frame["open_time"].iloc[0]) == 1_700_000_000_000
    assert frame["close"].dtype == float


def test_drop_unclosed_removes_in_progress_bar() -> None:
    frame = klines_to_frame(_rows(0, 3))
    kept = drop_unclosed(frame, now_ms=2 * 3_600_000 - 1)
    assert len(kept) == 1


def test_store_merges_and_dedupes(tmp_path: Path) -> None:
    store = KlineStore(tmp_path)
    first = klines_to_frame(_rows(0, 5))
    second = klines_to_frame(_rows(3 * 3_600_000, 5))
    assert store.append("BTCUSDT", "1h", first) == 5
    assert store.append("BTCUSDT", "1h", second) == 8
    loaded = store.load("BTCUSDT", "1h")
    assert loaded["open_time"].is_monotonic_increasing and loaded["open_time"].is_unique
    assert store.last_open_time("BTCUSDT", "1h") == 7 * 3_600_000
    assert store.symbols("1h") == ["BTCUSDT"]


def test_funding_store_and_per_bar_alignment(tmp_path: Path) -> None:
    store = FundingStore(tmp_path)
    frame = pd.DataFrame(
        {"funding_time": [8 * 3_600_000, 16 * 3_600_000], "funding_rate": [0.0001, -0.0002], "mark_price": [1.0, 1.0]}
    )
    store.append("BTCUSDT", frame)
    bars = pd.date_range("1970-01-01", periods=24, freq="h", tz="UTC")
    per_bar = funding_per_bar(store.load("BTCUSDT"), bars)
    assert per_bar.iloc[8] == pytest.approx(0.0001)
    assert per_bar.iloc[16] == pytest.approx(-0.0002)
    assert per_bar.abs().sum() == pytest.approx(0.0003)


def test_funding_per_bar_keeps_settlements_stamped_past_the_bar_open(tmp_path: Path) -> None:
    """Binance stamps ``fundingTime`` 1-47 ms late; matching bar opens exactly dropped 43.7% of the archive."""
    store = FundingStore(tmp_path)
    store.append(
        "BTCUSDT",
        pd.DataFrame(
            {
                "funding_time": [8 * 3_600_000 + 5, 16 * 3_600_000 + 47, 16 * 3_600_000 + 1_800_000],
                "funding_rate": [0.0001, -0.0002, -0.0003],
                "mark_price": [1.0, 1.0, 1.0],
            }
        ),
    )
    bars = pd.date_range("1970-01-01", periods=24, freq="h", tz="UTC")
    per_bar = funding_per_bar(store.load("BTCUSDT"), bars)
    assert per_bar.iloc[8] == pytest.approx(0.0001)
    assert per_bar.iloc[16] == pytest.approx(-0.0005)  # both settlements inside bar 16 are summed
    assert per_bar.abs().sum() == pytest.approx(0.0006)


def test_funding_per_bar_uses_the_grid_the_bar_index_defines(tmp_path: Path) -> None:
    """A 4h panel must bin a 08:05-stamped settlement into the 08:00 bar, not into an hour that has no bar."""
    store = FundingStore(tmp_path)
    store.append(
        "BTCUSDT",
        pd.DataFrame(
            {"funding_time": [9 * 3_600_000 + 5], "funding_rate": [0.0004], "mark_price": [1.0]},
        ),
    )
    bars = pd.date_range("1970-01-01", periods=12, freq="4h", tz="UTC")
    per_bar = funding_per_bar(store.load("BTCUSDT"), bars)
    assert per_bar.loc[pd.Timestamp("1970-01-01 08:00", tz="UTC")] == pytest.approx(0.0004)
    assert per_bar.abs().sum() == pytest.approx(0.0004)


def test_archive_checksum_and_zip_parsing() -> None:
    csv = "open_time,open,high,low,close,volume,close_time,quote_volume,count,taker_buy_volume,taker_buy_quote_volume,ignore\n"
    csv += "1700000000000,1,2,0.5,1.5,3,1700003599999,4,1,1,1,0\n"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("BTCUSDT-1h-2023-11.csv", csv)
    payload = buffer.getvalue()
    frame = zip_to_frame(payload)
    assert len(frame) == 1 and int(frame["open_time"].iloc[0]) == 1700000000000
    import hashlib

    digest = hashlib.sha256(payload).hexdigest()
    assert parse_checksum(f"{digest}  BTCUSDT-1h-2023-11.zip\n") == digest
    verify_zip(payload, digest)
    with pytest.raises(ChecksumMismatch):
        verify_zip(payload, "0" * 64)
    assert [str(m) for m in month_range(Month(2023, 11), Month(2024, 2))] == ["2023-11", "2023-12", "2024-01"]


def test_universe_hysteresis_and_filters() -> None:
    rules = {
        **{
            f"S{i}USDT": InstrumentRules(
                f"S{i}USDT", *(__import__("decimal").Decimal(x) for x in ("0.1", "0.1", "0.1", "5"))
            )
            for i in range(30)
        },
        "BIGUSDT": InstrumentRules("BIGUSDT", *(__import__("decimal").Decimal(x) for x in ("0.1", "0.1", "0.1", "50"))),
        "XBUSD": InstrumentRules(
            "XBUSD", *(__import__("decimal").Decimal(x) for x in ("0.1", "0.1", "0.1", "5")), quote_asset="BUSD"
        ),
    }
    volume = {f"S{i}USDT": 1000.0 - i for i in range(30)}
    volume["BIGUSDT"] = 5000.0
    volume["XBUSD"] = 9000.0
    config = UniverseConfig(
        top_n=15, enter_rank=15, exit_rank=20, always_include=("S29USDT",), max_min_notional_usdt=20
    )
    chosen = refresh_selection(volume, rules, config, (), 0).symbols
    assert "BIGUSDT" not in chosen and "XBUSD" not in chosen
    assert "S29USDT" in chosen
    assert list(chosen[:15]) == [f"S{i}USDT" for i in range(15)]
    # S16 is rank 17: not entering fresh, but retained when previously held
    assert "S16USDT" not in chosen
    assert "S16USDT" in refresh_selection(volume, rules, config, ["S16USDT"], 0).symbols
    assert "S25USDT" not in refresh_selection(volume, rules, config, ["S25USDT"], 0).symbols  # beyond exit_rank


def test_parse_exchange_info() -> None:
    payload = {
        "symbols": [
            {
                "symbol": "BTCUSDT",
                "status": "TRADING",
                "contractType": "PERPETUAL",
                "quoteAsset": "USDT",
                "filters": [
                    {"filterType": "PRICE_FILTER", "tickSize": "0.10"},
                    {"filterType": "LOT_SIZE", "stepSize": "0.001", "minQty": "0.001"},
                    {"filterType": "MIN_NOTIONAL", "notional": "100"},
                ],
            }
        ]
    }
    rules = parse_exchange_info(payload)
    assert str(rules["BTCUSDT"].min_notional) == "100" and rules["BTCUSDT"].tradable


def test_store_reports_gaps_after_a_merge_with_a_hole(tmp_path: Path) -> None:
    """T-D01: the contract's second half — after the REST tail is merged, open_time must be contiguous."""
    from starquant_data.store import interval_ms

    store = KlineStore(tmp_path)
    step = interval_ms("1h")
    base = 1_700_000_000_000 // step * step

    def frame(opens: list[int]) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "open_time": opens,
                "open": [1.0] * len(opens),
                "high": [1.0] * len(opens),
                "low": [1.0] * len(opens),
                "close": [1.0] * len(opens),
                "volume": [1.0] * len(opens),
                "close_time": [o + step - 1 for o in opens],
            }
        )

    store.append("BTCUSDT", "1h", frame([base + i * step for i in range(5)]))
    assert store.gaps("BTCUSDT", "1h") == [], "a contiguous series has no gaps"

    # the archive month ends, and the REST tail resumes two bars later
    store.append("BTCUSDT", "1h", frame([base + i * step for i in (7, 8)]))
    gaps = store.gaps("BTCUSDT", "1h")
    assert gaps == [(base + 4 * step, base + 7 * step)], gaps

    store.append("BTCUSDT", "1h", frame([base + i * step for i in (5, 6)]))  # the hole is patched
    assert store.gaps("BTCUSDT", "1h") == []
    assert store.count("BTCUSDT", "1h") == 9
