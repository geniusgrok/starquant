"""`Panel._map` dropped `metrics`, so every slice silently lost the DL-D4 columns.

The cost is measured, not hypothetical.  The 2026-09-09 mine ran right after the metrics archive was
backfilled to 202/205 symbols - the whole reason for that backfill was the DL-D4 open-interest and
long/short leaves - and its report says `outcomes.errored = 90`.  The 90 are exactly the 54 `oi` and
36 `lsr` candidates: **not one metrics candidate has ever been scored, in any round**.

The failure is the shape this repository keeps finding.  `_required_metric` raises loudly, which is
right; the miner catches the raise and counts it, which is also defensible; and the count is all that
reaches the report - so a family that cannot run at all looks like a family that ran and lost.  The
expression itself is fine: on the panel it was handed it evaluates to 50.8% non-null over 205 symbols.
The miner slices, and the slice was a different panel.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from starquant_alpha.panel import Panel


def _panel(bars: int = 300, symbols: tuple[str, ...] = ("AAA", "BBB")) -> Panel:
    index = pd.date_range("2024-01-01", periods=bars, freq="1h", tz="UTC")
    frame = pd.DataFrame(
        100.0 + np.arange(bars * len(symbols)).reshape(bars, len(symbols)) * 0.01,
        index=index,
        columns=list(symbols),
    )
    return Panel(
        interval="1h",
        open=frame,
        high=frame * 1.001,
        low=frame * 0.999,
        close=frame,
        volume=frame,
        quote_volume=frame,
        metrics={"sum_open_interest": frame * 2.0, "count_long_short_ratio": frame * 0.5},
    )


def test_every_way_of_narrowing_a_panel_keeps_its_metrics() -> None:
    panel = _panel()
    assert panel.metric("sum_open_interest") is not None
    narrowed = {
        "slice": panel.slice(panel.close.index[50], panel.close.index[-1]),
        "tail": panel.tail(100),
        "select": panel.select(["AAA"]),
    }
    for name, out in narrowed.items():
        for column in ("sum_open_interest", "count_long_short_ratio"):
            frame = out.metric(column)
            assert frame is not None, f"{name} dropped panel.metrics[{column!r}]"
            assert frame.index.equals(out.close.index), f"{name} left {column} on the old index"
            assert list(frame.columns) == list(out.close.columns), f"{name} left {column} on the old symbols"


def test_a_panel_that_never_had_metrics_still_has_none_after_slicing() -> None:
    """The fix must not invent a column: absent stays absent, which is what `_required_metric` reads."""
    panel = _panel()
    bare = Panel(
        interval=panel.interval,
        open=panel.open,
        high=panel.high,
        low=panel.low,
        close=panel.close,
        volume=panel.volume,
    )
    assert bare.metric("sum_open_interest") is None
    assert bare.tail(10).metric("sum_open_interest") is None


def test_the_leaf_that_could_not_be_scored_can_be_scored_on_a_slice() -> None:
    """The regression in its own terms: the DL-D4 leaf, on a narrowed panel, without raising."""
    from starquant_alpha.mining.expr import ExprError

    panel = _panel()
    leaf = next(cls for cls in _metric_leaves() if getattr(cls, "COLUMN", None) == "count_long_short_ratio")
    node = leaf(72)  # type: ignore[call-arg]
    try:
        out = node.evaluate(panel.tail(200))
    except ExprError as exc:  # pragma: no cover - this is the bug, and it is fixed
        raise AssertionError(f"a metrics leaf still cannot read a narrowed panel: {exc}") from exc
    assert out.shape[0] == 200


def _metric_leaves() -> list[type]:
    import starquant_alpha.mining.expr as expr

    return [obj for obj in vars(expr).values() if isinstance(obj, type) and getattr(obj, "COLUMN", None)]
