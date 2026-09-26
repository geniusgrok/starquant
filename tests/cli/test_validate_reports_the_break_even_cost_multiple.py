"""validate 的报告带保本成本倍数 m*（G8，2026-09-23）。

端到端跑 `research validate`：真实的 2026-08 币安 1h K 线，经 `KlineStore` 落盘再读回，走生产那条面板
路径。钉住四件事：

1. **两条序列各是它该是的那条**。全样本取 `cost_stress` 定价的序列，即 best_key 自己的全长。样本外取
   `cost_stress_gate` 那条：重对齐到 common_index，再按 fold 切。两格 grid 让两者长度不同（669 对 619
   根），所以哪条取错了，下一件事都会抓到。
2. **m* 就是零点**。从面板独立重建 best_key 的 book，在报告的 m* 处重新定价。两条序列的净收益均值
   都在容差内为 0。样本外按报告自己的 `range` 与 fold 参数重切。
3. Markdown 在「Cost stress (Sharpe)」一节多一行，只多一行；verdict 的 reasons 里没有它。
4. **不是收敛的 m* 时，那一行看得出来**：没有零点印原因，没收敛印离零多远。这条是单测。没有零点的
   真实情形在 alpha 侧（August 的后三周不计成本也亏），但 validate 的 fold 在这份 fixture 上切不到那一段。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
from click.testing import CliRunner

from starquant_alpha.backtest import CostModel, run_backtest
from starquant_alpha.registry import StrategyEntry
from starquant_alpha.validation.pipeline import score_book
from starquant_alpha.validation.stability import BREAK_EVEN_TOLERANCE
from starquant_alpha.validation.walk_forward import walk_forward_folds
from starquant_cli import main
from starquant_cli.research_book_eval import _book_guards, _exit_params
from starquant_cli.research_panel import _load, _model
from starquant_cli.research_report import _break_even_row
from starquant_data.store import KlineStore
from starquant_shared.config import load_yaml

ROOT = Path(__file__).resolve().parents[2]
SYMBOLS = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT")
ROW = "| break-even multiple m* (never enforced) |"


def _store_from_fixtures(august_dir: Path, root: Path) -> None:
    store = KlineStore(root)
    for symbol in SYMBOLS:
        frame = pd.read_parquet(august_dir / symbol / "1h.parquet")
        frame["close_time"] = frame["open_time"] + 3_600_000 - 1
        store.append(symbol, "1h", frame)


def _validate(root: Path, out: Path, grid: str) -> tuple[dict[str, Any], str]:
    result = CliRunner().invoke(
        main,
        [
            "research", "validate",
            "--strategy", "tsmom",
            "--root", str(root),
            "--symbols", ",".join(SYMBOLS),
            "--out", str(out),
            "--no-funding",
            "--params", '{"horizons": [5, 20, 50], "crowding_window": 0}',
            "--grid", grid,
            "--folds", "3",
            "--min-train", "300",
            "--purge", "5",
            "--cpcv-groups", "4",
            "--min-history", "0",
        ],
    )  # fmt: skip
    assert result.exit_code == 0, result.output
    newest = max(out.glob("tsmom-validation-*.json"), key=lambda p: p.stat().st_mtime)
    return json.loads(newest.read_text(encoding="utf-8")), newest.with_suffix(".md").read_text(encoding="utf-8")


def _repriced(root: Path, report: dict[str, Any], multiple: float) -> pd.Series:
    """best_key 的 book 在成本 x multiple 下的净收益，从面板重建，不读报告里除参数以外的任何东西。"""
    panel = _load(str(root), list(SYMBOLS), "1h", None, None, False)
    profile = load_yaml(ROOT / "config" / "live.demo.yaml")
    model = _model(StrategyEntry(id="tsmom", params=report["best_params"]), profile, "1h", 0)
    weights, _c, _p = model.evaluate(panel, None)
    guards = _book_guards(profile, True)
    _r, decisions = score_book(panel, weights, CostModel(), guards=guards, exits=_exit_params(profile, True, "1h"))
    costs = report["costs"]
    scaled = CostModel(costs["turnover_bps"] * multiple, costs["carry_bps_per_bar"] * multiple, costs["use_funding"])
    return run_backtest(panel, decisions, scaled, guards=guards).portfolio_net


def _oos(report: dict[str, Any], net: pd.Series) -> pd.Series:
    common = net.loc[pd.Timestamp(report["range"]["start"]) : pd.Timestamp(report["range"]["end"])]
    assert len(common) == report["range"]["bars"]
    n = len(common)
    min_train = min(report["min_train"], max(n // 2, 2))
    folds = walk_forward_folds(n, report["folds"], min_train=min_train, purge=report["purge"])
    return pd.concat([common.iloc[fold.test_slice] for fold in folds])


def test_m_star_is_the_zero_of_both_series_it_names(tmp_path: Path, august_dir: Path) -> None:
    root = tmp_path / "data"
    _store_from_fixtures(august_dir, root)

    report, markdown = _validate(root, tmp_path / "out", '{"vol_window": [100, 200]}')

    block = report["cost_break_even"]
    full, oos = block["full_sample"], block["oos"]
    assert full["converged"] and oos["converged"], block
    at_full = _repriced(root, report, full["multiple"])
    assert len(at_full) > report["range"]["bars"], "两条序列等长，下面分不出全样本取的是哪一条"
    assert abs(float(at_full.mean())) <= BREAK_EVEN_TOLERANCE * full["cost_per_multiple"]
    at_oos = _oos(report, _repriced(root, report, oos["multiple"]))
    assert len(at_oos) == report["walk_forward"]["oos_bars"]
    assert abs(float(at_oos.mean())) <= BREAK_EVEN_TOLERANCE * oos["cost_per_multiple"]
    # the full-sample m* and cost_stress price one series, so the x2 gate reads the same fact
    assert (full["multiple"] >= 2.0) == (report["cost_stress"]["x2"] >= 0.0)
    assert set(block["basis"]) == {"multiple", "zero_of", "full_sample", "oos"}

    rows = [line for line in markdown.splitlines() if line.startswith(ROW)]
    assert len(rows) == 1, "m* 在 Markdown 里是一行"
    assert f"full_sample={full['multiple']:.2f}" in rows[0] and f"oos={oos['multiple']:.2f}" in rows[0]
    section = markdown.split("## Cost stress (Sharpe)", 1)[1].split("\n## ", 1)[0]
    assert rows[0] in section, "这一行要挨着成本压力那一节"
    assert not any("break-even" in reason or "m*" in reason for reason in report["reasons"])


def test_no_m_star_and_an_unsettled_one_do_not_print_like_a_settled_one() -> None:
    """两种不是「收敛的 m*」的读数，在那一行里都要看得出来：没有零点印原因，没收敛印离零多远。"""
    settled = {"multiple": 15.4606, "converged": True, "mean_net_at_multiple": 1e-19, "cost_per_multiple": 7.7e-6}
    unsettled = {**settled, "converged": False, "mean_net_at_multiple": 3.85e-10}
    none = {"multiple": None, "converged": False, "why": "mean net is below zero before any cost is scaled"}

    assert "full_sample=15.46  oos=15.46 (unsettled: +5.0e-05 off)" in _break_even_row(
        {"full_sample": settled, "oos": unsettled}
    )
    assert "oos=n/a (mean net is below zero before any cost is scaled)" in _break_even_row(
        {"full_sample": settled, "oos": none}
    )
