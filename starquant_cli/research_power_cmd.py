"""``starquant research power``：门的功效表，跑之前就能算，一行 ledger 都不动。

**为什么要有这条命令。** 操作者到 2026-09-18 已经四次问「判定条件是不是太严」。四次的回答都是
「不是门」，四次都没有给数——所以问题每次都回来。数其实一直在手边：样本外 Sharpe 估计的标准误
就写在每份报告的 `oos_selection.variance` 里，而「真 Sharpe 是 s 的策略有多大概率过这道门」是
一次正态尾概率。`2026-09-18` 的分析（§5.2.1）把它算了出来——**真 Sharpe 1.0 的策略在空桶里也只有
一半机会过 1.0 那条 PASS 线**，与 D-028 无关，是五年样本外的抽样噪声。

**为什么它要能在跑之前算。** M-SY01 要求的是「每份新预登记在写下网格与桶时同时写下该 N 下的功效
读数」。预登记是写在跑之前的，那时候还没有这一次的 `variance`——所以方差从**同族最近一份报告**借，
而这条借用必须被写出来、不能默认：命令强制 `--evidence`，并把那份报告的路径与 sha256 印在输出里。

**为什么它免费。** 它读一个 JSON、算一次正态分位数，不碰面板、不跑回测、不写 `trials.jsonl`。
`test_research_power_writes_nothing` 钉住这一条。

**它不判定任何东西。** 功效低不是放宽门的理由：α 是操作者签的 0.05，而功效是样本长度的函数。
这张表能改变的是**要不要跑**——一次在 N=299 的桶里对真 Sharpe 1.5 只有 43% 把握的 validate，
花的是同一笔 ledger，而且会把所有同桶候选的门再抬高一点。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import click

from starquant_alpha.panel import bars_per_year as bars_per_year_of
from starquant_alpha.validation.multiple_testing import PASS_LINE_ANNUAL, POWER_SHARPES, selection_power
from starquant_cli import research
from starquant_cli.research_report import _power_rows


def _evidence(path: Path) -> tuple[dict[str, Any], str]:
    if not path.exists():
        raise click.BadParameter(f"--evidence {path} 不存在")
    raw = path.read_bytes()
    return json.loads(raw.decode("utf-8")), hashlib.sha256(raw).hexdigest()


@research.command("power")
@click.option(
    "--evidence",
    required=True,
    help=(
        "方差从哪份报告借（JSON）。**不接受手输的方差**：手输的那个数正是会被往大里写的——"
        "方差越大标准误越大，功效表就越好看。同族最近一份 `research validate` 的报告是正解。"
    ),
)
@click.option("--trials", type=int, default=None, help="要算哪个 N。默认取证据报告自己的 `n_trials`。")
@click.option(
    "--charge",
    type=int,
    default=0,
    show_default=True,
    help="这次打算再花几笔（网格格数）。给出时多印一行 N+charge——那才是这次运行真正要面对的门。",
)
@click.option("--alpha", type=float, default=0.05, show_default=True, help="D-028 的 α。操作者签的是 0.05。")
@click.option(
    "--pass-line",
    type=float,
    default=PASS_LINE_ANNUAL,
    show_default=True,
    help="D-020 的 PASS 线。门取它与 D-028 选择门的较大者。",
)
@click.option(
    "--sharpe",
    "sharpes",
    multiple=True,
    type=float,
    help=f"在哪些「真年化 Sharpe」上读功效。默认 {list(POWER_SHARPES)}。",
)
def research_power(
    evidence: str,
    trials: int | None,
    charge: int,
    alpha: float,
    pass_line: float,
    sharpes: tuple[float, ...],
) -> None:
    """门的功效：真 Sharpe 是 s 的策略，有多大概率过得了这道门。零 ledger。"""
    path = Path(evidence)
    report, digest = _evidence(path)
    block = report.get("oos_selection") or {}
    variance = block.get("variance")
    if not isinstance(variance, (int, float)) or variance <= 0:
        raise click.ClickException(
            f"{path} 里没有可用的 `oos_selection.variance`——功效表的标准误就是从它来的。"
            "换一份 `research validate` 写的报告。"
        )
    interval = str(report.get("interval") or "1h")
    bpy = bars_per_year_of(interval)
    base_n = int(trials if trials is not None else block.get("n_trials") or 1)
    wanted = tuple(sharpes) or POWER_SHARPES

    click.echo(f"evidence: {path} sha256={digest}")
    click.echo(
        f"  interval={interval} bars_per_year={bpy:g} n_obs={block.get('n_obs')} "
        f"variance={variance:.6g} (这份报告自己量的样本外方差)"
    )
    if trials is not None and trials != block.get("n_trials"):
        click.echo(f"  N 由 --trials 指定为 {base_n}，证据报告自己的是 {block.get('n_trials')}")
    for n in (base_n, base_n + charge) if charge else (base_n,):
        power = selection_power(
            sharpe_variance=float(variance),
            bars_per_year=bpy,
            n_trials=n,
            alpha=alpha,
            pass_line_annual=pass_line,
            true_sharpes=wanted,
        )
        label = f"N={n}" + ("（这次跑完的 N）" if charge and n != base_n else "")
        click.echo("")
        click.echo(f"## {label}")
        for key, value in _power_rows(power).items():
            click.echo(f"    {key}: {value}")
    click.echo("")
    click.echo(
        "把上面这张表抄进预登记，紧挨着网格与桶（M-SY01）。方差是借来的——它是样本外序列长度与"
        "矩的函数，换一个候选会变，所以这是一个**估计**，不是这次运行的读数。"
    )
    click.echo("零 ledger：本命令不写 trials.jsonl，不写报告，不碰面板。")
