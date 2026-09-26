"""What `apply_exits` costs on the panel `research overlay` actually runs it on (P1).

The review measured 15.22 s per pass over the 1h PIT panel - 49,937 bars x 205 symbols, about 10.2
million `exit_step` calls - and the default overlay grid enables 11 of its 12 cells, so one
`research overlay` spends roughly 165 s inside this one function.  This times the shipped path and the
one engine against the other on exactly the same arrays.

    python scratchpad/exit_overlay_timing.py
"""

from __future__ import annotations

import time

import numpy as np
import pandas as pd

from starquant_alpha.overlays import exits as ex
from starquant_data.store import KlineStore

SHIPPED = ex.ExitParams(stop_loss=6.0, take_profit=6.0)
GRID = {
    "shipped (stop+tp, no trailing, no regime)": SHIPPED,
    "with trailing": ex.ExitParams(stop_loss=6.0, take_profit=6.0, trailing_stop=3.0),
    "unit_mode=current": ex.ExitParams(stop_loss=6.0, take_profit=6.0, unit_mode="current"),
    "regime_window=168": ex.ExitParams(stop_loss=6.0, take_profit=6.0, regime_window=168),
}


def _close(symbols: list[str]) -> pd.DataFrame:
    store = KlineStore(".starquant/data")
    series: dict[str, pd.Series] = {}
    for symbol in symbols:
        frame = pd.read_parquet(store.path(symbol, "1h"), columns=["open_time", "close"])
        index = pd.to_datetime(frame["open_time"], unit="ms", utc=True)
        series[symbol] = pd.Series(frame["close"].to_numpy(dtype=float), index=index)
    return pd.DataFrame(series).sort_index()


def _time(call: object, repeats: int = 3) -> float:
    best = float("inf")
    for _ in range(repeats):
        start = time.perf_counter()
        call()  # type: ignore[operator]
        best = min(best, time.perf_counter() - start)
    return best


def main() -> int:
    membership = pd.read_parquet(".starquant/data/membership.parquet")
    store = KlineStore(".starquant/data")
    members = [s for s in membership.columns if bool(membership[s].any()) and store.exists(s, "1h")]
    close = _close(members)
    weights = (np.sign(close.pct_change(24, fill_method=None).fillna(0.0)) * 0.02).astype(float)
    calls = close.shape[0] * close.shape[1]
    print(f"panel: {close.shape[0]:,} bars x {close.shape[1]} symbols = {calls:,} symbol-bars\n")
    print(f"{'params':<44}{'stepwise':>12}{'vector':>12}{'speedup':>10}{'identical':>11}")
    for name, params in GRID.items():
        slow = _time(lambda p=params: ex._apply_exits(weights, close, p, None, ex._run_stepwise))
        fast = _time(lambda p=params: ex._apply_exits(weights, close, p, None, ex._run_vectorised))
        # The unit tests search for a counterexample on small panels; this is the same claim on the
        # panel `research overlay` actually runs, where the cooldown and the re-entry happen thousands
        # of times.  uint64, not `approx`: every weight has to be the same 64 bits.
        a = ex._apply_exits(weights, close, params, None, ex._run_stepwise)
        b = ex._apply_exits(weights, close, params, None, ex._run_vectorised)
        same = np.array_equal(a.weights.to_numpy().view(np.uint64), b.weights.to_numpy().view(np.uint64))
        pd.testing.assert_frame_equal(a.events, b.events, check_exact=True)
        print(f"{name:<44}{slow:>11.2f}s{fast:>11.2f}s{slow / fast:>9.1f}x{str(same) + f' ({len(a.events)})':>11}")
        assert same
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
