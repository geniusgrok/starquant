"""P12 stage 1, part one: rebuild the point-in-time membership table with the Amihud screen applied.

The screen acts on CANDIDATES, before ranking, so an excluded name is replaced by the next one down -
which is what the live rule would do and what stage 0 explicitly could not measure.

Faithfulness check, run first and printed: with the screen disabled this loop must reproduce the committed
`membership.parquet` cell for cell.  If it does not, the screened tables are not comparable to the baseline
and the run stops.  The ranking itself comes from `starquant_data.universe.rank_with_hysteresis` rather than a
copy, so only the candidate filter is new code.

Writes one root per multiple: <out>/m<N>/membership.parquet, with klines symlinked to the real store, so
`starquant research validate --root <out>/m<N> --universe pit` runs unmodified against it.
"""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

import pandas as pd

from starquant_data.archive import ArchiveClient, Month
from starquant_data.binance_public import PublicClient
from starquant_data.pool import daily_quote_volume, membership_summary, point_in_time_membership
from starquant_data.store import KlineStore
from starquant_data.universe import UniverseConfig, rank_with_hysteresis
from starquant_shared.binance_rules import parse_exchange_info
from starquant_shared.config import load_yaml

sys.path.insert(0, str(Path(__file__).parent))
from p12_stage0 import daily_frames, illiquidity

REFRESH = "D"  # the committed table is daily (2,042 refreshes); see the pool comment in live.demo.yaml
PINS = ("BTCUSDT", "ETHUSDT")
MULTIPLES = (2.0, 4.0, 8.0)


def screened_membership(
    quote_volume: pd.DataFrame,
    config: UniverseConfig,
    eligible: set[str],
    illiq: pd.DataFrame | None,
    multiple: float | None,
) -> pd.DataFrame:
    """``point_in_time_membership`` with one extra step: drop candidates whose ILLIQ exceeds m x the median.

    With ``multiple=None`` this is the unscreened rule, and the faithfulness check asserts it matches the
    committed table.  The screen is applied to the candidate pool *before* ``rank_with_hysteresis``, so the
    slot freed by an excluded name goes to the next candidate rather than shrinking the universe.
    """
    days = pd.DatetimeIndex(quote_volume.index)
    first = days[0] + pd.Timedelta(days=config.min_age_days)
    dates = pd.date_range(first.normalize(), days[-1], freq=REFRESH, tz="UTC")
    if len(dates) == 0 or dates[0] > first:
        dates = pd.DatetimeIndex([first.normalize(), *dates]) if len(dates) else pd.DatetimeIndex([first.normalize()])
    universe = list(quote_volume.columns)
    rows: list[list[bool]] = []
    previous: list[str] = []
    observed = quote_volume.notna().cumsum()
    for date in dates:
        before = quote_volume.loc[: date - pd.Timedelta(nanoseconds=1)]
        if before.empty:
            rows.append([False] * len(universe))
            continue
        age = observed.loc[: date - pd.Timedelta(nanoseconds=1)].iloc[-1]
        window = before.iloc[-config.volume_lookback_days :]
        volumes = {s: float(window[s].fillna(0.0).sum()) for s in universe if age[s] >= config.min_age_days}
        if multiple is not None and illiq is not None:
            history = illiq.loc[: date - pd.Timedelta(nanoseconds=1)]
            if not history.empty:
                scores = history.iloc[-1].reindex(list(volumes)).dropna()
                if len(scores) >= 3:
                    limit = multiple * float(scores.median())
                    for symbol in scores[scores > limit].index:
                        volumes.pop(symbol, None)
        members = rank_with_hysteresis(
            volumes,
            eligible & set(volumes),
            previous,
            enter_rank=config.enter_rank,
            exit_rank=config.exit_rank,
            top_n=config.top_n,
            always_include=config.always_include,
        )
        previous = members
        chosen = set(members)
        rows.append([s in chosen for s in universe])
    return pd.DataFrame(rows, index=dates, columns=universe, dtype=bool)


def main() -> int:
    source = Path(sys.argv[1] if len(sys.argv) > 1 else "~/starquant/.starquant/data")
    out = Path(sys.argv[2] if len(sys.argv) > 2 else "/private/tmp/p12")
    base = UniverseConfig.from_mapping(load_yaml("config/universe.yaml"))
    config = replace(base, always_include=PINS)
    store = KlineStore(source)
    with PublicClient("https://fapi.binance.com") as public, ArchiveClient() as archive:
        rules = parse_exchange_info(public.exchange_info())
        listed = {s for s, rule in rules.items() if rule.quote_asset == config.quote_asset}
        archived = {s for s in archive.list_symbols() if s.endswith(config.quote_asset)}
    candidates = sorted(listed | archived)
    eligible = {
        s
        for s in candidates
        if s not in rules
        or (
            rules[s].contract_type == "PERPETUAL"
            and rules[s].quote_asset == config.quote_asset
            and (float(rules[s].min_notional) <= config.max_min_notional_usdt or s in PINS)
        )
    } - set(config.exclude)
    volume = daily_quote_volume(store, candidates)
    volume = volume.loc[pd.Timestamp(Month.parse(config.history_start).start_ms(), unit="ms", tz="UTC") :]
    print(f"candidates {len(candidates)}  eligible {len(eligible)}  volume frame {volume.shape}")

    committed = pd.read_parquet(source / "membership.parquet").astype(bool)
    committed.index = pd.DatetimeIndex(committed.index)
    reference = point_in_time_membership(volume, config, eligible=eligible, refresh=REFRESH)
    mine = screened_membership(volume, config, eligible, None, None)
    same_api = reference.equals(committed.reindex(index=reference.index, columns=reference.columns).fillna(False))
    same_loop = mine.equals(reference)
    print(f"faithfulness: package rule reproduces committed table = {same_api}; this loop matches it = {same_loop}")
    if not (same_api and same_loop):
        print("STOP: the unscreened rebuild does not match the committed table; screened tables would not compare")
        return 1

    close, quote = daily_frames(list(volume.columns))
    illiq, dropped, total = illiquidity(close, quote)
    print(f"illiq frame {illiq.shape}; gap rule dropped {dropped}/{total} observations ({dropped / total:.4%})")

    for multiple in MULTIPLES:
        table = screened_membership(volume, config, eligible, illiq, multiple)
        root = out / f"m{multiple:g}"
        (root / "klines").parent.mkdir(parents=True, exist_ok=True)
        if not (root / "klines").exists():
            (root / "klines").symlink_to(source / "klines")
        if not (root / "funding").exists() and (source / "funding").exists():
            (root / "funding").symlink_to(source / "funding")
        for name in ("universe.json",):
            if (source / name).exists():
                (root / name).write_bytes((source / name).read_bytes())
        table.to_parquet(root / "membership.parquet")
        summary = membership_summary(table)
        base_summary = membership_summary(reference)
        (root / "membership.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", "utf-8")
        turnover = summary["changes_per_refresh"]
        print(
            f"m={multiple:g}: mean size {summary['mean_size']:.2f} (base {base_summary['mean_size']:.2f}), "
            f"union {len(summary['union'])} (base {len(base_summary['union'])}), "
            f"changes/refresh {turnover:.3f} (base {base_summary['changes_per_refresh']:.3f}) -> {root}"
        )
    baseline_root = out / "base"
    (baseline_root / "klines").parent.mkdir(parents=True, exist_ok=True)
    if not (baseline_root / "klines").exists():
        (baseline_root / "klines").symlink_to(source / "klines")
    if not (baseline_root / "funding").exists() and (source / "funding").exists():
        (baseline_root / "funding").symlink_to(source / "funding")
    if (source / "universe.json").exists():
        (baseline_root / "universe.json").write_bytes((source / "universe.json").read_bytes())
    reference.to_parquet(baseline_root / "membership.parquet")
    print(f"baseline -> {baseline_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
