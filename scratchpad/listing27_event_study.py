"""#27 上新事件研究：2026-09-09 预登记的 6 格，在补齐 1h 数据之后跑一次（Q-SY3，2026-09-18）。

**这份脚本不挑任何规则。** 网格、主格、判据、falsifier 全部写在 `docs/RESEARCH_LOG.md`
「2026-09-09 · 块 3「上新」(#27)」的第四节，2026-09-09 就钉死了，比这里的任何一行代码早九天。
本脚本只做三件事：按那份预登记取样本、算那 6 格、把判据逐条对上。

预登记原文（摘）：

* 网格：入场偏移 `a ∈ {1, 24}` bar × 持有长度 `L ∈ {48, 144, 312}` bar，**方向固定为做空**。
  不扫入场阈值、不扫方向、不扫波动率缩放。
* 主格**提前声明**为 `a=24, L=48`——今天 |t| 最大的那一格，故意选在对自己最有利的一侧。
* 判据：无选择偏差样本上，主格按上市月聚类的 |t| >= 3、符号与做空先验一致、扣掉 14bps 往返后仍成立、
  且在 2021–2023 与 2024–2026 两个半样本上同号。
* falsifier：6 格最大 |t| < 3，或主格符号与先验相反 → **#27 关闭**，且不得以换窗口／换偏移重开。
* 预期：**阴性**（最大 |t| 落在 1.5 以下）。

**样本为什么现在才无偏。** 09-09 那次只能用 240 个有 1h 数据的标的里的 184 次上新，而其中 205 个是
曾经的池子成员——子样本大体是「后来当上 top-15 的那些上新」，前视选择偏在有利的一侧。Q-SY3 补齐了
623 个标的的 1h 归档，触发条件 (1) 因此满足。

**计费。** 预登记触发条件 (3)：「6 个格子每格各计一次先验试验」。桶是 `listing`——`ledger_scope`
对它返回 `("listing",)`，是一个全新的桶，不进任何在架策略的分母。要写 ledger 必须显式 `--charge 6`，
不写就只读不计费（而只读的那一次**不算数**：预登记要的是计了费的那一次）。

用法：

    python scratchpad/listing27_event_study.py --root .starquant/data            # 只读预览，不写 ledger
    python scratchpad/listing27_event_study.py --root .starquant/data --charge 6 # 正式跑，写 6 行
"""

from __future__ import annotations

import argparse
import math
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from starquant_alpha.validation.ledger import TrialRecord, resolve_ledger_path
from starquant_cli.research_ledger_io import _record_trials, _symbol_set_hash

LEDGER_STRATEGY = "listing"  # #27 自己的桶，`ledger_scope` 不把它给任何在架策略
ROOT = Path(".starquant/data")
ARCHIVE_START = pd.Timestamp("2021-01-01", tz="UTC")  # 归档起点：这一天上市的是左截断不是上新
OFFSETS = (1, 24)  # a
HOLDS = (48, 144, 312)  # L
MAIN = (24, 48)  # 主格，2026-09-09 提前声明
ROUND_TRIP = 0.0014  # 14 bps 往返，预登记写死


def _listing_dates() -> dict[str, pd.Timestamp]:
    """上市 = 日线首根 bar，剔除 2021-01-01 的左截断。与 09-09 数出 799 的口径相同。"""
    out: dict[str, pd.Timestamp] = {}
    for directory in sorted((ROOT / "klines").iterdir()):
        daily = directory / "1d.parquet"
        if not directory.is_dir() or not daily.exists():
            continue
        first = pd.read_parquet(daily, columns=["open_time"])["open_time"].min()
        stamp = pd.Timestamp(int(first), unit="ms", tz="UTC")
        if stamp <= ARCHIVE_START:
            continue
        out[directory.name] = stamp
    return out


def _events(listings: dict[str, pd.Timestamp]) -> pd.DataFrame:
    """每次上新一行：按 (a, L) 各给一个做空收益，扣费前。"""
    rows: list[dict[str, object]] = []
    for symbol, listed_at in listings.items():
        hourly = ROOT / "klines" / symbol / "1h.parquet"
        if not hourly.exists():
            continue
        frame = pd.read_parquet(hourly, columns=["open_time", "close"])
        index = pd.DatetimeIndex(pd.to_datetime(frame["open_time"], unit="ms", utc=True))
        close = pd.Series(frame["close"].to_numpy(dtype=float), index=index).sort_index()
        close = close[close.index >= listed_at]
        if close.empty:
            continue
        row: dict[str, object] = {"symbol": symbol, "listed_at": listed_at, "bars": int(close.size)}
        values = close.to_numpy(dtype=float)
        for a in OFFSETS:
            for hold in HOLDS:
                exit_index = a + hold
                if exit_index >= values.size or values[a] <= 0:
                    continue
                # 做空：价格跌 → 正收益
                row[f"a{a}_L{hold}"] = -(values[exit_index] / values[a] - 1.0)
        rows.append(row)
    return pd.DataFrame(rows)


def _clustered_t(values: np.ndarray, clusters: np.ndarray) -> tuple[float, float, float, int]:
    """按上市月聚类的 (mean, se, t, 簇数)。预登记写的是「按上市月聚类的 |t|」。

    簇内相关是这个样本的主要风险：同一个月上市的币共享同一段市场状态，把它们当独立观测会把
    |t| 抬高。这里用标准的 cluster-robust 三明治，并带上 G/(G-1) 的小样本修正。
    """
    n = values.size
    if n < 2:
        return float("nan"), float("nan"), float("nan"), 0
    mean = float(values.mean())
    grouped: dict[object, float] = defaultdict(float)
    for value, key in zip(values, clusters, strict=True):
        grouped[key] += value - mean
    g = len(grouped)
    if g < 2:
        return mean, float("nan"), float("nan"), g
    meat = sum(total**2 for total in grouped.values())
    # 小样本修正 G/(G-1) * (N-1)/(N-K)，这里 K=1（只估一个均值），第二项恒为 1，所以只留第一项。
    variance = (g / (g - 1)) * meat / (n**2)
    se = math.sqrt(variance) if variance > 0 else float("nan")
    return mean, se, (mean / se if se and math.isfinite(se) and se > 0 else float("nan")), g


def _charge(events: pd.DataFrame, charge: int) -> None:
    """预登记触发条件 (3)：6 个格子每格一笔，写进 `listing` 桶。

    手写 ledger 行不是绕过计费纪律，是执行它：这次事件研究不是一次 `validate`，没有 CLI 会替它
    记账，而预登记明写了要计 6 笔。走的是 CLI 用的同一个 `_record_trials`，所以去重规则、签名
    与落盘方式都一样。不显式 `--charge 6` 就不写——和 `research validate` 拒绝未申报的计费同形。
    """
    wanted = len(OFFSETS) * len(HOLDS)
    if charge != wanted:
        raise SystemExit(
            f"这次要计 {wanted} 笔到 `{LEDGER_STRATEGY}` 桶（预登记触发条件 (3)：6 个格子每格一次）。"
            f"请显式写 --charge {wanted}，或者不写 --charge 只做只读预览。"
        )
    now = datetime.now(UTC).isoformat(timespec="seconds")
    start = events["listed_at"].min().isoformat()
    end = events["listed_at"].max().isoformat()
    records = [
        TrialRecord(
            strategy=LEDGER_STRATEGY,
            param_key=f"a{a}_L{hold}|short|14bps",
            sharpe_annual=None,  # 事件研究给的是每事件均值与聚类 t，不是一条 sleeve 的 Sharpe
            bars_per_year=0.0,
            recorded_at=now,
            range_start=start,
            range_end=end,
            symbols=len(events),
            run_id=f"listing27-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}",
            symbol_set_hash=_symbol_set_hash(sorted(events["symbol"].tolist())),
        )
        for a in OFFSETS
        for hold in HOLDS
    ]
    path = resolve_ledger_path()
    written = _record_trials(path, records)
    print(f"\nledger：写了 {written} 行到 {path}（桶 {LEDGER_STRATEGY}，预登记触发条件 (3)）")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".starquant/data")
    parser.add_argument("--charge", type=int, default=None)
    args = parser.parse_args()
    global ROOT
    ROOT = Path(args.root)
    listings = _listing_dates()
    events = _events(listings)
    print(f"上市事件（日线首根 bar，剔除 {ARCHIVE_START.date()} 左截断）：{len(listings)}")
    print(f"其中有 1h 数据的：{len(events)}")
    if events.empty:
        print("没有可用事件。")
        return
    events["month"] = events["listed_at"].dt.strftime("%Y-%m")  # 聚类键；时间戳本来就是 UTC
    events["era"] = np.where(events["listed_at"].dt.year <= 2023, "2021-2023", "2024-2026")

    print()
    print("| 格 | a | L | n | 均值（扣费前） | 扣 14bps 后 | 聚类 SE | 聚类 t | 簇 | 21-23 符号 | 24-26 符号 |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    table: dict[tuple[int, int], dict[str, float]] = {}
    for a in OFFSETS:
        for hold in HOLDS:
            column = f"a{a}_L{hold}"
            if column not in events:
                continue
            block = events.dropna(subset=[column])
            net = block[column].to_numpy(dtype=float) - ROUND_TRIP
            mean, se, t, g = _clustered_t(net, block["month"].to_numpy())
            signs = {}
            for era, part in block.groupby("era"):
                signs[era] = float(part[column].mean()) - ROUND_TRIP
            table[(a, hold)] = {"n": len(block), "gross": float(block[column].mean()), "net": mean, "se": se, "t": t}
            star = " **主格**" if (a, hold) == MAIN else ""
            print(
                f"| a{a}_L{hold}{star} | {a} | {hold} | {len(block)} | {block[column].mean():+.4f} | {mean:+.4f} "
                f"| {se:.4f} | **{t:+.2f}** | {g} "
                f"| {signs.get('2021-2023', float('nan')):+.4f} | {signs.get('2024-2026', float('nan')):+.4f} |"
            )

    main_cell = table.get(MAIN)
    worst = max((abs(cell["t"]) for cell in table.values() if math.isfinite(cell["t"])), default=float("nan"))
    print()
    print(f"6 格最大 |t| = {worst:.2f}（预登记的 falsifier：< 3 即 #27 关闭）")
    if main_cell:
        print(f"主格 a=24 L=48：净均值 {main_cell['net']:+.4f}，聚类 t {main_cell['t']:+.2f}，n = {main_cell['n']}")
        print(f"主格符号与做空先验一致：{main_cell['net'] > 0}")
    print(f"判据①（主格 |t| >= 3）：{abs(main_cell['t']) >= 3 if main_cell else 'n/a'}")
    print(f"falsifier（6 格最大 |t| < 3）：{worst < 3 if math.isfinite(worst) else 'n/a'}")

    if args.charge is None:
        print("\n只读预览：没有写 ledger。预登记要的是**计了费的那一次**，正式跑要 --charge 6。")
    else:
        _charge(events, args.charge)


if __name__ == "__main__":
    main()
