"""上板花钱，读板不花钱——而且这两件事没有办法顺手搞混。

操作者 2026-09-17 裁定 Q-C = 建。方案里这块最贵的一条风险是 RISK-AM03：**板变成一条免费窥视通道**。
反过来还有一条同样坏的：读一次板就误计一笔。板的门按桶里的行数算，所以多记一笔会让**所有**在板
候选的判定年限一起变长——一次误计不是记错一个数，是把整块板往后推。

所以 `add` 与 `status` 是两条命令，而不是一条带模式的。下面把两个方向都钉住。
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest
from click.testing import CliRunner

from starquant_alpha.validation.forward_board import FORWARD_BOARD_STRATEGY, live_entries, read_board
from starquant_alpha.validation.ledger import parse_ledger
from starquant_cli import main
from starquant_data.store import KlineStore

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = str(ROOT / "config" / "alpha_registry.yaml")
PROFILE = str(ROOT / "config" / "live.demo.yaml")
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
#: 与 `test_cli_offline.py` 同一组：fixture 只有三个币、一个月数据，registry 的默认暖机跑不出决策。
#: `crowding_window: 0` 不是装饰——这些跑法传 `--no-funding`，而 tsmom 的默认参数开着读资金费的
#: 拥挤修正器。
FIXTURE_PARAMS = '{"vol_window": 100, "horizons": [5, 20, 50], "crowding_window": 0}'


def _store(august_dir: Path, root: Path) -> None:
    store = KlineStore(root)
    for symbol in SYMBOLS:
        frame = pd.read_parquet(august_dir / symbol / "1h.parquet")
        frame["close_time"] = frame["open_time"] + 3_600_000 - 1
        store.append(symbol, "1h", frame)


def _evidence(path: Path, sharpe: float | None = 1.59, *, tail: bool = False) -> Path:
    """写一份形状与本仓库 `validate` 一致的证据报告。

    `tail=True` 带上 `walk_forward.oos_is_full_sample_tail`——在架的 tsmom 证据就是这样，
    而板默认拒绝拿一条全样本尾巴当 `claimed_sharpe`。
    """
    payload: dict = {"kind": "validation", "strategy": "tsmom"}
    if sharpe is not None:
        payload["walk_forward"] = {"oos_sharpe": sharpe, "oos_is_full_sample_tail": tail}
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _add_args(tmp_path: Path, root: Path, evidence: Path, *extra: str) -> list[str]:
    return [
        "research",
        "forward",
        "add",
        "--strategy",
        "tsmom",
        "--params",
        FIXTURE_PARAMS,
        "--root",
        str(root),
        "--symbols",
        ",".join(SYMBOLS),
        "--registry",
        REGISTRY,
        "--profile",
        PROFILE,
        "--out",
        str(tmp_path / "reports"),
        "--board",
        str(tmp_path / "board.jsonl"),
        "--evidence",
        str(evidence),
        "--no-funding",
        "--min-history",
        "0",
        *extra,
    ]


def _ledger(tmp_path: Path) -> Path:
    """本套件的 ledger 被 `conftest.py` 重定向过，所以这里读的是那一份。"""
    import os

    return Path(os.environ["STARQUANT_TRIALS_LEDGER"])


def _board_rows(tmp_path: Path) -> list:
    path = tmp_path / "board.jsonl"
    return read_board(path.read_text(encoding="utf-8").splitlines()) if path.exists() else []


def _charges(tmp_path: Path) -> list:
    path = _ledger(tmp_path)
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    return parse_ledger(lines, FORWARD_BOARD_STRATEGY)


# ---- 拒跑：说不出价钱就不许上板 ----------------------------------------------------------


def test_adding_without_saying_the_price_refuses_before_any_data_is_read(tmp_path: Path) -> None:
    """守卫在碰数据之前响：`--root` 指向一个空目录，它仍然给出计费消息而不是数据错误。

    这与 `validate` 那道守卫是同一个形状，理由也一样——一条只有在跑完之后才拦得住的守卫，
    拦住的是已经花掉的钱。
    """
    evidence = _evidence(tmp_path / "evidence.json")
    empty = tmp_path / "empty-root"
    empty.mkdir()
    result = CliRunner().invoke(main, _add_args(tmp_path, empty, evidence))
    assert result.exit_code != 0
    assert "--charge 1" in result.output, result.output
    assert not _board_rows(tmp_path), "被拒的上板不该留下板位"


def test_the_refusal_says_what_it_costs_the_candidates_already_on_the_board(tmp_path: Path) -> None:
    """拒绝消息要说出「这一笔让已经在板上的每一个候选都要多等」——那才是真正的价钱。"""
    evidence = _evidence(tmp_path / "evidence.json")
    empty = tmp_path / "empty-root"
    empty.mkdir()
    result = CliRunner().invoke(main, _add_args(tmp_path, empty, evidence))
    assert "已经在板上的每一个候选" in result.output, result.output
    assert FORWARD_BOARD_STRATEGY in result.output


def test_a_wrong_number_is_refused_too(tmp_path: Path) -> None:
    evidence = _evidence(tmp_path / "evidence.json")
    empty = tmp_path / "empty-root"
    empty.mkdir()
    result = CliRunner().invoke(main, _add_args(tmp_path, empty, evidence, "--charge", "0"))
    assert result.exit_code != 0
    assert "--charge 1" in result.output


# ---- 证据：声称的 Sharpe 只能从报告里读 --------------------------------------------------


def test_evidence_without_a_sharpe_refuses_instead_of_defaulting_to_zero(tmp_path: Path) -> None:
    """读不到就说读不到。默认 0.0 会让年限读起来像「这个候选没希望」，而真相是没读到那个数。"""
    evidence = _evidence(tmp_path / "evidence.json", sharpe=None)
    empty = tmp_path / "empty-root"
    empty.mkdir()
    result = CliRunner().invoke(main, _add_args(tmp_path, empty, evidence, "--charge", "1"))
    assert result.exit_code != 0
    assert "读不到年化 Sharpe" in result.output


def test_a_missing_evidence_file_refuses(tmp_path: Path) -> None:
    empty = tmp_path / "empty-root"
    empty.mkdir()
    result = CliRunner().invoke(main, _add_args(tmp_path, empty, tmp_path / "nope.json", "--charge", "1"))
    assert result.exit_code != 0
    assert "证据报告不存在" in result.output


# ---- D-043：全样本尾巴不许安静地变成 claimed_sharpe ---------------------------------------


def test_a_full_sample_tail_is_refused_by_default(tmp_path: Path) -> None:
    """判定年限是 (z / claimed_sharpe)²——声称越高年限越短，所以乐观读数只会让板判得**太早**。

    在架的 tsmom 证据正是这种：`oos_sharpe` 1.5919 而 `oos_is_full_sample_tail` 为真，D-043 因此
    给它封顶 WEAK_PASS。板看不见这件事，就会拿 1.5919 去算年限。
    """
    evidence = _evidence(tmp_path / "tail.json", sharpe=1.5919, tail=True)
    empty = tmp_path / "empty-root"
    empty.mkdir()
    result = CliRunner().invoke(main, _add_args(tmp_path, empty, evidence, "--charge", "1"))
    assert result.exit_code != 0
    assert "全样本尾巴" in result.output and "--accept-full-sample-tail" in result.output
    assert not _board_rows(tmp_path)


@pytest.mark.usefixtures("isolated_trials_ledger")
def test_accepting_it_is_recorded_on_the_slot_for_life(tmp_path: Path, august_dir: Path) -> None:
    """承认了就上板，但承认本身写进条目——几年后读板的人要能看出这一条建在乐观读数上。"""
    root = tmp_path / "data"
    _store(august_dir, root)
    evidence = _evidence(tmp_path / "tail.json", sharpe=1.5919, tail=True)
    result = CliRunner().invoke(main, _add_args(tmp_path, root, evidence, "--charge", "1", "--accept-full-sample-tail"))
    assert result.exit_code == 0, result.output
    assert "全样本尾巴" in result.output, "上板成功也要把这件事说出来"
    rows = _board_rows(tmp_path)
    assert len(rows) == 1 and rows[0].claimed_is_full_sample_tail is True


@pytest.mark.usefixtures("isolated_trials_ledger")
def test_a_clean_report_needs_no_flag(tmp_path: Path, august_dir: Path) -> None:
    """守卫只拦尾巴。一份样本外真的是样本外的报告，照常上板。"""
    root = tmp_path / "data"
    _store(august_dir, root)
    evidence = _evidence(tmp_path / "clean.json", sharpe=1.27, tail=False)
    result = CliRunner().invoke(main, _add_args(tmp_path, root, evidence, "--charge", "1"))
    assert result.exit_code == 0, result.output
    assert _board_rows(tmp_path)[0].claimed_is_full_sample_tail is False


# ---- 上板：恰好一笔，且带着它的证据 -------------------------------------------------------


@pytest.mark.usefixtures("isolated_trials_ledger")
def test_a_declared_entry_charges_exactly_one_and_records_where_the_number_came_from(
    tmp_path: Path, august_dir: Path
) -> None:
    root = tmp_path / "data"
    _store(august_dir, root)
    evidence = _evidence(tmp_path / "evidence.json", sharpe=1.59)
    before = len(_charges(tmp_path))

    result = CliRunner().invoke(main, _add_args(tmp_path, root, evidence, "--charge", "1"))
    assert result.exit_code == 0, result.output

    rows = _board_rows(tmp_path)
    assert len(rows) == 1
    assert rows[0].claimed_sharpe == pytest.approx(1.59)
    assert rows[0].evidence.endswith("evidence.json")
    assert len(rows[0].evidence_sha256) == 64, "证据的摘要要钉住——否则报告改了没人知道"
    assert len(_charges(tmp_path)) == before + 1, "上板要恰好计一笔"


@pytest.mark.usefixtures("isolated_trials_ledger")
def test_the_same_candidate_twice_does_not_pay_twice(tmp_path: Path, august_dir: Path) -> None:
    """同一个候选、同参数、同 universe、同构造 = 同一个板位。第二次不是新的观察。"""
    root = tmp_path / "data"
    _store(august_dir, root)
    evidence = _evidence(tmp_path / "evidence.json")
    runner = CliRunner()
    assert runner.invoke(main, _add_args(tmp_path, root, evidence, "--charge", "1")).exit_code == 0
    charged_once = len(_charges(tmp_path))

    second = runner.invoke(main, _add_args(tmp_path, root, evidence, "--charge", "1"))
    assert second.exit_code == 0
    assert "已在板上" in second.output
    assert len(_charges(tmp_path)) == charged_once, "第二次上板又计了一笔"
    assert len(_board_rows(tmp_path)) == 1


# ---- 读板：一分钱都不能花 -----------------------------------------------------------------


@pytest.mark.usefixtures("isolated_trials_ledger")
def test_reading_the_board_never_writes_a_ledger_row(tmp_path: Path, august_dir: Path) -> None:
    """这一条是这个文件的理由。

    板的门按桶里的行数算，所以读一次板若误计一笔，不是记错一个数——是把**整块板**的判定年限
    一起往后推。而读板是要每天跑的（launchd），所以这条错误会以一天一次的速度累积。
    """
    root = tmp_path / "data"
    _store(august_dir, root)
    evidence = _evidence(tmp_path / "evidence.json")
    runner = CliRunner()
    assert runner.invoke(main, _add_args(tmp_path, root, evidence, "--charge", "1")).exit_code == 0
    after_add = len(_charges(tmp_path))

    args = [
        "research",
        "forward",
        "status",
        "--root",
        str(root),
        "--symbols",
        ",".join(SYMBOLS),
        "--registry",
        REGISTRY,
        "--profile",
        PROFILE,
        "--out",
        str(tmp_path / "reports"),
        "--board",
        str(tmp_path / "board.jsonl"),
        "--no-funding",
        "--min-history",
        "0",
    ]
    for _ in range(3):  # 跑三次，模拟连着三天的日任务
        result = runner.invoke(main, args)
        assert result.exit_code == 0, result.output

    assert len(_charges(tmp_path)) == after_add, "读板花掉了钱"
    assert "OBSERVING" in result.output, "才上板就给出裁定了"


@pytest.mark.usefixtures("isolated_trials_ledger")
def test_day_one_reads_as_zero_forward_bars_rather_than_crashing(tmp_path: Path, august_dir: Path) -> None:
    """一个今天刚上板的候选，前向窗口是空的——那是**正常状态**，不是异常。

    板位在上板那一刻就成立，读数要等下一根 bar。这条测试写出来是因为第一版真的崩在这里：
    `threshold_annual` 是 `None` 而输出行直接格式化了它，于是日任务会在每个候选上板的当天挂掉。
    """
    root = tmp_path / "data"
    _store(august_dir, root)
    runner = CliRunner()
    assert (
        runner.invoke(main, _add_args(tmp_path, root, _evidence(tmp_path / "evidence.json"), "--charge", "1")).exit_code
        == 0
    )

    result = runner.invoke(
        main,
        [
            "research",
            "forward",
            "status",
            "--root",
            str(root),
            "--symbols",
            ",".join(SYMBOLS),
            "--registry",
            REGISTRY,
            "--profile",
            PROFILE,
            "--out",
            str(tmp_path / "reports"),
            "--board",
            str(tmp_path / "board.jsonl"),
            "--no-funding",
            "--min-history",
            "0",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "前向 0.00 年" in result.output and "S=—" in result.output
    assert "OBSERVING" in result.output


def test_the_daily_job_can_actually_call_the_command_it_calls(tmp_path: Path) -> None:
    """`deploy/run_forward_board.sh` 里那行命令必须真的能跑。

    这条是补的，因为第一版漏了它，代价是**日任务每天失败**：`status` 从 `_common_options` 继承了
    必填的 `--strategy`，而脚本只传 `--board`。失败的形式是 click 的用法错误，看起来像脚本写错，
    而其实是命令定义错。当时的 shell 只做了 `bash -n` 语法检查——语法检查看不见这个。

    所以这里不检查语法，而是把脚本里真正那行的参数喂给命令本身。
    """
    script = (ROOT / "deploy" / "run_forward_board.sh").read_text(encoding="utf-8")
    line = next(li for li in script.splitlines() if "research forward status" in li and "starquant" in li)
    # 脚本里是 `"$REPO/.venv/bin/starquant" research forward status --board "$BOARD" 2>&1`
    assert "--board" in line, "脚本不再显式传 --board 了？那它会依赖命令的默认值"
    flags = [token for token in line.split() if token.startswith("--")]

    params = {opt for p in main.commands["research"].commands["forward"].commands["status"].params for opt in p.opts}
    unknown = [flag for flag in flags if flag not in params]
    assert not unknown, f"脚本传了命令不认识的选项：{unknown}"

    result = CliRunner().invoke(main, ["research", "forward", "status", "--board", str(tmp_path / "nothing.jsonl")])
    assert result.exit_code == 0, f"日任务那行跑不起来：{result.output}"


def test_status_needs_no_strategy_because_the_board_carries_it(tmp_path: Path) -> None:
    """板位的策略、参数、universe 都在条目里——那正是上板时钉死的东西，不该再从命令行要一遍。"""
    required = [p.opts for p in main.commands["research"].commands["forward"].commands["status"].params if p.required]
    assert not required, f"`status` 不该有必填项，现在有：{required}"


def test_status_on_an_empty_board_says_so_and_charges_nothing(tmp_path: Path) -> None:
    before = len(_charges(tmp_path))
    result = CliRunner().invoke(
        main,
        [
            "research",
            "forward",
            "status",
            "--root",
            str(tmp_path),
            "--registry",
            REGISTRY,
            "--profile",
            PROFILE,
            "--out",
            str(tmp_path / "reports"),
            "--board",
            str(tmp_path / "nothing.jsonl"),
        ],
    )
    assert result.exit_code == 0
    assert "板是空的" in result.output
    assert len(_charges(tmp_path)) == before


# ---- 退役与重上：更正一个钉错的板位 --------------------------------------------------------


def _board_lines(tmp_path: Path) -> list[str]:
    path = tmp_path / "board.jsonl"
    return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


@pytest.mark.usefixtures("isolated_trials_ledger")
def test_retire_then_re_add_leaves_exactly_one_live_slot(tmp_path: Path, august_dir: Path) -> None:
    """走一遍真实的更正流程：上板 -> 退役 -> 用新证据重上。

    第一版这里是坏的：退役按身份相减，把重上的那个也减掉了，`status` 报「全部已退役」。
    """
    root = tmp_path / "data"
    _store(august_dir, root)
    runner = CliRunner()

    first = _evidence(tmp_path / "tail.json", sharpe=1.5919, tail=True)
    assert (
        runner.invoke(main, _add_args(tmp_path, root, first, "--charge", "1", "--accept-full-sample-tail")).exit_code
        == 0
    )
    key = _board_rows(tmp_path)[0].param_key

    retired = runner.invoke(
        main,
        [
            "research",
            "forward",
            "retire",
            "--candidate",
            "tsmom",
            "--param-key",
            key,
            "--universe",
            "static",
            "--reason",
            "claimed 钉的是一条全样本尾巴",
            "--board",
            str(tmp_path / "board.jsonl"),
        ],
    )
    assert retired.exit_code == 0, retired.output
    assert "看过就是看过" in retired.output
    assert live_entries(_board_lines(tmp_path)) == []

    second = _evidence(tmp_path / "clean.json", sharpe=1.2757, tail=False)
    again = runner.invoke(main, _add_args(tmp_path, root, second, "--charge", "1"))
    assert again.exit_code == 0, again.output
    assert "重上" in again.output

    live = live_entries(_board_lines(tmp_path))
    assert len(live) == 1, "重上之后板应该恰好一个在板"
    assert live[0].claimed_sharpe == pytest.approx(1.2757)

    status = runner.invoke(
        main,
        [
            "research",
            "forward",
            "status",
            "--root",
            str(root),
            "--symbols",
            ",".join(SYMBOLS),
            "--registry",
            REGISTRY,
            "--profile",
            PROFILE,
            "--out",
            str(tmp_path / "out"),
            "--board",
            str(tmp_path / "board.jsonl"),
            "--no-funding",
            "--min-history",
            "0",
        ],
    )
    assert status.exit_code == 0, status.output
    assert "已退役 1 个" in status.output
    assert "要看 1.66 年" in status.output, f"年限没跟着新的声称值走：{status.output}"


def test_retiring_something_not_on_the_board_says_so(tmp_path: Path) -> None:
    (tmp_path / "board.jsonl").write_text("", encoding="utf-8")
    result = CliRunner().invoke(
        main,
        [
            "research",
            "forward",
            "retire",
            "--candidate",
            "tsmom",
            "--param-key",
            "deadbeef",
            "--universe",
            "pit",
            "--reason",
            "x",
            "--board",
            str(tmp_path / "board.jsonl"),
        ],
    )
    assert result.exit_code != 0 and "板上没有" in result.output


def test_the_daily_job_writes_outside_reports_research(tmp_path: Path) -> None:
    """板读数不进 `reports/research/`——那里放的是计过费的证据，板读数是每天一份的派生物。"""
    from starquant_cli.research_forward_cmd import DEFAULT_BOARD_REPORTS

    assert not DEFAULT_BOARD_REPORTS.startswith("reports/research"), DEFAULT_BOARD_REPORTS
    params = {p.opts[0]: p.default for p in main.commands["research"].commands["forward"].commands["status"].params}
    assert params["--out"] == DEFAULT_BOARD_REPORTS
