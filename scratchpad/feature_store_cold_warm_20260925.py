"""feature store 冷热对比（2026-09-25，外部清单 #9.6）：真实时点面板上，store 关 / 开冷 / 开热各跑一轮。

零 ledger：不跑任何 `research` 命令，不写报告。只读 `--root` 下的数据；store 写进 `--store`，运行前清空。

三组工作量，都按研究侧的真实调用走（`model.evaluate` + `score_book`，与 `research validate` 每格做的相同）：

* **grid**：`research validate --strategy tsmom` 不传 `--grid` 时的 16 格（`DEFAULT_GRIDS`），加 registry 的 flow
  sleeve 一次，共 17 次评估。组合、护栏、exits 取 `config/live.demo.yaml`，成本取 `config/costs.yaml`。
* **expensive**：meanrev（registry 参数）与 chanlun（默认参数）各一次。signal 层最贵的两个。
* **sweep**：registry 的 tsmom，只改 `vol_target`（0.30 / 0.45 / 0.60 / 0.75）。signal 不变，store 在冷的那一轮
  里就开始命中。只跑 `evaluate`。

三轮的顺序是关、冷、热。冷与热两轮的每个输出都与关那一轮比：`weights`、`combined`、每个策略的目标、
`score_book` 的净收益，用 `tests/alpha/test_causality.py` 的 `_bit_for_bit`（逐列 uint64 视图）。任何一个
不同，脚本以非零退出。

`--keep-store` 让第二个进程沿用第一个进程写下的 store，于是它的「冷」那一轮读的是另一个进程写的条目。
两个进程之间数据若被同步改过，键就对不上，那一轮会是全不命中而不是读错。

热那一轮读的是刚写进页缓存的文件。冷盘读要多花时间：85 MB 按 3 GB/s 顺序读约 30 ms 一个条目，
这里没有清页缓存（`purge` 要 sudo）。

复现
----
    PYTHONPATH=. .venv/bin/python scratchpad/feature_store_cold_warm_20260925.py \\
        --root ~/starquant/.starquant/data --store <空目录> --out <输出目录>
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import shutil
import time
from pathlib import Path
from typing import Any

from starquant_alpha.model import AlphaModel
from starquant_alpha.registry import StrategyEntry
from starquant_alpha.validation.pipeline import score_book
from starquant_cli.research_book_eval import _book_guards, _exit_params
from starquant_cli.research_feature_store import ENV, FeatureStore, StoredScoresModel
from starquant_cli.research_grids import DEFAULT_GRIDS, _grid
from starquant_cli.research_panel import _entry, _load, _membership, _model, _resolve_symbols
from starquant_live.composition import cost_model
from starquant_shared.config import load_yaml
from tests.alpha.test_causality import _bit_for_bit


@dataclasses.dataclass
class TimedStore(FeatureStore):
    """同一个 store，额外记下花在键、读、写上的时间。"""

    seconds: dict[str, float] = dataclasses.field(default_factory=lambda: {"key": 0.0, "read": 0.0, "write": 0.0})

    def key(self, signal_id: str, params: Any, panel: Any) -> str:
        start = time.perf_counter()
        try:
            return super().key(signal_id, params, panel)
        finally:
            self.seconds["key"] += time.perf_counter() - start

    def read(self, key: str) -> Any:
        start = time.perf_counter()
        try:
            return super().read(key)
        finally:
            self.seconds["read"] += time.perf_counter() - start

    def write(self, key: str, frame: Any) -> None:
        start = time.perf_counter()
        try:
            super().write(key, frame)
        finally:
            self.seconds["write"] += time.perf_counter() - start


def stored(model: AlphaModel, store: FeatureStore) -> StoredScoresModel:
    return StoredScoresModel(**{f.name: getattr(model, f.name) for f in dataclasses.fields(AlphaModel)}, store=store)


def same(left: Any, right: Any) -> bool:
    try:
        _bit_for_bit(left, right)
    except AssertionError:
        return False
    return True


def disk(path: Path) -> dict[str, int]:
    files = [item for item in path.iterdir() if item.is_file()]
    return {"files": len(files), "bytes": sum(item.stat().st_size for item in files)}


def run_phase(
    label: str, jobs: list[tuple[str, AlphaModel, bool]], store: TimedStore | None, ctx: dict[str, Any]
) -> dict[str, Any]:
    rows, mismatches = [], 0
    started = time.perf_counter()
    for name, model, priced in jobs:
        chosen = model if store is None else stored(model, store)
        a = time.perf_counter()
        weights, combined, per = chosen.evaluate(ctx["panel"], ctx["membership"])
        b = time.perf_counter()
        net = None
        if priced:
            net = score_book(ctx["panel"], weights, ctx["cost"], guards=ctx["guards"], exits=ctx["exits"])[0].portfolio_net
        c = time.perf_counter()
        row: dict[str, Any] = {"job": name, "evaluate_s": round(b - a, 4), "score_book_s": round(c - b, 4)}
        if store is None:
            ctx["baseline"][name] = (weights, combined, per, net)
        else:
            base = ctx["baseline"][name]
            checks = {"weights": same(base[0], weights), "combined": same(base[1], combined)}
            checks.update({f"target:{key}": same(base[2][key], per[key]) for key in base[2]})
            if priced:
                checks["net"] = same(base[3], net)
            row["bit_identical"] = checks
            mismatches += sum(not ok for ok in checks.values())
        rows.append(row)
    out: dict[str, Any] = {
        "phase": label,
        "total_s": round(time.perf_counter() - started, 3),
        "evaluate_s": round(sum(row["evaluate_s"] for row in rows), 3),
        "score_book_s": round(sum(row["score_book_s"] for row in rows), 3),
        "mismatches": mismatches,
        "rows": rows,
    }
    if store is not None:
        out["store"] = dataclasses.asdict(store.stats)
        out["store_seconds"] = {key: round(value, 3) for key, value in store.seconds.items()}
        out["disk_after"] = disk(store.root)
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--store", required=True)
    parser.add_argument("--out", required=True)
    # 第二个进程沿用第一个进程写下的 store：它的「冷」那一轮就是跨进程命中，照样与本进程的「关」逐位比。
    parser.add_argument("--keep-store", action="store_true")
    args = parser.parse_args()
    os.environ.pop(ENV, None)  # 这里的 store 由脚本显式构造，`_model` 不能再套一层
    store_dir, out_dir = Path(args.store), Path(args.out)
    if not args.keep_store:
        shutil.rmtree(store_dir, ignore_errors=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    profile = load_yaml("config/live.demo.yaml")
    t0 = time.perf_counter()
    panel = _load(args.root, _resolve_symbols(args.root, "", "1h", "pit"), "1h", None, None, True)
    membership = _membership(args.root, "pit", panel, 0)
    load_s = time.perf_counter() - t0
    ctx: dict[str, Any] = {
        "panel": panel,
        "membership": membership,
        "cost": cost_model(load_yaml("config/costs.yaml"), use_funding=True),
        "guards": _book_guards(profile, True),
        "exits": _exit_params(profile, True, "1h"),
        "baseline": {},
    }
    registry = "config/alpha_registry.yaml"
    tsmom = _entry("tsmom", registry, "")
    grid = [
        (f"tsmom#{n}", _model(StrategyEntry(id="tsmom", params=combo), profile, "1h", None), True)
        for n, combo in enumerate(_grid("tsmom", json.dumps(DEFAULT_GRIDS["tsmom"]), dict(tsmom.params)))
    ]
    grid.append(("flow", _model(_entry("flow", registry, ""), profile, "1h", None), True))
    expensive = [(name, _model(_entry(name, registry, ""), profile, "1h", None), True) for name in ("meanrev", "chanlun")]
    base = _model(tsmom, profile, "1h", None)
    sweep = [
        (f"k={k}", dataclasses.replace(base, portfolio=dataclasses.replace(base.portfolio, vol_target=k)), False)
        for k in (0.30, 0.45, 0.60, 0.75)
    ]
    report: dict[str, Any] = {
        "panel": {
            "symbols": len(panel.symbols),
            "bars": len(panel.index),
            "first": str(panel.index[0]),
            "last": str(panel.index[-1]),
        },
        "load_s": round(load_s, 3),
        "store_preexisting": bool(args.keep_store),
        "workloads": {},
    }
    status = 0
    for workload, jobs in (("grid", grid), ("expensive", expensive), ("sweep", sweep)):
        ctx["baseline"] = {}
        directory = store_dir / workload
        phases = [run_phase("off", jobs, None, ctx)]
        for label in ("cold", "warm"):
            store = TimedStore(directory)
            phases.append(run_phase(label, jobs, store, ctx))
            report["code_digest"] = (store.code_hex or "")[:12]
        report["workloads"][workload] = phases
        status |= any(phase["mismatches"] for phase in phases)
        summary = " | ".join(f"{p['phase']} {p['total_s']:.1f}s (evaluate {p['evaluate_s']:.1f}s)" for p in phases)
        print(f"{workload}: {summary}; mismatches {[p['mismatches'] for p in phases]}", flush=True)
    (out_dir / "feature-store-cold-warm-20260925.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
