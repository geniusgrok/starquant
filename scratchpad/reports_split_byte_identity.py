"""2026-09-25 拆 `starquant_live/reports.py` 的两道验收：定义逐字相同，产物逐字节相同。

拆分本身由 `scratchpad/reports_split_by_area.py` 完成：每个顶层定义连同紧贴其上的注释块整段切走，
import 按各块实际用到的名字重算。这个脚本回答它有没有在搬运中改动任何东西。

**一、`text`：定义逐字相同。** 把父提交里 `reports.py` 的每个顶层定义（连同上方注释块）与它在新模块
里的文本逐字比。2026-09-25 的读数：81 个定义，逐字相同 81，不同 0，消失 0；新增只有 `__all__`。

**二、`render`：产物逐字节相同。** 照 `starquant_cli/live_cmd.py` 的 `report daily`、`report weekly`、
`report beta` 出报告，但不发 webhook。在同一个 cwd 下（config、registry、reports/research、git 历史
都相同），只换 PYTHONPATH 指向的代码，各跑一次再 `diff -r`。周报的 alpha 投入占比读 `git log`，
这里给固定值，量的是代码不是分支。`long_run_sharpe` 是唯一读墙钟的读数，按它当时所在的模块冻结。
2026-09-25 的读数：实盘状态快照（09-03 至 09-24T17:00Z）上 22 天日报（md、json、告警）、4 份周报、
2 份 beta 报告，另加 `live status` 与引擎用的三个读数，81 个产物逐字节相同。冻结时钟后，基线自己
跑两次也逐字节相同；不冻结时 `calendar_days` 与 `downtime_days` 两个字段会随墙钟变。

复现（父提交是 5fe1e6b3）：

    git worktree add --detach /tmp/base 5fe1e6b3
    cp -Rp .starquant/live /tmp/state          # 在两个周期之间复制
    cd /tmp/base
    PYTHONPATH=/tmp/base    python <本文件> render /tmp/state <data_root> /tmp/out/base
    PYTHONPATH=<拆分后的树>  python <本文件> render /tmp/state <data_root> /tmp/out/split
    diff -r -x _code.txt /tmp/out/base /tmp/out/split
    cd <拆分后的树> && python <本文件> text /tmp/base/starquant_live/reports.py
"""

from __future__ import annotations

import ast
import json
import sys
from dataclasses import asdict
from pathlib import Path


def segments(path: Path) -> dict[str, str]:
    """Each top-level definition's text, with the comment block directly above it."""
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines(keepends=True)
    out: dict[str, str] = {}
    previous = 0
    for node in ast.parse(source).body:
        name = getattr(node, "name", None)
        if name is None and isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
        if name is None and isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            name = node.target.id
        if name and not isinstance(node, (ast.Import, ast.ImportFrom)):
            start = min([node.lineno, *(d.lineno for d in getattr(node, "decorator_list", []))])
            above: list[str] = []
            for line in reversed(lines[previous : start - 1]):
                if not line.lstrip().startswith("#"):
                    break
                above.insert(0, line)
            out[name] = "".join(above) + "".join(lines[start - 1 : node.end_lineno])
        previous = node.end_lineno or node.lineno
    return out


def text(baseline: str) -> None:
    old = segments(Path(baseline))
    new: dict[str, tuple[str, str]] = {}
    for path in [Path("starquant_live/reports.py"), *sorted(Path("starquant_live").glob("report_*.py"))]:
        for name, body in segments(path).items():
            assert name not in new, f"{name} is defined twice"
            new[name] = (str(path), body)
    same = [n for n in old if n in new and new[n][1] == old[n]]
    changed = [f"{n} ({new[n][0]})" for n in old if n in new and new[n][1] != old[n]]
    gone = [n for n in old if n not in new]
    added = [n for n in new if n not in old]
    print(f"定义 {len(old)} 个：逐字相同 {len(same)}，不同 {len(changed)}，消失 {len(gone)}；新增 {added}")
    assert not changed and not gone, (changed, gone)


def dump(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True, default=str) + "\n"


def freeze_the_one_wall_clock_read() -> str:
    """Pin `datetime.now` in whichever module defines `long_run_sharpe`, before and after alike."""
    import datetime as _dt
    import importlib

    from starquant_live import reports

    fixed = _dt.datetime(2026, 9, 24, 18, 0, tzinfo=_dt.UTC)

    class Frozen(_dt.datetime):
        @classmethod
        def now(cls, tz: _dt.tzinfo | None = None) -> _dt.datetime:  # type: ignore[override]
            return fixed if tz is not None else fixed.replace(tzinfo=None)

    module = importlib.import_module(reports.long_run_sharpe.__module__)
    assert module.datetime is _dt.datetime, "expected a plain `from datetime import datetime`"
    module.datetime = Frozen
    return module.__name__


def render(state_dir: str, data_root: str, out_dir: str) -> None:
    from starquant_cli import live_cmd as L
    from starquant_live import reports
    from starquant_live.engine import collateral_share
    from starquant_live.state import StateStore

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    frozen_in = freeze_the_one_wall_clock_read()
    (out / "_code.txt").write_text(f"{reports.__file__}\n{L.__file__}\nclock frozen in {frozen_in}\n", encoding="utf-8")
    payload = L.load_profile("config/live.demo.yaml")
    store = StateStore(Path(state_dir))
    registry = L.load_registry(payload.get("registry", "config/alpha_registry.yaml"))
    expectations = L.expectations_from_evidence(L._evidence_reports(registry))
    dataset = asdict(L.registry_dataset_problems(registry, data_root, L._interval(payload)))
    days = sorted({str(row.get("at", ""))[:10] for row in store.read_jsonl(store.cycles_path) if row.get("at")})
    for day in days:
        data = L.daily_payload(
            store,
            day,
            expectations,
            L.probes_from_registry(registry),
            L.RiskBudgetParams.from_mapping(payload.get("risk_budget", {}) or {}),
            dataset=dataset,
            vol_target=L.portfolio_params(payload).vol_target,
            margin_cap=float((payload.get("portfolio", {}) or {}).get("margin_cap", 0.0)) or None,
            data_root=data_root,
            exits=L.ExitParams.from_mapping(payload.get("exits", {}) or {}),
            fidelity=L.ReplayInputs.from_profile(payload, registry, data_root),
        )
        (out / f"daily-{day}.md").write_text(L.daily_markdown(data), encoding="utf-8")
        (out / f"daily-{day}.json").write_text(dump(data), encoding="utf-8")
        alerts, notices = L.daily_alerts(data)
        (out / f"daily-{day}.alerts.json").write_text(dump({"alerts": alerts, "notices": notices}), encoding="utf-8")
    changed = {"starquant_alpha/x.py": 90, "starquant_live/y.py": 10}
    for day in days[-10::3]:
        data = L.weekly_payload(store, day, expectations=expectations, changed_lines=changed, dataset=dataset)
        validations = L._validations_since(Path("reports/research"), int(data["since_ms"]))
        skipped = L.preregistration_skipped(validations, effective_from=L.PREREGISTRATION_EFFECTIVE_FROM)
        data["preregistration"] = {
            "checked": len(validations) - skipped,
            "skipped_as_predating_the_check": skipped,
            "effective_from": L.PREREGISTRATION_EFFECTIVE_FROM,
            "problems": L.preregistration_problems(
                validations,
                first_mentioned=L._log_first_mentions({row["strategy"] for row in validations}),
                search_charged=L._search_charged(),
                effective_from=L.PREREGISTRATION_EFFECTIVE_FROM,
            ),
        }
        (out / f"weekly-{day}.md").write_text(L.weekly_markdown(data), encoding="utf-8")
        (out / f"weekly-{day}.json").write_text(dump(data), encoding="utf-8")
    for strategy in ("tsmom", "flow"):
        beta = L.beta_reading(
            store.read_jsonl(store.cycles_path),
            store.read_jsonl(store.attribution_path),
            L._store_closes(data_root, L._interval(payload)),
            strategy,
        )
        rendered = L.beta_markdown(beta) if "reason" not in beta else f"reason: {beta['reason']}\n"
        (out / f"beta-{strategy}.md").write_text(rendered, encoding="utf-8")
        (out / f"beta-{strategy}.json").write_text(dump(beta), encoding="utf-8")
    latest = L.latest_risk_adaptation(store)
    (out / "status-risk-adaptation.json").write_text(dump(latest), encoding="utf-8")
    (out / "status-headline.txt").write_text(str(L.risk_adaptation_headline(latest)) + "\n", encoding="utf-8")
    (out / "engine-collateral-share.json").write_text(
        dump(collateral_share(equity=1000.0, usdt_equity=640.0)), encoding="utf-8"
    )
    print(f"{len(days)} daily, {len(days[-10::3])} weekly, 2 beta -> {out}")


if __name__ == "__main__":
    if sys.argv[1] == "text":
        text(sys.argv[2])
    else:
        render(*sys.argv[2:5])
