"""O4: how often does the point-in-time universe hold a slot with no market data behind it?

A 30-day trailing quote volume keeps ranking a symbol that has stopped quoting, so a name can occupy
one of `top_n` slots for up to a month after its last bar.  This builds the `available` frame
`membership_summary` needs - "did this symbol have a 1h bar on this refresh day?" - and prints what it
finds.  `pool.py` deliberately does not read the archive, so this is where the I/O lives.

    STARQUANT_DATA_ROOT=/path/to/.starquant/data PYTHONPATH=. python scratchpad/membership_dead_slots.py

Measured 2026-09-13 on the shipped archive: 2,042 refreshes, 35,899 member-refresh slots, 109 dead
(0.30%), on 104 refresh days (5.1%), worst 2 of 18 on 2026-07-18.  0.30% changes no conclusion - the
reason to compute it is that a measured 0.30% and an unmeasured unknown are different answers.

The split is the part a single share hides, and it is why this prints per symbol: 28 of the 109 are
LUNAUSDT's delisting tail (last 1h bar 2022-05-13, member until 2022-06-10), and the other 81 belong
to six 2026 names - SKYAI, SYN, BLESS, ALLO, RE, ENSO - whose 1h archive has never been backfilled.
`research --universe pit` already prints those six as "member symbols have no 1h klines yet", so they
are a sync gap wearing a universe defect's clothes; the fix for them is a download, not a rule change.
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

from starquant_data.pool import MEMBERSHIP_FILE, membership_summary
from starquant_data.store import KlineStore

ROOT = os.environ.get("STARQUANT_DATA_ROOT", ".starquant/data")


def available_frame(membership: pd.DataFrame, root: str, interval: str = "1h") -> pd.DataFrame:
    """Did each symbol print at least one bar on each refresh DAY?  Missing symbol -> all False."""
    store = KlineStore(root)  # the root IS `.starquant/data`; "klines" is the `kind` default, not a suffix
    days = pd.DatetimeIndex(membership.index).normalize()
    columns: dict[str, pd.Series] = {}
    for symbol in membership.columns:
        if not store.exists(symbol, interval):
            columns[symbol] = pd.Series(False, index=membership.index)
            continue
        frame = store.load(symbol, interval)
        stamps = pd.DatetimeIndex(pd.to_datetime(frame["open_time"].to_numpy(), unit="ms", utc=True)).normalize()
        columns[symbol] = pd.Series(days.isin(set(stamps)), index=membership.index)
    return pd.DataFrame(columns)


def main() -> None:
    table = pd.read_parquet(Path(ROOT) / MEMBERSHIP_FILE)
    index = pd.DatetimeIndex(table.index)
    table.index = index.tz_localize("UTC") if index.tz is None else index.tz_convert("UTC")
    membership = table.astype(bool)
    available = available_frame(membership, ROOT)

    summary = membership_summary(membership, available=available)
    print(f"refreshes {summary['refreshes']:,}  {summary['first']} .. {summary['last']}")
    print(f"mean size {summary['mean_size']:.2f}  union {len(summary['union'])} symbols")
    print(f"dead slots {summary['dead_slots']:,}  share {summary['dead_slot_share']:.4%}")
    print(f"worst refresh {summary['worst_refresh']}")

    members = membership.astype(bool)
    dead = members & ~available.reindex(index=membership.index, columns=membership.columns).fillna(False)
    per_refresh = dead.sum(axis=1)
    print(f"refresh days with at least one dead slot: {int((per_refresh > 0).sum()):,} "
          f"({(per_refresh > 0).mean():.1%})")
    per_symbol = dead.sum(axis=0)
    print(f"symbols ever holding a dead slot: {int((per_symbol > 0).sum())}")
    print(f"  worst: {per_symbol[per_symbol > 0].sort_values(ascending=False).head(8).to_dict()}")
    by_year = per_refresh.groupby(per_refresh.index.year).mean()
    print("dead slots per refresh, by year: " + "  ".join(f"{y} {v:.2f}" for y, v in by_year.items()))

    # The named case, checked rather than repeated: LUNAUSDT's last bar against its last membership.
    if "LUNAUSDT" in membership.columns:
        held = membership.index[membership["LUNAUSDT"]]
        alive = membership.index[available["LUNAUSDT"]]
        print(
            f"LUNAUSDT: member {held[0].date()}..{held[-1].date()}, last bar {alive[-1].date()}, "
            f"{int(dead['LUNAUSDT'].sum())} dead refreshes"
        )

    # The other half of the contract: no `available`, no keys - never a 0.0 that reads as a pass.
    bare = membership_summary(membership)
    print(f"without `available`: dead keys present = {[k for k in ('dead_slots', 'dead_slot_share') if k in bare]}")


if __name__ == "__main__":
    main()
