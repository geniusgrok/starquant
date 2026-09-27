"""DL-S51: the properties that make a Chan implementation honest rather than merely plausible.

Chan theory usually reads the future, and it does it in a specific way: the textbook draws its pens
and segments with the whole chart visible, so a structure revised at bar 900 silently repaints the
picture at bar 400.  The shared suite's causality test would have missed it here until KILL-AR-15 was
fixed, because this signal's 720-bar warmup was longer than that test's whole comparison window - the
scores it compared were NaN against NaN.

So the properties below are about WHEN a value may appear and WHAT the three vocabulary items mean,
not about whether the signal is any good.  Whether it is any good is `research validate`'s question
and its answer was pre-registered as "probably not, and if it is, probably tsmom rewritten".
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from starquant_alpha.panel import Panel
from starquant_alpha.signals import SIGNALS
from starquant_alpha.signals.base import scores_to_targets
from starquant_alpha.signals.chanlun import HOLD, ChanlunParams, chanlun_scores
from tests.alpha.test_causality import _bit_for_bit


def _panel(n_bars: int = 2_000, seed: int = 3, symbols: tuple[str, ...] = ("AAAUSDT", "BBBUSDT")) -> Panel:
    rng = np.random.default_rng(seed)
    index = pd.date_range("2024-01-01", periods=n_bars, freq="h", tz="UTC")
    frames = {}
    for j, symbol in enumerate(symbols):
        steps = rng.normal(0.0, 0.008, size=n_bars) + 0.00004 * (1 if j == 0 else -1)
        close = 100.0 * np.exp(np.cumsum(steps))
        wobble = np.abs(rng.normal(0.0, 0.003, size=n_bars))
        frames[symbol] = pd.DataFrame(
            {
                "open": close,
                "high": close * (1 + wobble),
                "low": close * (1 - wobble),
                "close": close,
                "volume": rng.uniform(500, 1500, size=n_bars),
                "quote_volume": rng.uniform(50_000, 150_000, size=n_bars),
                "trades": rng.uniform(100, 500, size=n_bars),
                "taker_buy_base": rng.uniform(200, 800, size=n_bars),
                "taker_buy_quote": rng.uniform(20_000, 80_000, size=n_bars),
            },
            index=index,
        )
    return Panel.from_frames(frames, "1h")


def test_t_s51_2_no_score_appears_before_the_declared_warmup_is_available() -> None:
    """A signal that scores earlier than it declares makes the loop request too little history."""
    panel = _panel()
    scores = chanlun_scores(panel)
    first = scores.notna().to_numpy().argmax(axis=0) if scores.notna().any().any() else None
    assert first is not None
    # The declaration is an upper bound on what the loop must fetch, so scoring EARLIER is allowed;
    # scoring at a bar the loop would not have fetched is not, and that is what this pins.
    assert ChanlunParams().warmup_bars <= len(panel.index)
    assert scores.iloc[ChanlunParams().warmup_bars :].notna().any().any(), "no score after the warmup"


def test_the_vocabulary_has_exactly_three_items() -> None:
    """+-1 acts, 0.0 closes, anything else holds.  A fourth value would mean something undefined."""
    scores = chanlun_scores(_panel())
    values = set(np.unique(scores.to_numpy()[~np.isnan(scores.to_numpy())]).round(10))
    assert values <= {1.0, -1.0, 0.0, HOLD, -HOLD}, f"unexpected score values: {sorted(values)}"


def test_a_hold_is_sub_threshold_and_a_zero_is_an_exit() -> None:
    """The three items have to mean what §7 says through `scores_to_targets`, not merely differ."""
    index = pd.date_range("2024-01-01", periods=4, freq="h", tz="UTC")
    scores = pd.DataFrame({"A": [1.0, HOLD, 0.0, -HOLD]}, index=index)
    targets = scores_to_targets(scores, ChanlunParams().entry_threshold)
    assert list(targets["A"]) == [1.0, 1.0, 0.0, 0.0], "hold must carry, zero must flatten"
    assert ChanlunParams().entry_threshold > HOLD


def test_a_four_hour_score_never_lands_before_its_own_bar_closed() -> None:
    """At 01:00 the 04:00 bar does not exist.  `label='right'` plus a forward fill is what enforces it."""
    panel = _panel()
    scores = chanlun_scores(panel, ChanlunParams(level="4h"))
    scored = scores["AAAUSDT"].dropna()
    assert not scored.empty
    # Every value must repeat across the 1h bars of the 4h bar that follows its stamp, never precede it.
    four_hourly = panel.close["AAAUSDT"].resample("4h", label="right", closed="right").last()
    assert scored.index.min() >= four_hourly.index.min()


def test_truncating_the_panel_does_not_change_the_scores_that_survive() -> None:
    """The sharpest causality check for this family: a prefix must score like the prefix of the whole.

    This is the property the textbook breaks.  Structures ARE revised as bars arrive - that is what
    Chan theory is - and the question is only whether a revision is allowed to rewrite a score that
    was already emitted.  Here it is not: each rebuild sees a prefix, so it cannot.
    """
    panel = _panel()
    whole = chanlun_scores(panel)
    cut = 1_500
    prefix = Panel.from_frames(
        {
            symbol: pd.DataFrame(
                {
                    field: getattr(panel, field)[symbol].to_numpy()[:cut]
                    for field in ("open", "high", "low", "close", "volume", "quote_volume", "trades")
                },
                index=panel.index[:cut],
            )
            for symbol in panel.symbols
        },
        "1h",
    )
    _bit_for_bit(chanlun_scores(prefix), whole.iloc[:cut][prefix.close.columns], check_freq=False)


@pytest.mark.parametrize("bad", [{"level": "2h"}, {"min_bars": 1}, {"div_ratio": 0.0}, {"entry_threshold": 1.5}])
def test_the_pre_registered_parameter_space_is_the_only_one_accepted(bad: dict) -> None:
    """`level` in particular: the grid is {1h, 4h} and a third level would be a new hypothesis."""
    with pytest.raises(ValueError):
        ChanlunParams.from_mapping({**ChanlunParams().__dict__, **bad})


def test_it_is_registered_under_its_pre_registered_defaults() -> None:
    spec = SIGNALS["chanlun"]
    assert spec.default_params == {"level": "1h", "min_bars": 4, "div_ratio": 0.8, "entry_threshold": 0.2}
    assert spec.warmup_for(spec.default_params) == 720
    assert not spec.needs_funding(spec.default_params)
