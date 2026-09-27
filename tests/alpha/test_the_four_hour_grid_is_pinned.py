"""chanlun `level: "4h"` groups 01-05, not 00-04, and that is a decision rather than a bug.

The panel is indexed by bar OPEN time.  `resample(rule, label="right", closed="right")` therefore puts
the 01:00/02:00/03:00/04:00 opens - real time 01:00 to 05:00 - into one group stamped 04:00.  Causally
that stamp is the correct one: the group's last input closes at 05:00, and 05:00 is exactly where the
information set of the DECISION bar 04:00 ends, so the `ffill` onto the 1h grid can never land a value
on a bar that predates its own inputs.

The price is that this is not Binance's 4h candle (00-04, 04-08, ...), so a `level: "4h"` structure
compared against a 4h chart will disagree, and the disagreement will be in the grid rather than in the
algorithm.  chanlun is not enabled, so nothing is being traded on it either way.

This file exists because the obvious "fix" - `label="left", closed="left"` - is a one-word edit that
looks like a tidy-up and is a strategy change plus a one-bar look-ahead.  Pinning the grouping makes
that edit fail a test that says so, instead of quietly re-deciding a signal.  Changing the grid on
purpose means changing this file in the same commit, with the evidence.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from starquant_alpha.panel import Panel
from starquant_alpha.signals.chanlun import LEVELS, ChanlunParams, chanlun_scores
from tests.alpha.test_causality import _bit_for_bit

RULE = LEVELS["4h"]


def _panel(n: int = 96, seed: int = 3) -> Panel:
    rng = np.random.default_rng(seed)
    index = pd.date_range("2024-05-01", periods=n, freq="h", tz="UTC")
    close = pd.Series(100.0 * np.exp(np.cumsum(rng.normal(0.0, 0.004, n))), index=index)
    frame = pd.DataFrame(
        {
            "open_time": index,
            "open": close.to_numpy(),
            "high": (close * 1.003).to_numpy(),
            "low": (close * 0.997).to_numpy(),
            "close": close.to_numpy(),
            "volume": 1_000.0,
        }
    )
    return Panel.from_frames({"BTCUSDT": frame}, interval="1h")


def test_the_group_stamped_at_0400_is_the_0100_to_0400_opens() -> None:
    panel = _panel()
    high = panel.high.resample(RULE, label="right", closed="right").max()
    stamp = pd.Timestamp("2024-05-02 04:00", tz="UTC")
    members = panel.index[(panel.index > stamp - pd.Timedelta(hours=4)) & (panel.index <= stamp)]
    assert [str(s.time()) for s in members] == ["01:00:00", "02:00:00", "03:00:00", "04:00:00"]
    assert float(high.loc[stamp].iloc[0]) == float(panel.high.loc[members].max().iloc[0])
    # And the venue's own candle - the 00/01/02/03 opens - is NOT what this produces.  Asserted by
    # moving one bar rather than by comparing two maxima, which can coincide by luck.
    venue_only, ours_only = stamp - pd.Timedelta(hours=4), stamp
    spiked = panel.high.copy()
    spiked.loc[venue_only] = spiked.loc[venue_only] * 10.0
    assert float(spiked.resample(RULE, label="right", closed="right").max().loc[stamp].iloc[0]) == float(
        high.loc[stamp].iloc[0]
    ), "the 00:00 open belongs to the previous group here; on the venue's grid it would belong to this one"
    spiked = panel.high.copy()
    spiked.loc[ours_only] = spiked.loc[ours_only] * 10.0
    assert float(spiked.resample(RULE, label="right", closed="right").max().loc[stamp].iloc[0]) > float(
        high.loc[stamp].iloc[0]
    ), "the 04:00 open belongs to this group; on the venue's grid it would open the next one"


def test_a_four_hour_score_is_never_readable_before_the_bar_that_closes_it() -> None:
    """The property `closed="right"` is paying for: the score at 04:00 needs data through 05:00.

    Perturbing the 04:00 bar - the last input of the group stamped 04:00 - must not move any 1h score
    at or before 04:00.  Under `label="left"` it would, because the group stamped 04:00 would then be
    the 04/05/06/07 opens and the `ffill` would put it on the 04:00 decision bar.
    """
    params = ChanlunParams(level="4h")
    panel = _panel()
    before = chanlun_scores(panel, params)
    poked = panel.high.copy()
    stamp = pd.Timestamp("2024-05-02 04:00", tz="UTC")
    poked.loc[stamp] = poked.loc[stamp] * 1.5
    after = chanlun_scores(Panel(**{**panel.__dict__, "high": poked}), params)
    head = panel.index[panel.index <= stamp]
    _bit_for_bit(before.loc[head], after.loc[head])


def test_the_one_hour_level_is_not_resampled_at_all() -> None:
    panel = _panel()
    scores = chanlun_scores(panel, ChanlunParams(level="1h"))
    assert list(scores.index) == list(panel.index)
