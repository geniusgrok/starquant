"""研究时间花在哪（2026-09-25，外部清单 #9.6）：feature store 该放在哪一层，先量再定。

零 ledger：不跑任何 `research` 命令，不写报告，只读 `--root` 下的数据。计时靠在本进程里给函数套计时器，
仓库文件一个字节不动。

三块读数，都在真实的时点面板上：

1. **layers**：一次 `research validate --strategy tsmom` 形状的运行，即 16 格（`DEFAULT_GRIDS`）加 registry 的
   flow sleeve，共 17 次 `model.evaluate` + `score_book`。`starquant_alpha.features` 里的每个函数在每个 import
   它的模块里替换成计时版本，只计顶层调用（`atr` 调 `true_range` 只算一次）。signal 层是
   `AlphaModel.strategy_scores`；其余几项是依赖权重的递推：`ewma_portfolio_vol`、`apply_exits`、
   `run_backtest`、`apply_no_trade_band`、`scores_to_targets`。
2. **units**：九个 signal 各自 `compute` 一次（默认参数，reference 取 min_history 与成员表），两个默认关闭的纯
   数据特征（`garch_forecast_vol`、HRP tilt），以及缓存自己的代价：一帧的 sha256、整张面板十个 bar 字段的
   sha256（串行与多线程）、npy 写加 fsync、读、读回再核 sha256。
3. **layout**：同一组权重按 C 序与 F 序各算一次 `ewma_portfolio_vol`，数不同的 bar。这是 store 要按 block 原样
   重建的理由。

复现
----
    PYTHONPATH=. .venv/bin/python scratchpad/feature_store_where_research_time_goes_20260925.py \\
        --root ~/starquant/.starquant/data --out <输出目录>
"""

from __future__ import annotations

import argparse
import functools
import hashlib
import inspect
import json
import os
import sys
import time
from collections import Counter, defaultdict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import starquant_alpha.backtest as backtest
import starquant_alpha.features as features
import starquant_alpha.model as model_module
import starquant_alpha.overlays.exits as exits_module
import starquant_alpha.portfolio as portfolio
import starquant_alpha.signals.base as signal_base
import starquant_alpha.validation.pipeline as pipeline
from starquant_alpha.registry import StrategyEntry
from starquant_alpha.signals import SIGNALS
from starquant_cli.research_book_eval import _book_guards, _exit_params
from starquant_cli.research_grids import DEFAULT_GRIDS, _grid
from starquant_cli.research_panel import _entry, _load, _membership, _model, _resolve_symbols
from starquant_live.composition import cost_model
from starquant_shared.config import load_yaml

SECONDS: dict[str, float] = defaultdict(float)
CALLS: Counter[str] = Counter()
DEPTH = [0]


def feature_timer(name: str, function: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(function)
    def timed(*args: Any, **kwargs: Any) -> Any:
        if DEPTH[0]:
            return function(*args, **kwargs)
        DEPTH[0] += 1
        start = time.perf_counter()
        try:
            return function(*args, **kwargs)
        finally:
            SECONDS[f"feature:{name}"] += time.perf_counter() - start
            CALLS[f"feature:{name}"] += 1
            DEPTH[0] -= 1

    return timed


def timer(label: str, function: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(function)
    def timed(*args: Any, **kwargs: Any) -> Any:
        start = time.perf_counter()
        try:
            return function(*args, **kwargs)
        finally:
            SECONDS[label] += time.perf_counter() - start
            CALLS[label] += 1

    return timed


def install() -> dict[str, Callable[..., Any]]:
    originals = {
        name: function
        for name, function in vars(features).items()
        if inspect.isfunction(function) and function.__module__ == features.__name__ and not name.startswith("_")
    }
    wrapped = {name: feature_timer(name, function) for name, function in originals.items()}
    for name, module in list(sys.modules.items()):
        if module is not None and name.startswith("starquant_alpha"):
            for attribute, function in originals.items():
                if getattr(module, attribute, None) is function:
                    setattr(module, attribute, wrapped[attribute])
    model_module.AlphaModel.strategy_scores = timer("layer:strategy_scores", model_module.AlphaModel.strategy_scores)
    vol = timer("weights:ewma_portfolio_vol", portfolio.ewma_portfolio_vol)
    model_module.ewma_portfolio_vol = vol
    portfolio.ewma_portfolio_vol = vol
    model_module.scores_to_targets = timer("weights:scores_to_targets", signal_base.scores_to_targets)
    portfolio.apply_no_trade_band = timer("weights:apply_no_trade_band", portfolio.apply_no_trade_band)
    pipeline.apply_exits = timer("weights:apply_exits", exits_module.apply_exits)
    pipeline.run_backtest = timer("weights:run_backtest", backtest.run_backtest)
    return originals


def layers(root: str, profile: dict[str, Any]) -> tuple[dict[str, Any], Any, Any]:
    t0 = time.perf_counter()
    panel = _load(root, _resolve_symbols(root, "", "1h", "pit"), "1h", None, None, True)
    t1 = time.perf_counter()
    membership = _membership(root, "pit", panel, 0)
    t2 = time.perf_counter()
    cost = cost_model(load_yaml("config/costs.yaml"), use_funding=True)
    guards, exits = _book_guards(profile, True), _exit_params(profile, True, "1h")
    tsmom = _entry("tsmom", "config/alpha_registry.yaml", "")
    entries = [StrategyEntry(id="tsmom", params=c) for c in _grid("tsmom", json.dumps(DEFAULT_GRIDS["tsmom"]), dict(tsmom.params))]
    entries.append(_entry("flow", "config/alpha_registry.yaml", ""))
    SECONDS.clear()
    CALLS.clear()
    t3 = time.perf_counter()
    for entry in entries:
        weights, _combined, _per = _model(entry, profile, "1h", None).evaluate(panel, membership)
        pipeline.score_book(panel, weights, cost, guards=guards, exits=exits)
    evaluations = time.perf_counter() - t3
    run = evaluations + (t2 - t0)
    feature_total = sum(value for key, value in SECONDS.items() if key.startswith("feature:"))
    out = {
        "panel": {"symbols": len(panel.symbols), "bars": len(panel.index), "last": str(panel.index[-1])},
        "evaluations": len(entries),
        "seconds": {"load_panel": t1 - t0, "membership": t2 - t1, "evaluations": evaluations, "run": run},
        "by_function": {key: {"seconds": SECONDS[key], "calls": CALLS[key]} for key in sorted(SECONDS)},
        "share_of_run": {
            "features": feature_total / run,
            "signal_layer": SECONDS["layer:strategy_scores"] / run,
            "load": (t2 - t0) / run,
            **{key: value / run for key, value in SECONDS.items() if key.startswith("weights:")},
        },
    }
    return out, panel, membership


def units(panel: Any, membership: Any, profile: dict[str, Any], scratch: Path) -> dict[str, Any]:
    model = _model(StrategyEntry(id="tsmom", params={}), profile, "1h", None)
    scored = panel.with_reference(model.eligible(panel, membership))
    signal_seconds: dict[str, Any] = {}
    for name, spec in SIGNALS.items():
        start = time.perf_counter()
        try:
            spec.compute(scored, dict(spec.default_params))
            signal_seconds[name] = time.perf_counter() - start
        except Exception as exc:  # a reading, not a gate
            signal_seconds[name] = f"{type(exc).__name__}: {exc}"
    params = model.portfolio
    start = time.perf_counter()
    features.garch_forecast_vol(panel.close)
    garch = time.perf_counter() - start
    sigma = portfolio.asset_vol(panel.close, params, panel.bars_per_year)
    start = time.perf_counter()
    portfolio._hrp_tilt(sigma, panel.close.pct_change(), params)
    hrp = time.perf_counter() - start
    frames = [
        frame
        for frame in (panel.open, panel.high, panel.low, panel.close, panel.volume, panel.quote_volume, panel.trades,
                      panel.taker_buy_base, panel.taker_buy_quote, panel.funding)
        if frame is not None
    ]

    def digest(frame: pd.DataFrame) -> bytes:
        h = hashlib.sha256()
        for block in frame._mgr.blocks:
            values = block.values
            h.update(memoryview(values if values.flags.c_contiguous else values.T).cast("B"))
        return h.digest()

    start = time.perf_counter()
    for frame in frames:
        digest(frame)
    serial = time.perf_counter() - start
    with ThreadPoolExecutor(max_workers=8) as pool:
        start = time.perf_counter()
        list(pool.map(digest, frames))
        threaded = time.perf_counter() - start
    values = np.ascontiguousarray(features.realized_vol(panel.close, 400).to_numpy())
    start = time.perf_counter()
    hashlib.sha256(values).hexdigest()
    one = time.perf_counter() - start
    path = scratch / "probe.npy"
    start = time.perf_counter()
    with path.open("wb") as handle:
        np.save(handle, values, allow_pickle=False)
        handle.flush()
        os.fsync(handle.fileno())
    write = time.perf_counter() - start
    start = time.perf_counter()
    np.load(path, allow_pickle=False)
    read = time.perf_counter() - start
    start = time.perf_counter()
    hashlib.sha256(path.read_bytes()).hexdigest()
    read_verify = time.perf_counter() - start
    size = path.stat().st_size
    path.unlink()
    return {
        "signal_compute_seconds": signal_seconds,
        "garch_forecast_vol_seconds": garch,
        "hrp_tilt_seconds": hrp,
        "frame_bytes": int(values.nbytes),
        "sha256_one_frame_seconds": one,
        "sha256_bar_fields_seconds": {"serial": serial, "threads_8": threaded, "bytes": sum(f.to_numpy().nbytes for f in frames)},
        "npy": {"write_fsync_seconds": write, "read_seconds": read, "read_and_sha256_seconds": read_verify, "bytes": size},
    }


def layout(panel: Any, membership: Any, profile: dict[str, Any], vol: Callable[..., Any]) -> dict[str, Any]:
    entry = _entry("tsmom", "config/alpha_registry.yaml", "")
    weights, _c, _p = _model(entry, profile, "1h", None).evaluate(panel, membership)
    values = weights.to_numpy()
    c_order = pd.DataFrame(np.ascontiguousarray(values), index=weights.index, columns=weights.columns, copy=False)
    f_order = pd.DataFrame(np.asfortranarray(values), index=weights.index, columns=weights.columns, copy=False)
    returns = panel.close.pct_change()
    a = vol(returns, c_order, 96, panel.bars_per_year).to_numpy()
    b = vol(returns, f_order, 96, panel.bars_per_year).to_numpy()
    differ = a.view(np.uint64) != b.view(np.uint64)
    return {
        "bars": len(a),
        "bars_differing": int(differ.sum()),
        "max_abs_difference": float(np.nanmax(np.abs(a - b))),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    profile = load_yaml("config/live.demo.yaml")
    original_vol = portfolio.ewma_portfolio_vol
    install()
    report, panel, membership = layers(args.root, profile)
    report["units"] = units(panel, membership, profile, out)
    report["layout"] = layout(panel, membership, profile, original_vol)
    (out / "feature-store-where-research-time-goes-20260925.json").write_text(
        json.dumps(report, indent=1, default=float), encoding="utf-8"
    )
    print(json.dumps({"share_of_run": report["share_of_run"], "layout": report["layout"]}, indent=1))


if __name__ == "__main__":
    main()
