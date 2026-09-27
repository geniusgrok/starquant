"""#17 read "research yes, live no" for a plumbing reason, and the mapping under it was wrong too.

`snapshot_metrics` polled `/futures/data/openInterestHist` and nothing else.  That page serves the two
open-interest fields; the four ratio columns come from four OTHER endpoints.  So every row the live
recorder ever wrote had those four as NaN, while the research archive had them - measured 2026-09-12 on
the production store: `sum_open_interest` 0% NaN, all four ratios **100%**.

`metrics_parity` folds columns into a row verdict and skips NaN pairs, so it read `differing: 0` over
data it never compared and the M-011 gate reported parity met.  Agreement on a neighbouring column is
not evidence about this one - `alignment.py` had already written that sentence down; what was missing
was anything that made it false.

The second finding is in the map itself: `longAccount -> count_toptrader_long_short_ratio` is the wrong
quantity.  `longAccount` is the long ACCOUNT SHARE (0.6298 live) and that archive column is a RATIO
(BTCUSDT median 1.5249, range 0.4993-5.3241).  It never fired only because the endpoint that returns
`longAccount` was never polled.  Each mapping below was checked against its own column's archived range
before the change.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pandas as pd

from starquant_data.metrics import REST_SOURCES, VALUE_COLUMNS, parse_rest_rows
from starquant_data.metrics_snapshot import snapshot_metrics
from starquant_data.store import MetricsStore

STAMP = 1_789_219_200_000 + 300_000 - 1  # a REST close stamp inside the 5m bucket opening at STAMP-…
FIVE_MIN = 300_000

#: What each endpoint actually returns, keyed by the last path segment.
PAGES: dict[str, dict[str, Any]] = {
    "openInterestHist": {"symbol": "BTCUSDT", "sumOpenInterest": "103708.403", "sumOpenInterestValue": "8010960215.4"},
    "topLongShortAccountRatio": {"symbol": "BTCUSDT", "longShortRatio": "1.7012", "longAccount": "0.6298"},
    "topLongShortPositionRatio": {"symbol": "BTCUSDT", "longShortRatio": "2.1974", "longAccount": "0.6873"},
    "globalLongShortAccountRatio": {"symbol": "BTCUSDT", "longShortRatio": "1.6323", "longAccount": "0.6202"},
    "takerlongshortRatio": {"buySellRatio": "0.3691", "buyVol": "1.0", "sellVol": "2.7"},  # no symbol echoed
}


class _Client:
    def __init__(self, empty: set[str] = frozenset()) -> None:
        self.calls: list[str] = []
        self.empty = empty

    async def get(self, path: str, params: Any = None) -> Any:
        name = path.rsplit("/", 1)[-1]
        self.calls.append(name)
        if name in self.empty:
            return []
        return [{**PAGES[name], "timestamp": STAMP}]


def _snapshot(tmp_path: Path, client: _Client) -> tuple[dict, pd.DataFrame]:
    store = MetricsStore(tmp_path, kind="metrics_snapshot")
    result = asyncio.run(snapshot_metrics(client, store, ["BTCUSDT"]))
    return result, store.load("BTCUSDT")


def test_every_value_column_is_populated_not_just_open_interest(tmp_path: Path) -> None:
    """The whole defect in one assertion: no column may be NaN across the board."""
    _result, frame = _snapshot(tmp_path, _Client())
    for column in VALUE_COLUMNS:
        assert frame[column].notna().any(), f"{column} is NaN in every row - the 2026-09-12 shape"


def test_each_ratio_lands_in_the_column_its_own_archive_range_supports(tmp_path: Path) -> None:
    """The mapping, checked value by value.  A wrong pairing is silent: both sides are floats."""
    _result, frame = _snapshot(tmp_path, _Client())
    row = frame.iloc[-1]
    assert row["count_toptrader_long_short_ratio"] == 1.7012  # topLongShortAccountRatio.longShortRatio
    assert row["sum_toptrader_long_short_ratio"] == 2.1974  # topLongShortPositionRatio.longShortRatio
    assert row["count_long_short_ratio"] == 1.6323  # globalLongShortAccountRatio.longShortRatio
    assert row["sum_taker_long_short_vol_ratio"] == 0.3691  # takerlongshortRatio.buySellRatio
    assert row["sum_open_interest"] == 103708.403


def test_the_long_account_share_never_reaches_a_ratio_column(tmp_path: Path) -> None:
    """The falsifier for the old map: 0.6298 is a share and must not appear as a ratio anywhere."""
    _result, frame = _snapshot(tmp_path, _Client())
    shares = {0.6298, 0.6873, 0.6202}
    for column in VALUE_COLUMNS:
        assert not set(frame[column].dropna()) & shares, f"{column} took an account share"


def test_the_page_that_does_not_echo_the_symbol_still_gets_one(tmp_path: Path) -> None:
    """`takerlongshortRatio` returns no `symbol`; a blank one would split the store's rows."""
    frame = parse_rest_rows(
        [{**PAGES["takerlongshortRatio"], "timestamp": STAMP}],
        FIVE_MIN,
        {"buySellRatio": "sum_taker_long_short_vol_ratio"},
        symbol="TUTUSDT",
    )
    assert frame["symbol"].tolist() == ["TUTUSDT"]


def test_an_endpoint_that_stops_answering_is_named_rather_than_left_as_nan(tmp_path: Path) -> None:
    """NaN in this store is exactly what `metrics_parity` cannot see, so silence is the wrong report."""
    result, frame = _snapshot(tmp_path, _Client(empty={"takerlongshortRatio"}))
    assert result["missing"] == {"BTCUSDT": ["takerlongshortRatio"]}
    assert frame["sum_taker_long_short_vol_ratio"].isna().all()
    assert frame["count_long_short_ratio"].notna().any(), "the other four still recorded"


def test_all_five_endpoints_are_polled_once_per_symbol(tmp_path: Path) -> None:
    client = _Client()
    _snapshot(tmp_path, client)
    assert sorted(client.calls) == sorted(path.rsplit("/", 1)[-1] for path, _ in REST_SOURCES)
    assert len(client.calls) == 5
