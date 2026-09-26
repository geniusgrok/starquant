"""T-D5-2: spot prices reach the panel, and neither a look-ahead nor a fill comes with them.

Two rules, both structural rather than remembered.

CAUSALITY.  Both markets stamp `open_time` on the same UTC boundary (measured 2026-09-09: every bar of
2026-08 in both markets satisfies `open_time % 3_600_000 == 0`), so the spot bar opening at t closes at
exactly the instant the perp bar opening at t closes.  A perp bar may read that spot bar and no other.
Reading the NEXT one - the obvious off-by-one, and the one DL-D2 actually found one market over - is
free money in a backtest and unavailable live.

NO FILL.  XMRUSDT's spot listing has been halted since 2024-02-20 02:00 at 118.70 while its perpetual
trades at 503.83 (2026-09-09).  Under "the latest value that had closed" - the rule `metrics.align_to_bars`
uses, correctly, for open interest - a basis leaf would read +324% and hold it for two years.  So a hole
in the spot series is NaN, in the panel and in the column, all the way to whatever reads it.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from starquant_alpha.panel import Panel

BARS = pd.date_range("2024-01-01", periods=48, freq="h", tz="UTC")
SYMBOLS = ("BTCUSDT", "1000SHIBUSDT", "FARTCOINUSDT")
HOUR_MS = 3_600_000


def _frames() -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(3)
    out = {}
    for symbol in SYMBOLS:
        close = 100.0 * np.exp(np.cumsum(rng.normal(0, 0.004, len(BARS))))
        out[symbol] = pd.DataFrame(
            {"open": close, "high": close * 1.001, "low": close * 0.999, "close": close, "volume": 1_000.0},
            index=BARS,
        )
    return out


def _spot(index: pd.DatetimeIndex = BARS) -> dict[str, pd.DataFrame]:
    values = pd.DataFrame(99.0, index=index, columns=list(SYMBOLS))
    return {"close": values, "quote_volume": values * 10.0}


def test_a_spot_frame_that_is_not_on_the_bar_index_is_refused_rather_than_reindexed() -> None:
    """`Panel` cannot know what a caller's stamps meant, so it may not fix them - only refuse them."""
    with pytest.raises(ValueError, match="align_spot_to_perp_bars"):
        Panel.from_frames(_frames(), "1h", spot=_spot(BARS + pd.Timedelta(minutes=30)))


def test_a_panel_without_spot_answers_none_rather_than_zero() -> None:
    """ "Nobody ingested spot" and "this perpetual has no spot leg" are different facts (see below)."""
    assert Panel.from_frames(_frames(), "1h").spot_field("close") is None


def test_the_spot_columns_survive_a_slice_because_a_holdout_split_may_not_delete_a_leg() -> None:
    """A basis leaf is scored on `panel.slice(end=cutoff)`; a field dropped there is a leg that exists
    in-sample and vanishes out-of-sample, which is the worst possible direction for that to go."""
    panel = Panel.from_frames(_frames(), "1h", spot=_spot())

    cut = panel.slice(start=BARS[10])
    tail = panel.tail(5)
    chosen = panel.select(["BTCUSDT"])

    assert cut.spot_field("close") is not None and len(cut.spot_field("close")) == len(BARS) - 10
    assert tail.spot_field("close") is not None and len(tail.spot_field("close")) == 5
    assert list(chosen.spot_field("close").columns) == ["BTCUSDT"]


# --- the alignment itself ----------------------------------------------------------------------------


def _stored(open_times: list[int], closes: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open_time": open_times,
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "quote_volume": [1_000.0] * len(closes),
        }
    )


def _bars(n: int) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(pd.to_datetime([i * HOUR_MS for i in range(n)], unit="ms", utc=True))


def test_a_bar_reads_the_spot_bar_that_shares_its_open_time() -> None:
    from starquant_data.spot import align_spot_to_perp_bars

    bars = _bars(4)
    aligned = align_spot_to_perp_bars(_stored([0, HOUR_MS, 2 * HOUR_MS, 3 * HOUR_MS], [10.0, 11.0, 12.0, 13.0]), bars)

    assert list(aligned["close"]) == [10.0, 11.0, 12.0, 13.0]


def test_a_bar_never_reads_a_spot_bar_from_the_future() -> None:
    """The off-by-one that DL-D2 found one market over.  It raises nothing, so it has to be pinned."""
    from starquant_data.spot import align_spot_to_perp_bars

    bars = _bars(3)
    # The spot series starts one bar LATE, so bar 0 has no counterpart at all.
    aligned = align_spot_to_perp_bars(_stored([HOUR_MS, 2 * HOUR_MS], [11.0, 12.0]), bars)

    assert pd.isna(aligned["close"].iloc[0]), "bar 0 borrowed the bar that opens an hour after it"
    assert list(aligned["close"].iloc[1:]) == [11.0, 12.0]


def test_a_hole_in_the_spot_series_stays_a_hole() -> None:
    """XMRUSDT's shape: a halted listing forward-filled reads as a basis, and a basis is a trade."""
    from starquant_data.spot import align_spot_to_perp_bars

    bars = _bars(5)
    aligned = align_spot_to_perp_bars(_stored([0, HOUR_MS, 4 * HOUR_MS], [10.0, 11.0, 40.0]), bars)

    assert list(aligned["close"].isna()) == [False, False, True, True, False]
    assert aligned["close"].iloc[2] != 11.0 and aligned["close"].iloc[3] != 11.0


def test_a_spot_series_that_stops_leaves_every_later_bar_missing() -> None:
    """The halt measured on the venue: spot stops in 2024 and the perpetual keeps trading for two years."""
    from starquant_data.spot import align_spot_to_perp_bars

    bars = _bars(6)
    aligned = align_spot_to_perp_bars(_stored([0, HOUR_MS], [118.7, 118.7]), bars)

    assert aligned["close"].iloc[2:].isna().all()


def test_the_multiplier_is_applied_to_prices_and_not_to_the_quote_volume() -> None:
    """1000SHIBUSDT quotes a thousand SHIB.  Both legs must be in one unit before anything divides them,
    and USDT volume is already in one unit - scaling it too would be the mirror-image error."""
    from starquant_data.spot import align_spot_to_perp_bars

    aligned = align_spot_to_perp_bars(_stored([0, HOUR_MS], [0.00001, 0.00002]), _bars(2), multiplier=1000.0)

    assert list(aligned["close"]) == [0.01, 0.02]
    assert list(aligned["quote_volume"]) == [1_000.0, 1_000.0]


def test_an_empty_spot_series_gives_a_column_of_nan_rather_than_no_column() -> None:
    """A shape that is always present makes "no spot" answerable; a missing key makes it a KeyError."""
    from starquant_data.spot import SPOT_PANEL_COLUMNS, align_spot_to_perp_bars

    aligned = align_spot_to_perp_bars(pd.DataFrame(), _bars(3))

    assert list(aligned.columns) == list(SPOT_PANEL_COLUMNS)
    assert aligned.isna().all().all()


# --- store -> panel, through the composition the CLI and the loop share -------------------------------


def test_a_perpetual_with_no_spot_leg_is_an_all_nan_column_not_an_absent_one(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """166 of 528 perpetuals have no spot at all, so the panel has to be able to SAY that about a symbol
    it carries.  A dropped column would make the basis leaf silently score a smaller universe than the
    one it was validated on - and the panel's own `symbols` would not agree with the spot frame's."""
    from starquant_data.spot import SpotMapping, write_spot_map
    from starquant_data.store import SPOT_KLINE_KIND, KlineStore
    from starquant_live.composition import load_panel

    perp_store = KlineStore(tmp_path)
    spot_store = KlineStore(tmp_path, kind=SPOT_KLINE_KIND)
    opens = [i * HOUR_MS for i in range(4)]
    for symbol in SYMBOLS:
        perp_store.append(symbol, "1h", _stored(opens, [100.0, 101.0, 102.0, 103.0]).assign(volume=1.0))
    spot_store.append("BTCUSDT", "1h", _stored(opens, [99.0, 100.0, 101.0, 102.0]).assign(volume=1.0))
    spot_store.append("SHIBUSDT", "1h", _stored(opens, [0.1, 0.101, 0.102, 0.103]).assign(volume=1.0))
    write_spot_map(
        tmp_path,
        {
            "BTCUSDT": SpotMapping("BTCUSDT", "BTCUSDT", 1.0),
            "1000SHIBUSDT": SpotMapping("1000SHIBUSDT", "SHIBUSDT", 1000.0),
            "FARTCOINUSDT": SpotMapping("FARTCOINUSDT", None),
        },
    )

    panel = load_panel(perp_store, list(SYMBOLS), "1h", spot_store=spot_store)

    close = panel.spot_field("close")
    assert close is not None
    assert list(close.columns) == panel.symbols
    assert close["FARTCOINUSDT"].isna().all(), "a perpetual with no spot leg must read as missing"
    assert close["BTCUSDT"].iloc[0] == pytest.approx(99.0)
    assert close["1000SHIBUSDT"].iloc[0] == pytest.approx(100.0), "the multiplier was not applied on the way in"


def test_a_spot_symbol_that_was_never_downloaded_reads_as_missing_rather_than_as_zero(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """The defect this repository keeps finding: a value that could not be computed coming back as a
    number that looks fine.  A mapped symbol with no parquet is NaN, exactly like an unmapped one."""
    from starquant_data.spot import SpotMapping, write_spot_map
    from starquant_data.store import SPOT_KLINE_KIND, KlineStore
    from starquant_live.composition import load_panel

    perp_store = KlineStore(tmp_path)
    spot_store = KlineStore(tmp_path, kind=SPOT_KLINE_KIND)
    opens = [i * HOUR_MS for i in range(4)]
    perp_store.append("BTCUSDT", "1h", _stored(opens, [100.0, 101.0, 102.0, 103.0]).assign(volume=1.0))
    perp_store.append("ETHUSDT", "1h", _stored(opens, [10.0, 11.0, 12.0, 13.0]).assign(volume=1.0))
    spot_store.append("BTCUSDT", "1h", _stored(opens, [99.0, 100.0, 101.0, 102.0]).assign(volume=1.0))
    write_spot_map(
        tmp_path,
        {"BTCUSDT": SpotMapping("BTCUSDT", "BTCUSDT"), "ETHUSDT": SpotMapping("ETHUSDT", "ETHUSDT")},
    )

    panel = load_panel(perp_store, ["BTCUSDT", "ETHUSDT"], "1h", spot_store=spot_store)

    close = panel.spot_field("close")
    assert close is not None and close["ETHUSDT"].isna().all()
    assert (close["ETHUSDT"] == 0.0).sum() == 0


def test_a_root_with_no_spot_at_all_builds_the_same_panel_as_before(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """The ingest must cost nothing to every caller that does not use it."""
    from starquant_data.store import SPOT_KLINE_KIND, KlineStore
    from starquant_live.composition import load_panel

    perp_store = KlineStore(tmp_path)
    opens = [i * HOUR_MS for i in range(4)]
    perp_store.append("BTCUSDT", "1h", _stored(opens, [100.0, 101.0, 102.0, 103.0]).assign(volume=1.0))

    panel = load_panel(perp_store, ["BTCUSDT"], "1h", spot_store=KlineStore(tmp_path, kind=SPOT_KLINE_KIND))

    assert panel.spot_field("close") is None
    assert list(panel.close["BTCUSDT"]) == [100.0, 101.0, 102.0, 103.0]
