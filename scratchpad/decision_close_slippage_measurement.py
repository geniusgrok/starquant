"""M-Q08's own ruler, read for the first time: slippage against the DECISION CLOSE.

`config/costs.yaml` carries `slippage_bps: 2.0` as "the model's own assumption" and, beside it, a
5.52 bps reading taken against the PLAN PRICE - with the note that the plan price is the reference
L1-04 retired, so that figure is a sensitivity input and not a verdict.  The sentence it ends on is
"M-Q08's own ruler (`decision_close`) had no readings yet on 2026-09-08".

It does now.  `trades.jsonl` has carried `decision_close` since then, and this reads it.

Why `decision_close` is the denominator.  The loop decides on bar t's close and sends a MARKET order
seconds later, so "how far did the fill land from the close the decision was made on" is the whole of
what execution cost the book, signed so that positive is adverse.  The plan price is a different
thing - the mark the planner happened to read while sizing - and measuring against it answers a
question about the planner rather than about execution, which is why L1-04 retired it.

Note this is NOT the backtest's reference; see the paragraph on the gap below before comparing.

    python scratchpad/decision_close_slippage_measurement.py

Result, 2026-09-17, 213 recorded orders of which 81 are FILLED and carry both prices:

    n = 81, notional 32,019 USDT
    mean               +4.89 bps
    median             +2.96 bps
    notional-weighted  +4.43 bps      <- the number comparable to `slippage_bps`
    p10 / p90          -4.32 / +29.40 bps
    95% CI of the mean [-1.09, +10.87] bps

Read it carefully, because it does not say what it looks like it says.  TWO reasons, and the second
is the one that is easy to get wrong.

*The interval.*  The centre is 2.2x the 2.0 the backtest charges, and the interval still contains
2.0, so 81 demo fills over a handful of days cannot reject the shipped assumption - they can only
stop supporting it comfortably.  `slippage_stress_bps` already prices the book at 2.0 / 5.5 / 9.2,
so the measured centre sits inside a stress grid that is already run.

*The reference point, which would make this a NOT like-for-like comparison if it were left alone.*
`slippage_bps` is charged on top of a fill at the NEXT BAR'S OPEN (`open_to_close`), while this
measures the distance from the decision CLOSE.  The two differ by the close_t -> open_{t+1} gap, so
the backtest's cost seen from the decision close is "2.0 bps PLUS whatever that gap averages" and
4.43 has to be compared against the sum.  `--with-gap` computes the gap term on the same fills:

    n = 68 of the 81 (the rest have no 1h bar on both sides in the local archive)
    close_t -> open_{t+1}, signed so positive is adverse
      mean               +0.21 bps
      notional-weighted  -0.02 bps

So on THESE fills the gap is nil and the comparison survives being made carefully:

      backtest, from the decision close   ~ +1.98 bps   (-0.02 gap + 2.0 assumed)
      measured, from the decision close     +4.43 bps

about 2.2x, and still inside the interval above.  Worth keeping the two numbers apart anyway: the gap
is near zero over 68 demo fills in one regime, and `starquant_alpha.backtest` measures it at 2.36% of
total absolute price movement across five years with an OOS Sharpe cost of -0.029 - i.e. small and
adverse, not absent.  A quiet stretch is not a proof that the term is zero.

*And the limit that outranks both of the above: every one of these fills is DEMO.*  What a demo venue
does with a market order is not what the mainnet book would do with it - the matching is against a
different book, and KILL-Q12 has held real capital out of scope since 2026-09-05 for exactly this
class of reason.  So this measures the loop's execution path on the venue it actually trades, which
is worth knowing and is what M-Q08 asked for; it does not measure what this strategy would pay live
with real money, and no number here should be carried into that sentence.  The dispersion is the
tell: p90 at +29 bps against p10 at -4 says a minority of orders pay most of the cost, which is the
shape you would expect if the participation cap and the band are pushing size into the thinner names
- and thin names are precisely where a demo book and a real one differ most.

So the honest summary is narrow: the ruler costs.yaml said had no readings now has 81 demo readings,
the centre sits above the assumption, and the interval does not exclude it.  A first reading moves
the burden; it does not settle the number, and it cannot settle the mainnet one at all.

What would make it decisive: more fills, and fills that are not all demo.  The dispersion is the
problem rather than the centre - p90 at +29 bps against p10 at -4 says a minority of orders pay most
of the cost, which is the shape you would expect if the cap and the band are pushing size into the
thinner names.  Splitting by symbol liquidity is the next cut and is deliberately not made here: this
script exists to answer the one question costs.yaml left open, not to start a new search.
"""

from __future__ import annotations

import json
import statistics as stats
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRADES = ROOT / ".starquant/live/trades.jsonl"
HOUR_MS = 3_600_000


def fills() -> list[dict]:
    rows = [json.loads(line) for line in TRADES.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [r for r in rows if r.get("status") == "FILLED" and r.get("avg_price") and r.get("decision_close")]


def _sign(row: dict) -> float:
    """Positive is adverse: a BUY filling above the reference, a SELL filling below it."""
    return 1.0 if row.get("side") == "BUY" else -1.0


def readings() -> list[tuple[float, float]]:
    """(signed slippage in bps, filled notional) for every fill that carries both prices."""
    out: list[tuple[float, float]] = []
    for row in fills():
        average, decision = float(row["avg_price"]), float(row["decision_close"])
        if average <= 0 or decision <= 0:
            continue
        out.append((_sign(row) * (average / decision - 1.0) * 10_000.0, abs(float(row.get("executed_qty") or 0)) * average))
    return out


def gap_readings() -> list[tuple[float, float]]:
    """(signed close_t -> open_{t+1} gap in bps, notional) - the term that makes the two references meet."""
    from starquant_data.store import KlineStore

    store = KlineStore(str(ROOT / ".starquant/data"))
    frames: dict[str, object] = {}
    out: list[tuple[float, float]] = []
    for row in fills():
        symbol, bar = row["symbol"], int(row["bar_open_ms"])
        if symbol not in frames:
            try:
                frames[symbol] = store.load(symbol, "1h").set_index("open_time")
            except Exception:  # a symbol the local archive has never synced
                frames[symbol] = None
        frame = frames[symbol]
        if frame is None or bar not in frame.index or bar + HOUR_MS not in frame.index:
            continue
        close_t, open_next = float(frame.loc[bar, "close"]), float(frame.loc[bar + HOUR_MS, "open"])
        if close_t <= 0:
            continue
        notional = abs(float(row.get("executed_qty") or 0)) * float(row["avg_price"])
        out.append((_sign(row) * (open_next / close_t - 1.0) * 10_000.0, notional))
    return out


def main() -> None:
    sample = readings()
    if not sample:
        print("no fill carries both avg_price and decision_close")
        return
    bps = [value for value, _ in sample]
    notional = [size for _, size in sample]
    total = sum(notional)
    ordered = sorted(bps)
    error = stats.stdev(bps) / len(bps) ** 0.5 if len(bps) > 1 else 0.0
    mean = stats.mean(bps)
    print(f"n = {len(bps)}, notional {total:,.0f} USDT")
    print(f"  mean               {mean:+.2f} bps")
    print(f"  median             {stats.median(bps):+.2f} bps")
    print(f"  notional-weighted  {sum(v * n for v, n in sample) / total:+.2f} bps")
    print(f"  p10 / p90          {ordered[len(ordered) // 10]:+.2f} / {ordered[-max(1, len(ordered) // 10)]:+.2f} bps")
    print(f"  95% CI of the mean [{mean - 1.96 * error:+.2f}, {mean + 1.96 * error:+.2f}] bps")
    print()
    print("costs.yaml charges slippage_bps 2.0; slippage_stress_bps already prices 2.0 / 5.5 / 9.2.")
    if "--with-gap" not in sys.argv:
        print("pass --with-gap to price the close -> open term the backtest's reference point needs.")
        return
    gaps = gap_readings()
    if not gaps:
        print("\nno fill has a 1h bar on both sides in the local archive; run `starquant data sync` first")
        return
    gap_total = sum(size for _, size in gaps)
    gap_weighted = sum(value * size for value, size in gaps) / gap_total
    print()
    print(f"close_t -> open_(t+1) on the same fills, n = {len(gaps)}")
    print(f"  mean               {stats.mean([v for v, _ in gaps]):+.2f} bps")
    print(f"  notional-weighted  {gap_weighted:+.2f} bps")
    print()
    print(f"  backtest, from the decision close  ~ {gap_weighted + 2.0:+.2f} bps  (gap + slippage_bps)")
    print(f"  measured, from the decision close    {sum(v * n for v, n in sample) / total:+.2f} bps")


if __name__ == "__main__":
    main()
