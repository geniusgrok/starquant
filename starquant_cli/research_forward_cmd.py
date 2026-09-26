"""``starquant research forward``：候选前向板（操作者 2026-09-17 裁定 Q-C = 建）。

**为什么是两条命令而不是一条带模式的。** `add` 花钱，`status` 不花钱。把它们做成同一条命令的两个
开关，迟早有人读一次板就花掉一笔——而板的门读的就是板上有几笔，所以误计一笔会让**所有**在板候选
的判定年限一起变长。分成两条，是让「花钱」这件事没有办法顺手发生。

**读板为什么免费。** 一个候选上板时就把假设钉死了：参数、universe、构造、声称的 Sharpe、起始 bar，
全部写进 `forward_board.jsonl` 并计一笔。此后每天重算的是**同一个**假设在多出来的数据上的读数，
不是一次新的选择。这正是前向检验与「再搜一次」的分别，也是板唯一便宜的地方。

**它不产生裁定。** 每份读数都带 `verdict` 与 `years_to_decide`，而按方案的定价，板上 30 个候选要
约 3.8 年才谈得上判。所以 `status` 的正常输出是一整版 `OBSERVING`，`decidable: 0`——那是诚实的读数，
不是功能没做完。

规则住在 `starquant_alpha/validation/forward_board.py`，这里只负责取数、计费、落盘。
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import click

from starquant_alpha.validation.forward_board import (
    FORWARD_BOARD_STRATEGY,
    PASSES,
    BoardEntry,
    Retirement,
    already_on_board,
    board_param_key,
    board_report,
    census,
    claimed_sharpe_from,
    forward_reading,
    full_sample_tail,
    live_entries,
    read_board,
    read_retirements,
)
from starquant_alpha.validation.ledger import TrialRecord, resolve_ledger_path
from starquant_alpha.validation.pipeline import score_book
from starquant_cli import research
from starquant_cli.research_book_eval import _book_guards, _exit_params
from starquant_cli.research_ledger_io import (
    _construction_digest,
    _record_trial,
    _symbol_set_hash,
)
from starquant_cli.research_options import _common_options
from starquant_cli.research_panel import _entry, _load, _membership, _model, _resolve_symbols
from starquant_cli.research_report import _stamp, _write
from starquant_live.composition import cost_model
from starquant_shared.config import load_yaml

#: 板文件。与 ledger 同一个目录，因为它们是同一件事的两半：板是名册，ledger 是账单。
DEFAULT_BOARD = "reports/research/forward_board.jsonl"

#: 板读数写哪。**不进 `reports/research/`**：那里放的是计过费的证据，而板读数是可从板与数据
#: 完全复现的派生物，日任务每天写一份。混在一起，一年 365 个未跟踪文件会把 `git status` 淹掉，
#: 掩盖真正的新证据——而「一层噪声掩盖另一层的信号」正是这个仓库付过学费的那类错误。
DEFAULT_BOARD_REPORTS = "reports/forward-board"


@research.group("forward")
def research_forward() -> None:
    """候选前向板：上板即计费，读板免费，判定要年。"""


def _board_path(board: str) -> Path:
    return Path(board)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@research_forward.command("add")
@_common_options
@click.option(
    "--evidence",
    required=True,
    help=(
        "让这个候选够格上板的那份报告（JSON）。声称的 Sharpe 从它里面读，不接受手输——"
        "手输的那个数正是会被往低里写的：写低一点，判定年限就短一点，板位就能早点「到期」。"
        "样本外优先于全样本（`oos.annualized_sharpe` > `summary.annualized_sharpe`）。"
    ),
)
@click.option(
    "--charge",
    type=int,
    default=None,
    help=(
        "本次上板要花多少笔，必须与实际相符。上板即计费到 `forward_board` 桶，而板的门读的就是"
        "这个桶——每上一个板位，**所有**在板候选的判定年限一起变长。不写这个数就拒跑。"
    ),
)
@click.option(
    "--accept-full-sample-tail",
    is_flag=True,
    default=False,
    help=(
        "证据的样本外是全样本尾巴（D-043 的 `oos_is_full_sample_tail`）时仍然上板。"
        "默认拒绝：判定年限是 (z / claimed_sharpe)²，声称越高年限越短，所以一条乐观读数只会让板"
        "判得**太早**。用这个开关就是承认这一点，而承认会被写进板条目、跟着这个板位走完一生。"
    ),
)
@click.option("--board", default=DEFAULT_BOARD, show_default=True, help="板文件（append-only）")
@click.option("--note", default="", help="给下一个读板的人的一句话")
def forward_add(
    evidence: str,
    charge: int | None,
    accept_full_sample_tail: bool,
    board: str,
    note: str,
    strategy: str,
    params: str,
    root: str,
    symbols: str,
    interval: str,
    start: str | None,
    end: str | None,
    profile: str,
    registry_path: str,
    costs_path: str,
    execution: str,
    funding: bool,
    out: str,
    min_history: int | None,
    universe_mode: str,
    min_tenure: int,
    grids: str,
) -> None:
    """把一个候选放上前向板：钉死假设，计一笔，此后只观察。"""
    board_file = _board_path(board)
    board_lines = board_file.read_text(encoding="utf-8").splitlines() if board_file.exists() else []
    existing = read_board(board_lines)
    # 退役过的板位可以重上——那正是「更正一个钉错的 claimed_sharpe」的路。重上要**再计一笔**：
    # 旧的那次观察不退钱，新的这次也是一次观察，两次都留在门的 N 里。
    still_live = live_entries(board_lines)

    evidence_path = Path(evidence)
    if not evidence_path.exists():
        raise click.ClickException(f"证据报告不存在：{evidence_path}")
    report = json.loads(evidence_path.read_text(encoding="utf-8"))
    claimed, where = claimed_sharpe_from(report)
    if claimed is None:
        raise click.ClickException(
            f"{evidence_path} 里读不到年化 Sharpe。板不拿 0.0 当默认——那会让判定年限读起来像"
            "「这个候选没希望」，而真相是「没读到那个数」。"
        )

    is_tail = full_sample_tail(report)
    if is_tail and not accept_full_sample_tail:
        raise click.ClickException(
            f"{evidence_path} 的样本外是**全样本尾巴**（`walk_forward.oos_is_full_sample_tail` 为真，"
            f"D-043 因此给它封顶 WEAK_PASS），而 {where} = {claimed:.4f} 就是那条尾巴。\n"
            "板的判定年限是 (z / claimed_sharpe)²——声称越高年限越短，所以拿乐观读数当基准只会让板"
            "判得**太早**：到点时估计量的噪声还大，一段走运的行情更容易把它推过门。\n"
            "要么换一份样本外真的是样本外的报告，要么显式写 `--accept-full-sample-tail` 承认这一点"
            "（承认会写进板条目，跟着这个板位走完一生）。"
        )

    entry_spec = _entry(strategy, registry_path, params, grids)
    profile_payload = load_yaml(profile)
    portfolio = _model(entry_spec, profile_payload, interval, min_history).portfolio.__dict__
    cost = cost_model(load_yaml(costs_path), use_funding=funding)
    digest = _construction_digest(portfolio, cost, execution)

    candidate = BoardEntry(
        candidate=strategy,
        param_key=board_param_key(strategy, dict(entry_spec.params)),
        params=dict(entry_spec.params),
        universe=universe_mode,
        construction_digest=digest,
        entered_at=datetime.now(UTC).isoformat(timespec="seconds"),
        run_id=f"board-{_stamp()}",
        claimed_sharpe=claimed,
        evidence=str(evidence_path),
        evidence_sha256=_sha256(evidence_path),
        claimed_is_full_sample_tail=is_tail,
        evidence_verdict=str(report.get("verdict", "")),
        note=note,
    )

    if already_on_board(still_live, candidate):
        click.echo(f"已在板上（{candidate.param_key}），不重复计费。板上现有 {census(existing)} 个板位。")
        return
    superseding = already_on_board(existing, candidate)

    wanted = 1
    if charge != wanted:
        n_after = census([*existing, candidate])
        raise click.ClickException(
            f"这次上板要计 {wanted} 笔到 `{FORWARD_BOARD_STRATEGY}` 桶，请显式写 `--charge {wanted}`。\n"
            f"板上现有 {census(existing)} 个板位，加上这个是 {n_after} 个——"
            f"而板的门按 N 算，所以这一笔让**已经在板上的每一个候选**都要多等一段。\n"
            f"证据：{evidence_path}（{where} = {claimed:.4f}）"
        )

    ledger_path = resolve_ledger_path(out=out)
    chosen = _resolve_symbols(root, symbols, interval, universe_mode)
    trial = TrialRecord(
        strategy=FORWARD_BOARD_STRATEGY,
        param_key=f"{strategy}|{candidate.param_key}|{universe_mode}",
        sharpe_annual=None,  # 上板时没有前向读数，写 None 而不是把声称值抄进账单
        bars_per_year=0.0,
        recorded_at=candidate.entered_at,
        range_start=candidate.entered_at,
        range_end=candidate.entered_at,
        symbols=len(chosen),
        run_id=candidate.run_id,
        construction_digest=digest,
        symbol_set_hash=_symbol_set_hash(chosen),
    )
    charged = _record_trial(ledger_path, trial)

    board_file.parent.mkdir(parents=True, exist_ok=True)
    with board_file.open("a", encoding="utf-8") as handle:
        handle.write(candidate.to_json() + "\n")

    verb = "重上（更正一个退役的板位）" if superseding else "上板"
    click.echo(f"{verb}：{strategy} {candidate.param_key} universe={universe_mode}")
    tail_note = "，**而它是一条全样本尾巴，年限建在乐观读数上**" if is_tail else ""
    click.echo(f"  声称 Sharpe {claimed:.4f}（读自 {evidence_path} 的 {where}{tail_note}）")
    click.echo(
        f"  计费 {'1 笔' if charged else '0 笔（同一笔已在账上）'} → {ledger_path}（桶 {FORWARD_BOARD_STRATEGY}）"
    )
    # 门的 N 按**不同的假设**数，所以重上同一个板位不会让它变大——重新钉一次声称值不是一个新候选。
    # 但它是一次被行使的自由度，所以照样计一笔：ledger 里那行是「谁在什么时候改了这个板位的声称值」
    # 的审计痕迹，而 N 管的是多重检验。两者本来就不该相等。
    click.echo(f"  在板 {len(still_live) + 1} 个；门按曾经上过板的 {census([*existing, candidate])} 个不同板位算")


# `status` **不用** `_common_options`，因为那里面 `--strategy` 是必填的，而读板根本不需要它：
# 每个板位的策略、参数与 universe 都在板条目里，那正是上板时钉死的东西。照抄 `_common_options`
# 的代价是具体的——`deploy/run_forward_board.sh` 就是不带 `--strategy` 调它的，于是日任务每天失败，
# 而失败的方式是 click 的用法错误，看起来像脚本写错而不是命令定义错。
@research_forward.command("retire")
@click.option("--candidate", required=True, help="板位的策略 id")
@click.option("--param-key", required=True, help="板位的参数摘要（`forward status` 会打出来）")
@click.option("--universe", required=True, help="板位的 universe")
@click.option("--reason", required=True, help="为什么撤——这句话会跟着退役记录留在板上")
@click.option("--board", default=DEFAULT_BOARD, show_default=True, help="板文件（append-only）")
def forward_retire(candidate: str, param_key: str, universe: str, reason: str, board: str) -> None:
    """把一个板位从**报告**里撤下来。**不退钱，也不降低门的 N。**

    「看过就是看过」：那一笔买的是一次观察的权利，撤回观察不能退多重检验的代价。所以退役之后
    `forward status` 不再读这个板位，而门的 N 仍按**曾经**上过板的数目算。

    唯一正当的用途是**更正**——一个板位的 `claimed_sharpe` 钉错了，换一个重上，而旧的那次观察照样
    计在 N 里。想靠退掉表现差的板位来降低其他候选的门，这条路是堵死的。
    """
    board_file = _board_path(board)
    if not board_file.exists():
        raise click.ClickException(f"板文件不存在：{board_file}")
    lines = board_file.read_text(encoding="utf-8").splitlines()
    entries = read_board(lines)
    already = read_retirements(lines)

    matches = [e for e in entries if (e.candidate, e.param_key, e.universe) == (candidate, param_key, universe)]
    if not matches:
        raise click.ClickException(
            f"板上没有 {candidate} / {param_key} / {universe}。现有板位："
            + ", ".join(f"{e.candidate}/{e.param_key}/{e.universe}" for e in entries)
        )
    target = matches[-1]
    if target.identity() in {r.identity() for r in already}:
        click.echo(f"已经退役过了（{target.param_key}），不重复记。")
        return

    record = Retirement(
        candidate=target.candidate,
        param_key=target.param_key,
        universe=target.universe,
        construction_digest=target.construction_digest,
        retired_at=datetime.now(UTC).isoformat(timespec="seconds"),
        reason=reason,
    )
    with board_file.open("a", encoding="utf-8") as handle:
        handle.write(record.to_json() + "\n")
    click.echo(f"退役：{target.candidate} {target.param_key} {target.universe}")
    click.echo(f"  理由：{reason}")
    click.echo(f"  门的 N 不变，仍按曾经上过板的 {census(entries)} 个算——看过就是看过。")


@research_forward.command("status")
@click.option("--root", default=".starquant/data", show_default=True)
@click.option("--symbols", default="", help="comma-separated; default = selected universe or all stored")
@click.option("--interval", default="1h", show_default=True)
@click.option("--from", "start", default=None, help="YYYY-MM-DD inclusive")
@click.option("--to", "end", default=None, help="YYYY-MM-DD exclusive")
@click.option("--profile", default="config/live.demo.yaml", show_default=True)
@click.option("--registry", "registry_path", default="config/alpha_registry.yaml", show_default=True)
@click.option("--costs", "costs_path", default="config/costs.yaml", show_default=True)
@click.option("--execution", type=click.Choice(["open_to_close", "close_to_close"]), default="open_to_close")
@click.option("--funding/--no-funding", default=True, show_default=True)
@click.option("--out", default=DEFAULT_BOARD_REPORTS, show_default=True, help="板读数写哪（不是 reports/research）")
@click.option("--min-history", default=None, type=int, help="bars a symbol must have before it is tradable")
@click.option("--min-tenure", default=0, show_default=True, help="pit only: refreshes before a symbol is tradable")
@click.option("--grids", default="", help="JSON of enumerate_candidates grids, for mined ids on the board")
@click.option("--board", default=DEFAULT_BOARD, show_default=True, help="板文件")
@click.option("--guards/--no-guards", default=True, show_default=True, help="按实盘的 book guards 定价")
@click.option("--exits/--no-exits", "exits", default=True, show_default=True, help="按实盘的退出层定价")
def forward_status(
    board: str,
    guards: bool,
    exits: bool,
    root: str,
    symbols: str,
    interval: str,
    start: str | None,
    end: str | None,
    profile: str,
    registry_path: str,
    costs_path: str,
    execution: str,
    funding: bool,
    out: str,
    min_history: int | None,
    min_tenure: int,
    grids: str,
) -> None:
    """重算板上每个候选的前向读数。**不计费**：钉死的假设在多出来的数据上重读，不是一次新的选择。"""
    board_file = _board_path(board)
    if not board_file.exists():
        click.echo(f"板是空的（{board_file} 不存在）。`research forward add` 放第一个候选上去。")
        return
    lines = board_file.read_text(encoding="utf-8").splitlines()
    entries = read_board(lines)
    retired = read_retirements(lines)
    if not entries:
        click.echo("板上没有可读的条目。")
        return

    # 门的 N 数的是**曾经**上过板的全部，退役的也算——看过就是看过，撤回观察不能退多重检验的代价。
    # 报告只读还在板上的那些。
    n = census(entries)
    live = live_entries(lines)
    if not live:
        click.echo(f"板上 {n} 个板位全部已退役（门的 N 仍按 {n} 算）。")
        return
    profile_payload = load_yaml(profile)
    cost = cost_model(load_yaml(costs_path), use_funding=funding)
    readings: list[dict[str, Any]] = []
    for item in live:
        chosen = _resolve_symbols(root, symbols, interval, item.universe)
        panel = _load(root, chosen, interval, start, end, funding)
        membership = _membership(root, item.universe, panel, min_tenure)
        spec = _entry(item.candidate, registry_path, json.dumps(item.params), grids)
        model = _model(spec, profile_payload, interval, min_history)
        weights, _combined, _per = model.evaluate(panel, membership)
        result, _priced = score_book(
            panel,
            weights,
            cost,
            execution=execution,
            guards=_book_guards(profile_payload, guards),
            exits=_exit_params(profile_payload, exits, interval),
        )
        readings.append(
            forward_reading(
                result.portfolio_net,
                item,
                bars_per_year=panel.bars_per_year,
                n_on_board=n,
                params_now=dict(spec.params),
            )
        )

    report = board_report(readings)
    report["board"] = str(board_file)
    # 板读数单独成文，不进任何 validate / book 报告。Scope Firewall 原话：
    # 「前向板读数不进任何历史选择」——一份混在一起的报告，迟早会有人拿板上的排序去挑候选。
    report["retired"] = len(retired)
    report["n_for_the_gate"] = n
    out_lines = [
        f"板上 {report['n_on_board']} 个在板（门按曾经的 {n} 个算，已退役 {len(retired)} 个）；到得了判定年数的 {report['decidable']} 个；"
        f"过门的 {report['passing']} 个；作废的 {report['tampered']} 个。"
    ]
    for reading in readings:
        if reading.get("verdict") == "TAMPERED":
            out_lines.append(f"  {reading['candidate']} {reading['param_key']}  作废：{reading['reason']}")
            out_lines.append(f"    → {reading['next_step']}")
            continue
        # 一个**今天刚上板**的候选前向窗口是空的，所以这三个都可能是 None，而那是正常状态不是异常：
        # 板位在上板那一刻就成立，读数要等下一根 bar。直接格式化 None 会让日任务在上板当天崩掉。
        sharpe_text = "—" if reading["sharpe_annual"] is None else f"{reading['sharpe_annual']:.3f}"
        gate_text = "—" if reading["threshold_annual"] is None else f"{reading['threshold_annual']:.3f}"
        years_text = "永远不够" if reading["years_to_decide"] is None else f"{reading['years_to_decide']:.2f}"
        out_lines.append(
            f"  {reading['candidate']} {reading['param_key']} {reading['universe']}  "
            f"前向 {reading['years_forward']:.2f} 年  S={sharpe_text}  "
            f"门={gate_text}  要看 {years_text} 年  {reading['verdict']}"
        )
        # 契约只在**要求有人动手**的时候印出来。一条还在观察的板位每天印四步契约是噪声，而噪声
        # 掩盖信号是这块板自己记过的那类错误（板读数换目录那一条）。
        if reading["verdict"] == PASSES or reading["long_enough"]:
            out_lines.append(f"    → {reading['next_step']}")
    for line in out_lines:
        click.echo(line)

    path, digest = _write(out, f"forward-board-{_stamp()}", report, "\n".join(["# 候选前向板", "", *out_lines]))
    click.echo(f"report: {path} sha256={digest}")
