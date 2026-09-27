"""k 的细化（2026-09-25）：在 0.20 与 0.15 之间补量 0.175，按 D-035 在诚实漂移下取守得住的最大 k。

起因。操作者 2026-09-25 裁定 k 取 0.45 并换抵押品，随后回报「抵押品无法置换」，0.45 的前提
（K-4：可动用 = 总权益）不成立。现有抵押品下，诚实漂移那张表（`k_remeasure_honest_drift_20260925.py`
的表 1）在 0.20 上 pit 压线（+0.07pp）、static 超线（−1.68pp）。另一个会话的 p32i 量过 0.15，两边都守得住，
但它不在仓库里。操作者选了「细化」：补量 0.175；0.175 两个 universe 都守得住就取 0.175，否则取 0.15。

零 ledger：只建面板、跑 bootstrap，不调任何 `research` 命令。

做法。与 `k_remeasure_honest_drift_20260925.py` 的表 1 同一条路径、同一套算术，只换 k：
* 面板走 `p32h.panel` -> `p32d.panel_series`，数据末端钉在 2026-09-22T16:00Z（`END`），带用 D2 + D3。
* 臂是 `ladder@k`，档位 `rescaled(k, budget=0.70 / F)`，F 是 09-25 的换算因子 1.7479。
* 诚实漂移：每条序列减同一个常数，使年化 Sharpe 等于 1.2306。
* block 起点照抄 p32h：`default_rng(20260904)`，2000 draws，block 168 根；n 相同则起点相同。
* 臂的计算直接调用 `k_remeasure_honest_drift_20260925.run_arm`，一行不改。
面板的键用三位小数（`k0.175`）：原脚本用两位，0.175 会被写成 `k0.17`。

对照。0.20 一并重跑，与已入库的 `reports/research/k-remeasure-honest-drift-20260925.json` 里
`main|<universe>|d3|k0.20|ladder@k|today|<drift>` 四行逐位比，面板摘要也比。那份是 09-25 早上在修缺口
（`starquant data repair`，同日 11:38Z）之前建的面板；逐位相同，说明修缺口没有碰到这几条序列。

复现：
    PYTHONPATH=. ~/starquant/.venv/bin/python scratchpad/k_bisect_0175_20260925.py --workers 12
输出 `<out>/k-bisect-0175-20260925.json`，是列表（第 0 项 meta），不进 `governance replay`。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import k_remeasure_honest_drift_20260925 as kr
import p32d_ladder_bootstrap_pathwise as p32d
import p32h_k_sweep_at_the_base_in_force as p32h

ROOT = Path(__file__).resolve().parents[1]
GRID = (0.20, 0.175, 0.15)
BUDGET = 0.70
REFERENCE = ROOT / "reports" / "research" / "k-remeasure-honest-drift-20260925.json"
CHECKED = ("median_total", "q95_total", "cagr_median", "starts_sha", "drift_c_per_bar", "sharpe_series_before")


def key(k: float) -> str:
    return f"k{k:.3f}"


def build_panels(job: tuple[str, str]) -> dict[str, Any]:
    """`kr.build_panels` 的同一套钉住，只换网格与键的写法。带固定为 D3（现行代码，不改 profile）。"""
    mode, out = job
    os.chdir(ROOT)
    calls = {"load": 0, "load_cached": 0}
    cache: dict[Any, Any] = {}
    original_load = p32d._load

    def load_to_end(root, symbols, interval, start, end, funding, *args, **kwargs):
        if start is not None or end is not None:
            raise RuntimeError(f"panel_series passed start/end ({start!r}, {end!r}); this pin assumes None/None")
        cache_key = (root, tuple(symbols), interval, funding, args, tuple(sorted(kwargs.items())))
        calls["load"] += 1
        if cache_key in cache:
            calls["load_cached"] += 1
            return cache[cache_key]
        cache[cache_key] = original_load(root, symbols, interval, start, kr.END, funding, *args, **kwargs)
        return cache[cache_key]

    p32d._load = load_to_end
    series: dict[str, np.ndarray] = {}
    digests: dict[str, str] = {}
    try:
        for k in GRID:
            before = calls["load"]
            mark, realised = p32h.panel(mode, k)
            if calls["load"] != before + 1:
                raise RuntimeError(f"the end pin did not take at {mode}/k={k}")
            series[f"{key(k)}_mark"], series[f"{key(k)}_realised"] = mark, realised
            digests[key(k)] = hashlib.sha256(mark.tobytes() + realised.tobytes()).hexdigest()[:16]
    finally:
        p32d._load = original_load
    path = Path(out) / f"panels-{mode}-d3.npz"
    np.savez(path, **series)
    return {"mode": mode, "file": str(path), "digests": digests, "calls": calls,
            "series_bars": len(series[f"{key(GRID[0])}_mark"])}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--out", default=str(ROOT / "scratchpad" / "k-bisect-0175-20260925"))
    args = parser.parse_args()
    os.chdir(ROOT)
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    sentinel = None
    if not os.environ.get("STARQUANT_TRIALS_LEDGER"):
        sentinel = out / "ledger-must-not-exist.jsonl"
        os.environ["STARQUANT_TRIALS_LEDGER"] = str(sentinel)
    ledger_before = kr._sha(kr.LEDGER)
    head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    print(f"HEAD {head}; trials.jsonl sha256 before {ledger_before}")
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=2) as pool:
        built = list(pool.map(build_panels, [(m, str(out)) for m in ("pit", "static")]))
    panels = {item["mode"]: item for item in built}
    for item in built:
        print(f"  panels {item['mode']}/d3: {item['series_bars']} bars, digests {item['digests']}, calls {item['calls']}")
    tasks = []
    for mode in ("pit", "static"):
        for drift in ("orig", "honest"):
            for k in GRID:
                label = f"main|{mode}|d3|{key(k)}|ladder@k|today|{drift}"
                tasks.append({"label": label, "set": "main", "mode": mode, "band": "d3", "k": k, "arm": "ladder@k",
                              "rungs": "today", "drift": drift, "file": panels[mode]["file"], "key": key(k),
                              "target_sharpe": kr.HONEST_SHARPE if drift == "honest" else None})
    rows: list[dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(kr.run_arm, task) for task in tasks]
        for future in as_completed(futures):
            row = future.result()
            rows.append(row)
            print(f"  [{time.time() - t0:5.0f}s] {row['label']}", flush=True)
    order = {t["label"]: i for i, t in enumerate(tasks)}
    rows.sort(key=lambda r: order[r["label"]])
    for mode in ("pit", "static"):
        shas = {r["starts_sha"] for r in rows if r["mode"] == mode}
        if len(shas) != 1:
            raise RuntimeError(f"{mode}: arms drew from {len(shas)} different sets of block starts: {shas}")

    reference = {r["label"]: r for r in json.loads(REFERENCE.read_text(encoding="utf-8")) if r.get("kind") != "meta"}
    ref_meta = next(r for r in json.loads(REFERENCE.read_text(encoding="utf-8")) if r.get("kind") == "meta")
    control = {}
    for row in rows:
        if abs(row["k"] - 0.20) > 1e-12:
            continue
        ref = reference[row["label"].replace("k0.200", "k0.20")]
        diffs = {f: (row[f], ref[f]) for f in CHECKED if row[f] != ref[f]}
        control[row["label"]] = diffs if diffs else "bit-identical"
    ref_digests = {p["mode"]: p["digests"]["k0.20"] for p in ref_meta["panels"] if p["band"] == "d3"}
    digest_check = {m: (panels[m]["digests"]["k0.200"], ref_digests[m]) for m in ("pit", "static")}

    def usdt(row: dict[str, Any]) -> float:
        return row["by_factor"]["today"]["q95_usdt"]

    honest = {(r["mode"], r["k"]): r for r in rows if r["drift"] == "honest"}
    holds = {k: all(usdt(honest[(m, k)]) >= -BUDGET for m in ("pit", "static")) for k in GRID}
    chosen = 0.175 if holds[0.175] else (0.15 if holds[0.15] else None)
    print("\ncontrol (k=0.20 against the committed rows):")
    for label, verdict in control.items():
        print(f"  {label}: {verdict}")
    print(f"panel digests k=0.20 now vs committed: {digest_check}")
    print("\nhonest drift, q95 on tradable USDT (factor today), headroom in pp:")
    for k in GRID:
        cells = "  ".join(
            f"{m} {usdt(honest[(m, k)]) * 100:+.2f}% ({(usdt(honest[(m, k)]) + BUDGET) * 100:+.2f}pp)"
            f" CAGR {honest[(m, k)]['cagr_median'] * 100:.1f}%"
            for m in ("pit", "static")
        )
        print(f"  k={k:.3f}: {cells}  holds both: {holds[k]}")
    print(f"\nD-035 on the operator's rule (0.175 if it holds in both, else 0.15): k = {chosen}")

    ledger_after = kr._sha(kr.LEDGER)
    if ledger_after != ledger_before:
        raise RuntimeError(f"trials.jsonl changed during the run: {ledger_before} -> {ledger_after}")
    if sentinel is not None and sentinel.exists():
        raise RuntimeError(f"something wrote a ledger row to {sentinel}")
    meta = {
        "kind": "meta",
        "script": "scratchpad/k_bisect_0175_20260925.py",
        "head": head,
        "grid": list(GRID),
        "end_exclusive": kr.END,
        "factor_today": kr.FACTOR_TODAY,
        "honest_sharpe": kr.HONEST_SHARPE,
        "draws": kr.DRAWS,
        "panels": [{k: v for k, v in item.items() if k != "file"} for item in built],
        "control_k020": control,
        "control_panel_digests": digest_check,
        "holds_both_honest": {f"{k:.3f}": v for k, v in holds.items()},
        "chosen_k": chosen,
        "trials_sha256_before": ledger_before,
        "trials_sha256_after": ledger_after,
        "seconds": round(time.time() - t0, 1),
    }
    path = out / "k-bisect-0175-20260925.json"
    path.write_text(json.dumps([meta, *rows], default=str) + "\n", encoding="utf-8")
    print(f"wrote {path} in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
