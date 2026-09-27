"""Block 4 #42 (VWAP): what this ledger's orders actually cost in impact, per fill.

The question a VWAP/child-order execution layer has to answer first is not "can we build it" but
"what is there to recover".  Under the DL-C1 square-root law the whole benefit of slicing is that
impact is concave in size: splitting one order into N equal children costs
``N * (Q/N) * c * sigma * sqrt((Q/N)/ADV) = impact(Q) / sqrt(N)``, so a perfect N-way split recovers
``(1 - 1/sqrt(N))`` of the impact and NOTHING else - not fee, not spread, not the flat slippage the
cost model already charges.  So the deliverable is one number: impact bps on the fills this account
actually produced.

Measured against the same rulers the system already uses, on purpose:
  * ADV as ``starquant_alpha.backtest.impact_costs`` builds it - trailing mean hourly quote volume over
    ``adv_window`` bars, times bars-per-day, shifted so the fill's own bar is not in its own ADV.
  * sigma_daily as that function builds it - trailing std of hourly close-to-close returns over
    ``vol_window``, times sqrt(bars per day), shifted.
  * the live participation ruler separately, because it is a DIFFERENT quantity: `plan_rebalance`
    compares an order against ``max_participation * mean hourly quote volume`` over
    ``liquidity_window`` (24) bars, i.e. an hour of volume, not a day of it.  Reporting only one of
    the two is how "participation" ends up meaning two things in one conversation.

Reads `.starquant/live/trades.jsonl` and the kline archive.  Writes nothing.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import os
from pathlib import Path

import pandas as pd

from starquant_shared.config import load_yaml

ROOT = Path(os.environ.get("STARQUANT_DATA_ROOT", "~/starquant/.starquant/data"))
LEDGER = Path(os.environ.get("STARQUANT_TRADES", "~/starquant/.starquant/live/trades.jsonl"))
BARS_PER_DAY = 24
# A perfect 4-way split recovers 1 - 1/sqrt(4) = 50% of impact; 10-way recovers 68%.  4 is the
# generous-but-not-absurd end of what an hourly loop can slice without holding the target open for
# most of the bar, so it is the number the recoverable column is priced at.
SLICES = 4


def _fills() -> list[dict]:
    rows = []
    for line in LEDGER.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        qty = abs(float(row.get("executed_qty") or 0.0))
        if row.get("status") not in {"FILLED", "PARTIAL"} or qty <= 0:
            continue
        price = float(row.get("avg_price") or 0.0) or float(row.get("price") or 0.0)
        if price <= 0:
            continue
        row["_notional"] = qty * price
        # `flatten` rows carry no `bar_open_ms` (they are not a cycle's decision), and the kline
        # archive lags the loop by up to a day.  Both are priced at the last bar at or before the
        # fill rather than dropped: dropping them would silently exclude the flatten event and the
        # newest fills, and the newest fills are the ones on the symbols the pool just added.
        row["_bar_ms"] = int(row["bar_open_ms"]) if row.get("bar_open_ms") else _floor_hour(str(row["at"]))
        rows.append(row)
    return rows


def _floor_hour(stamp: str) -> int:
    at = dt.datetime.fromisoformat(stamp)
    return int(at.replace(minute=0, second=0, microsecond=0).timestamp()) * 1000


def _series(symbol: str) -> pd.DataFrame | None:
    path = ROOT / "klines" / symbol / "1h.parquet"
    if not path.exists():
        return None
    frame = pd.read_parquet(path)
    frame = frame.sort_values("open_time").set_index("open_time")
    quote = frame["quote_volume"].astype(float)
    close = frame["close"].astype(float)
    out = pd.DataFrame(index=frame.index)
    # Shifted so a fill's own bar never prices its own impact - the same causality `impact_costs` keeps.
    out["adv"] = (quote.rolling(720, min_periods=1).mean() * BARS_PER_DAY).shift(1)
    out["hourly"] = quote.rolling(24, min_periods=1).mean().shift(1)
    out["sigma_daily"] = close.pct_change().rolling(720, min_periods=180).std().shift(1) * math.sqrt(BARS_PER_DAY)
    return out


def main() -> None:
    costs = load_yaml("config/costs.yaml")
    coefficient = float((costs.get("impact") or {}).get("coefficient", 1.0))
    profile = load_yaml("config/live.demo.yaml")
    cap = float((profile.get("portfolio") or {}).get("max_participation", 0.0))

    fills = _fills()
    cache: dict[str, pd.DataFrame | None] = {}
    rows = []
    equities = []
    stale = 0
    for fill in fills:
        symbol = str(fill["symbol"])
        if symbol not in cache:
            cache[symbol] = _series(symbol)
        series = cache[symbol]
        bar = int(fill["_bar_ms"])
        if series is None or not len(series) or bar < int(series.index[0]):
            rows.append({"symbol": symbol, "notional": fill["_notional"], "adv": None})
            continue
        if bar not in series.index:
            stale += 1
        at = series.loc[series.index.asof(bar)]
        adv = float(at["adv"]) if pd.notna(at["adv"]) else 0.0
        hourly = float(at["hourly"]) if pd.notna(at["hourly"]) else 0.0
        sigma = float(at["sigma_daily"]) if pd.notna(at["sigma_daily"]) else 0.0
        notional = float(fill["_notional"])
        weight = abs(float(fill.get("target_weight") or 0.0))
        if weight > 1e-9:
            equities.append(abs(float(fill.get("target_notional") or 0.0)) / weight)
        rows.append(
            {
                "symbol": symbol,
                "notional": notional,
                "adv": adv,
                "hourly": hourly,
                "sigma_daily": sigma,
                "order_over_adv": notional / adv if adv > 0 else float("nan"),
                "participation_hourly": notional / hourly if hourly > 0 else float("nan"),
                "impact_bps": 1e4 * coefficient * sigma * math.sqrt(notional / adv) if adv > 0 and sigma > 0 else 0.0,
            }
        )
    table = pd.DataFrame(rows).dropna(subset=["adv"])
    equity = sum(equities) / len(equities) if equities else float("nan")
    total = table["notional"].sum()
    stamps = [dt.datetime.fromisoformat(str(f["at"])) for f in fills]
    days = (max(stamps) - min(stamps)).total_seconds() / 86_400
    cycle = sum(float(f["_notional"]) for f in fills if not f.get("flatten"))
    units = cycle / equity
    turns = units / days * 365
    weighted = float((table["impact_bps"] * table["notional"]).sum() / total)
    recoverable = weighted * (1 - 1 / math.sqrt(SLICES))

    print(f"fills={len(table)} of {len(fills)}  traded notional={total:,.0f} USDT  mean equity={equity:,.0f} USDT")
    print(f"priced at a stale bar (archive lags the loop): {stale}")
    print(f"coefficient={coefficient}  max_participation={cap:.3f}  slices priced={SLICES}")
    print()
    print("order / ADV (daily quote volume, the impact model's ruler)")
    for name, value in table["order_over_adv"].describe(percentiles=[0.5, 0.95]).items():
        print(f"  {name:>5}: {value:.3e}" if name != "count" else f"  {name:>5}: {value:.0f}")
    print(f"  max symbol: {table.loc[table['order_over_adv'].idxmax(), 'symbol']}")
    print()
    print(f"participation vs one hour of volume (the live cap's ruler, cap={cap:.1%})")
    for name, value in table["participation_hourly"].describe(percentiles=[0.5, 0.95]).items():
        print(f"  {name:>5}: {value:.3e}" if name != "count" else f"  {name:>5}: {value:.0f}")
    print(f"  fills at or above the {cap:.1%} cap: {(table['participation_hourly'] >= cap).sum()}")
    print()
    print("modelled impact per fill, bps")
    print(f"  notional-weighted: {weighted:.6f}")
    print(f"  median           : {table['impact_bps'].median():.6f}")
    print(f"  max              : {table['impact_bps'].max():.6f}  ({table.loc[table['impact_bps'].idxmax(), 'symbol']})")
    print(f"  recoverable by a perfect {SLICES}-way split: {recoverable:.6f} bps")
    print()
    # Impact is sqrt-concave in size and every weight is a fraction of equity, so scaling the account
    # by m scales every order by m and every impact reading by sqrt(m).  That makes this ledger's own
    # trade mix - not the backtest's - extrapolable to the capital where slicing starts to pay.
    print("extrapolated to account size (same trade mix, impact ~ sqrt(capital))")
    print(f"{'capital':>14} {'impact bps':>12} {'recoverable bps':>16} {'recovered /yr':>14}")
    # Turnover is derived from this ledger rather than quoted from `live.demo.yaml`, because the 472.9
    # there is `turnover_units` - the sum of |dw| over the WHOLE backtest sample, not per year.  Reading
    # it as annual overstates the saving about six-fold, which is exactly the size of error that makes a
    # no-benefit finding look like a benefit.  Flatten rows are excluded: a one-off unwind is not part of
    # the book's recurring turnover, and including it inflates the annualisation on a 6-day window.
    for capital in (equity, 1e4, 1e5, 1e6, 1e7, 1e8):
        scale = math.sqrt(capital / equity)
        bps = weighted * scale
        rec = recoverable * scale
        print(f"{capital:>14,.0f} {bps:>12.4f} {rec:>16.4f} {rec * 1e-4 * turns:>13.3%}")
    print()
    print(f"annualised saving = recoverable bps x realised turnover {turns:.1f} units/yr, cycle orders only")
    print(f"  (this ledger: {units:.2f} units over {days:.2f} days; the backtest's own sample runs ~83/yr)")


if __name__ == "__main__":
    main()
