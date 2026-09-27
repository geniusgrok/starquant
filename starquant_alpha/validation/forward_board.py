"""候选前向板：把「可观察」的候选数从 2 提到数十，代价是每上一个板都让所有候选更难过门。

**它买的是什么，以及明确不是什么。** 2026-09-17 的 alpha 模块深度分析（C-AM08，`docs/analysis/
2026-09-17-alpha-module-deep-analysis.md`）把这件事的价钱算过：板提高的是**可观察**的候选数，不是
**可裁定**的。在 `Policy.max_concurrent_probes = 2` 之下，任何时刻只有两个候选在拿真实盘位；板让
几十个候选同时被前向记录，venue 成本为零。但判定要年：单候选按 S=1.5 判到 z=2 要约 1.8 年，板上 30
个候选按选择门要 z≈2.93，即约 3.8 年（`years_to_decide` 就是这两个数的来源）。所以这个模块的每一份
读数都带 `verdict: OBSERVING` 与 `years_to_decide`，**在到点之前它不产生任何裁定**。

**四条不变式，每条都对应一个已写下的失败模式。**

1. **前向就是前向。** 读数只用 `entered_at` 当根 bar 及其之后的收益（`forward_slice`）。一个候选上板
   之前的表现，无论多好，都不进它的板读数——那正是它上板之前已经被用过的那部分样本。
2. **上板即计费，计到独立桶。** 每次 `add` 在 `FORWARD_BOARD_STRATEGY` 桶里写一行。`ledger_scope`
   对任何真实策略都不返回这个桶，所以板的计费**不进任何 family gate 的分母**。RISK-AM03：板若不
   计费就是一条免费窥视通道。
   **门的 N 不是这个桶的行数，是 `census`——板上不同板位的个数**（含退役的）。两者不相等，也不该
   相等：ledger 的行数是「有人做过几次动作」的审计痕迹（重新钉一次声称值也算一次），而 N 是
   「在看几个不同的假设」。重上同一个板位不是一个新候选，所以它不抬门。
3. **板上的候选不许被换参数。** 条目记 `param_key`（参数的规范摘要）。重算时参数对不上就是
   `TAMPERED`，那一条作废而不是给出读数（FM-AM4：板上候选被换参数 → 撤板）。
4. **板读数不进任何历史选择。** 这个模块不导出任何能喂给 `validate` / `book` 的东西，它的报告也
   单独成文。Scope Firewall 原话：「前向板读数不进任何历史选择」。
5. **PASS 买到的是一份新预登记的资格，不是一次裁定。** 2026-09-18 补（Q-SY2 的前置 (a)）。在此
   之前板的出口是空的——K-SY08 的原话：「板 PASS 只产生一条读数，没有后续契约」。一个没有出口的
   观察机制是停车场：候选进来、年限到了、没有任何人被要求做任何事，而 `years_to_decide` 还会随着
   别人上板继续变长。所以出口与入口一起写死，两个方向都写：过门走 `BOARD_PASS_CONTRACT` 的四步
   （新预登记 → probe，**不解除任何 `reopen.yaml` 条件**），到点没过门按 `BOARD_EXIT_CONTRACT`
   退役、不延期。每份读数都带 `next_step`，所以三年后读这块板的人不必去翻一份分析文档的第 7 节。

**门为什么不直接用 `max_sharpe_quantile`。** 那是 D-028 的选择门，`n_trials <= 1` 时按约定返回
0.0——没有选择就没有选择门，这在 `validate` 里是对的，因为显著性由别处的 OOS 门与 DSR 负责。板不同：
板上的读数**本身就是那个检验**，所以哪怕只有一个候选也要过普通的单边 95%。`board_threshold` 因此取
「选择门」与「单边临界值」的较大者。**不改 `max_sharpe_quantile`**：它是 `validate` 在用的门，动它
是一次 R10 规则变更，会移动每一条历史裁决的阈值。
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd

from starquant_alpha.report import canonical_json
from starquant_alpha.validation.metrics import normal_ppf
from starquant_alpha.validation.multiple_testing import max_sharpe_quantile, sampling_variance

#: 板自己的 ledger 桶。`ledger_scope` 对任何真实策略都不会返回它，所以板的计费不进 family gate。
#: 与 `MINED_SEARCH_STRATEGY` / `PAIR_SEARCH_STRATEGY` 同一形状：桶属于**那次观察**，不属于被观察的策略。
FORWARD_BOARD_STRATEGY = "forward_board"

#: 板读数的三种状态。没有第四种——尤其没有「通过」以外的任何软性说法。
OBSERVING = "OBSERVING"  # 还没到可判的年数，或还没过门
PASSES = "PASSES_BOARD_GATE"  # 过了按今天板大小算的门
TAMPERED = "TAMPERED"  # 参数与上板时对不上，这一条作废


#: 一份板读数**买到了什么**，按它的处境分。四条里没有一条是「裁定」。
#:
#: 这块东西 2026-09-18 才写下来（Q-SY2，操作者裁「要」的前置 (a)）。在那之前板 PASS 只产生一条
#: 读数：K-SY08 的原话是「板 PASS 只产生一条读数，**没有后续契约**」。一个没有出口的观察机制是
#: 停车场——候选进来、年限到了、然后没有任何人被要求做任何事，而 `years_to_decide` 会随着别人上板
#: 继续变长。所以出口和入口一起写死，两个方向都写：过门要走哪四步，没过门要退役。
BOARD_PASS_CONTRACT = (
    "过了按今天板大小算的门。**这不是裁定**，它买到的是「一份新预登记的资格」，四步缺一不可：\n"
    "(1) 新预登记按 docs/PREREGISTRATION.md 九项写，假设必须是**前向的**"
    "（「这个板位自 entered_at 起交付了 X」），不得回头再搜历史网格；\n"
    "(2) 功效读数（模板第 5 项）用**板自己的 N** 与 `board_threshold`，不是 validate 的桶；\n"
    "(3) 申请的是 **probe 位**（`Policy.max_concurrent_probes = 2`），不是主书。probe 要 registry 里"
    "一个 `probe` 块（D-019 / D-029：accepted_by / accepted_on / reason / review_after_days / stop）"
    "与一份被引用的报告——**板读数不是那份报告**，所以仍要一次按正常规则计费的 validate；\n"
    "(4) 原族 `governance/reopen.yaml` 的重开条件**不因板 PASS 而解除**。板 PASS 是向操作者提出"
    "重开的**理由**，由 `check: operator` 裁，不是自动重开。"
)

#: 到点而没过门：退役，不延期。
BOARD_EXIT_CONTRACT = (
    "到点了（`long_enough` 为真）而没过门：按契约 `research forward retire` 退役这个板位。"
    "**不延期、不换 `claimed_sharpe`、不换参数。** 延期是事后把判定年限改成「再等等看」，"
    "而那个年限正是上板时钉死 claimed 要防的循环，只是换了个方向。"
)

#: 还没到点：读数存在，裁定不存在。
BOARD_OBSERVING_CONTRACT = (
    "还在观察。到 `years_to_decide` 之前，这条读数不构成任何裁定——今天在门上面也不算，那只是「今天恰好好看」。"
)

#: 参数对不上：这一条作废。
BOARD_TAMPERED_CONTRACT = (
    "参数与上板时对不上，这一条作废，不给读数（FM-AM4）。要重新观察就先 retire 再 add，"
    "重上**再计一笔**——旧的那次观察不退钱。"
)


def next_step(*, verdict: str, long_enough: bool) -> str:
    """一条读数之后**谁该做什么**。永远有一句，永远不是空的。

    读数带 `verdict` 与 `years_to_decide` 已经挡住了「把板当排行榜读」；这一句挡的是另一件事——
    读完之后没有人知道该做什么，于是什么都不做。三年后读这块板的人（可能不是今天这个人）要能
    从 artefact 本身读到出口，而不是去翻一份分析文档的第 7 节。
    """
    if verdict == TAMPERED:
        return BOARD_TAMPERED_CONTRACT
    if verdict == PASSES:
        return BOARD_PASS_CONTRACT
    return BOARD_EXIT_CONTRACT if long_enough else BOARD_OBSERVING_CONTRACT


@dataclass(frozen=True)
class BoardEntry:
    """一个候选上板时被钉住的东西。append-only：改一个条目等于换一个候选。"""

    candidate: str  # 候选来自哪个族（记录用，**不是**它的 ledger 桶）
    param_key: str  # 上板时参数的规范摘要，重算时要对上
    params: dict[str, Any]
    universe: str
    construction_digest: str
    entered_at: str  # UTC ISO。前向窗口从这里开始，一根 bar 都不往前借
    run_id: str
    #: 上板时这个候选**声称**的年化 Sharpe（来自让它够格上板的那份 validate 报告）。
    #: 判定年限由它算，**不由后来观察到的 Sharpe 算**——否则一个早期走运的候选会自己缩短
    #: 自己的年限，那正是这块东西该防的循环。它在上板那一刻钉死，此后不再变。
    claimed_sharpe: float = 0.0
    #: 那个 `claimed_sharpe` 是从哪份报告读出来的，以及那份报告的 sha256。
    #: 不让它手输，是因为手输的「声称 Sharpe」正是会被往低里写的那个数——写低一点，
    #: `years_to_decide` 就短一点，板位就能早点「到期」。从报告读并钉住摘要，这条路就堵上了。
    evidence: str = ""
    evidence_sha256: str = ""
    #: 那份证据自己的裁决。板不因为 FAIL 就拒绝上板——板要看的正是「可观察但不可裁定」的那批，
    #: 而一份 FAIL 报告的样本外仍然是一次测量。但读板的人要能看见它。
    evidence_verdict: str = ""
    #: 这个 `claimed_sharpe` 是不是一条全样本尾巴（D-043），以及上板时操作者显式承认了它。
    #: 跟着板位走完一生：几年后读这块板的人要能看出这一条的年限是建在乐观读数上的。
    claimed_is_full_sample_tail: bool = False
    note: str = ""

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, ensure_ascii=False)

    @classmethod
    def from_json(cls, line: str) -> BoardEntry | None:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None
        try:
            return cls(
                candidate=str(payload["candidate"]),
                param_key=str(payload["param_key"]),
                params=dict(payload["params"]),
                universe=str(payload["universe"]),
                construction_digest=str(payload["construction_digest"]),
                entered_at=str(payload["entered_at"]),
                run_id=str(payload["run_id"]),
                claimed_sharpe=float(payload.get("claimed_sharpe", 0.0)),
                evidence=str(payload.get("evidence", "")),
                evidence_sha256=str(payload.get("evidence_sha256", "")),
                evidence_verdict=str(payload.get("evidence_verdict", "")),
                claimed_is_full_sample_tail=bool(payload.get("claimed_is_full_sample_tail", False)),
                note=str(payload.get("note", "")),
            )
        except (KeyError, TypeError, ValueError):
            return None

    def identity(self) -> tuple[str, str, str, str]:
        """同一候选、同一参数、同一 universe、同一构造 = 同一个板位，第二次上板不另计费。"""
        return (self.candidate, self.param_key, self.universe, self.construction_digest)


def _normalised(value: Any) -> Any:
    """整值浮点归一为整数，其余原样。

    这一步只为一件事：参数经 YAML/JSON 往返一次，`168` 可能变成 `168.0`。那不是换了候选，而
    `tampering` 误报会**作废一个真板位**——一个已经前向观察了两年、再也补不回来的板位。所以这里
    归一，而且只归一这一种：别的类型差异（字符串 "168" 对数字 168）确实是不同的输入，不该被抹平。

    `bool` 明确排除：`True` 是 `int` 的子类，归一会让 `enabled: true` 与 `enabled: 1` 撞成一个键，
    而那两个在 YAML 里是不同的写法、也该是不同的候选。
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, Mapping):
        return {str(k): _normalised(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalised(v) for v in value]
    return value


def board_param_key(candidate: str, params: Mapping[str, Any]) -> str:
    """参数的规范摘要。用 `canonical_json` 而不是 `str(dict)`：键序与浮点写法都不该改变身份。"""
    return hashlib.sha256(f"{candidate}|{canonical_json(_normalised(dict(params)))}".encode()).hexdigest()[:16]


#: 一份报告里「年化 Sharpe」可能待的地方，按优先级。**样本外优先于全样本**，这个顺序是契约的一部分。
#:
#: 这几条路径是 2026-09-17 照**真实归档报告**改过的。第一版按一份手写 fixture 的形状写成
#: `oos.annualized_sharpe`，而这个仓库的 `validate` 根本不产生那个键——第一次拿在架的
#: `tsmom-validation-20260913T182325Z.json` 上板就读出 `None`。
#: `tests/alpha/test_the_board_reads_the_reports_this_repo_actually_writes.py` 现在拿归档里的真报告
#: 钉住它，所以报告形状再变就是红的，不是安静地读不到。
CLAIMED_SHARPE_PATHS: tuple[tuple[str, ...], ...] = (
    ("walk_forward", "oos_sharpe"),  # validate：走 walk-forward 的样本外
    ("best_key_oos_sharpe",),  # 同上，顶层的那份
    ("oos", "annualized_sharpe"),  # 留着：别处产生的报告有用这个形状的
    ("summary", "annualized_sharpe"),  # backtest：只有全样本，所以排在最后
)

#: `walk_forward` 里那个自述字段：这份报告的「样本外」其实是全样本的尾巴。
FULL_SAMPLE_TAIL_FIELD = ("walk_forward", "oos_is_full_sample_tail")


def _dig(report: Mapping[str, Any], path: tuple[str, ...]) -> Any:
    node: Any = report
    for key in path:
        if not isinstance(node, Mapping) or key not in node:
            return None
        node = node[key]
    return node


def claimed_sharpe_from(report: Mapping[str, Any]) -> tuple[float | None, str]:
    """从一份报告里读上板时该钉住的 Sharpe。返回 (值, 它在报告里的路径)。

    找不到就返回 `(None, "")` 而不是 0.0：0.0 会让 `years_to_decide` 返回 `None`，读起来像
    「这个候选没希望」，而真相是「没读到那个数」。两件事混在一起，板会安静地记下一个错的年限。
    """
    for path in CLAIMED_SHARPE_PATHS:
        node = _dig(report, path)
        if isinstance(node, (int, float)) and not isinstance(node, bool) and math.isfinite(float(node)):
            return float(node), ".".join(path)
    return None, ""


def full_sample_tail(report: Mapping[str, Any]) -> bool:
    """这份报告自己说它的「样本外」是全样本尾巴吗（D-043）。

    **为什么板要管这件事。** `years_to_decide` 是 `(z / claimed_sharpe)²`——**声称的 Sharpe 越高，
    年限越短**。一条全样本尾巴给出的是这个候选的乐观读数（在架 tsmom：尾巴 1.5919，而真选择网格下
    的样本外是 1.27–1.28），拿它当基准，板会在一个被高估的数上提早宣布「够久了」，而那时估计量的
    噪声还大，一段走运的行情更容易把它推过门。

    误差的方向是要紧的：高估 claimed 只会让板判得**太早**，不会让它判得太晚。所以默认拒绝，
    要用就显式承认——承认本身会被写进板条目，跟着这个板位走完它的一生。
    """
    return _dig(report, FULL_SAMPLE_TAIL_FIELD) is True


@dataclass(frozen=True)
class Retirement:
    """把一个板位从**报告**里撤下来，但**不**把它从门的 N 里撤下来。

    这两件事必须分开，否则板就有了一个后门：退掉表现差的板位，所有还在板上的候选的门就降低了。
    「看过就是看过」——那一笔花掉的钱买的是一次观察的权利，撤回观察不能退钱，也不能退多重检验的代价。

    所以 `census`（门的 N）数的是**曾经上过板的所有板位**，而 `live_entries`（报告读哪些）才排除
    退役的。退役的唯一正当用途是**更正**：一个板位的 `claimed_sharpe` 钉错了，换一个重上，而旧的
    那一次观察照样计在 N 里。
    """

    candidate: str
    param_key: str
    universe: str
    construction_digest: str
    retired_at: str
    reason: str

    def to_json(self) -> str:
        return json.dumps({"retired": asdict(self)}, sort_keys=True, ensure_ascii=False)

    def identity(self) -> tuple[str, str, str, str]:
        return (self.candidate, self.param_key, self.universe, self.construction_digest)

    @classmethod
    def from_json(cls, line: str) -> Retirement | None:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            return None
        node = payload.get("retired") if isinstance(payload, dict) else None
        if not isinstance(node, dict):
            return None
        try:
            return cls(
                candidate=str(node["candidate"]),
                param_key=str(node["param_key"]),
                universe=str(node["universe"]),
                construction_digest=str(node["construction_digest"]),
                retired_at=str(node["retired_at"]),
                reason=str(node["reason"]),
            )
        except (KeyError, TypeError, ValueError):
            return None


def read_retirements(lines: Iterable[str]) -> list[Retirement]:
    out: list[Retirement] = []
    for line in lines:
        if not line.strip():
            continue
        item = Retirement.from_json(line)
        if item is not None:
            out.append(item)
    return out


def live_entries(lines: Iterable[str]) -> list[BoardEntry]:
    """报告读哪些板位。**不是** `census` 数的那些——见 `Retirement` 的 docstring。

    **按文件顺序折叠，不是按集合相减。** 这是 append-only 文件唯一正确的读法，也是第一版写错的地方：
    退役与重上的板位身份完全相同（同参数、同 universe、同构造），按身份相减会把**重上的那个也
    一起减掉**，板于是读成空的。位置在这里是有意义的——一条退役只作用于它**之前**的那个条目，
    之后再 append 的同身份条目是新的一次观察，重新生效。

    这也正是「更正一个钉错的 `claimed_sharpe`」那条路能走通的原因：退役旧的、append 新的，
    而两次都留在 `census` 里。
    """
    held: dict[tuple[str, str, str, str], BoardEntry | None] = {}
    order: list[tuple[str, str, str, str]] = []
    for line in lines:
        if not line.strip():
            continue
        entry = BoardEntry.from_json(line)
        if entry is not None:
            if entry.identity() not in held:
                order.append(entry.identity())
            held[entry.identity()] = entry
            continue
        retirement = Retirement.from_json(line)
        if retirement is not None and retirement.identity() in held:
            held[retirement.identity()] = None
    out: list[BoardEntry] = []
    for key in order:
        entry = held[key]
        if entry is not None:
            out.append(entry)
    return out


def read_board(lines: Iterable[str]) -> list[BoardEntry]:
    """读板。坏行跳过而不是抛错——板是 append-only 的记录，一行坏掉不该让整块读不出来。"""
    out: list[BoardEntry] = []
    for line in lines:
        if not line.strip():
            continue
        entry = BoardEntry.from_json(line)
        if entry is not None:
            out.append(entry)
    return out


def census(entries: Sequence[BoardEntry]) -> int:
    """**曾经**上过板的板位数。门的 N 就是它——**板越大，每个候选越难过门**。

    数的是曾经，不是现在：退役一个板位不会把它从这里撤下来（见 `Retirement`）。否则退掉输家
    就能降低所有还在板上的候选的门，而那正是这块东西要防的那类事。

    这与 D-028「搜得越多越退休自己的 incumbent」是同一条性质，换到前向上：多看一个候选，
    是在抬高所有候选的门，包括已经在板上看了两年的那个。写在这里是为了让加板位这件事有价钱。
    """
    return len({entry.identity() for entry in entries})


def already_on_board(entries: Sequence[BoardEntry], candidate: BoardEntry) -> bool:
    return candidate.identity() in {entry.identity() for entry in entries}


def tampering(entry: BoardEntry, params_now: Mapping[str, Any]) -> str:
    """参数对不上就是作废，不是「大致还是那个候选」。返回空串表示没问题。"""
    key_now = board_param_key(entry.candidate, params_now)
    if key_now == entry.param_key:
        return ""
    return (
        f"板上 `{entry.candidate}` 的参数摘要是 {entry.param_key}，今天重算得到 {key_now}。"
        "板上的候选不许被换参数——换了就是另一个候选，要另开一个板位并另行计费。"
    )


def forward_slice(net: pd.Series, entered_at: str) -> pd.Series:
    """只留 `entered_at` 当根 bar 及其之后的收益。

    这是这块东西的全部意义所在，所以它是一个有名字的函数而不是一行切片：一个候选上板之前的表现
    已经被它上板这件事本身用掉了，把那段收益算进板读数，板就成了另一种样本内。
    """
    if net.empty:
        return net
    start = pd.Timestamp(entered_at)
    if start.tzinfo is None:
        start = start.tz_localize(UTC)
    index = net.index
    if isinstance(index, pd.DatetimeIndex) and index.tz is None:
        index = index.tz_localize(UTC)
        net = pd.Series(net.to_numpy(), index=index, name=net.name)
    return net[net.index >= start]


def board_threshold(n_on_board: int, *, n_obs: int, alpha: float = 0.05) -> float:
    """今天板上这么多候选时，一个候选要清的**每期** Sharpe。

    取两者较大：D-028 的选择门（`max_sharpe_quantile`，N<=1 时按约定为 0），以及普通的单边
    `1 - alpha` 临界值。后者是地板：板上只有一个候选时没有选择偏差，但「看了就算数」仍要过显著性，
    而在 `validate` 里那件事由别的门负责，在板上没有别人负责。
    """
    if n_obs <= 1 or not 0.0 < alpha < 1.0:
        return math.inf
    variance = sampling_variance(0.0, n_obs)
    floor = normal_ppf(1.0 - alpha) * math.sqrt(variance)
    return max(max_sharpe_quantile(max(n_on_board, 1), variance, alpha=alpha), floor)


def years_to_decide(claimed_sharpe: float, *, n_on_board: int, alpha: float = 0.05) -> float | None:
    """按今天板上的候选数，一个**声称**这么高年化 Sharpe 的候选要观察多少年才够清门。

    吃的是上板时钉住的 `BoardEntry.claimed_sharpe`，**不是**后来观察到的 Sharpe。用观察值是循环的：
    早期走运的候选会把年限缩短到已经观察到的长度，于是「够久了」其实只是「今天恰好好看」。

    推导只有一步：零假设下年化 Sharpe 的噪声 ≈ 1/√T（T 以年计），所以门 ≈ z(N)/√T，
    解 S = z(N)/√T 得 **T = (z(N)/S)²**。方案里那两个数就是它：单候选 z=2 → 1.8 年；
    30 个候选 z≈2.93 → 3.8 年。

    `None` 表示永远不够——Sharpe 非正时没有 T 能让它过门。

    **与方案里那个数的一处差别，写明而不是让它自己消化掉。** 分析文档写「单候选判到 z=2 约 1.8 年」，
    那个 z=2 是举例用的（约等于单边 97.7%）。本模块按 `alpha` 走：α=0.05 的单边临界值是 1.645，
    S=1.5 时得 **1.2 年**。30 个候选那个数（z≈2.93 → 3.8 年）两边一致，因为它由选择门决定而不由地板决定。
    """
    if claimed_sharpe <= 0.0 or not 0.0 < alpha < 1.0:
        return None
    z = max(max_sharpe_quantile(max(n_on_board, 1), 1.0, alpha=alpha), normal_ppf(1.0 - alpha))
    return float((z / claimed_sharpe) ** 2)


def forward_reading(
    net: pd.Series,
    entry: BoardEntry,
    *,
    bars_per_year: float,
    n_on_board: int,
    alpha: float = 0.05,
    params_now: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """一个板位今天的读数。**永远带上 `verdict` 与 `years_to_decide`，永远不只给一个 Sharpe。**

    只给 Sharpe 的板会被当成排行榜读，而排行榜正是这块东西唯一真正的危险：它让人以为看见了
    可以据以行动的东西，而实际上要等年。
    """
    if params_now is not None:
        reason = tampering(entry, params_now)
        if reason:
            return {
                "candidate": entry.candidate,
                "param_key": entry.param_key,
                "universe": entry.universe,
                "entered_at": entry.entered_at,
                "verdict": TAMPERED,
                "reason": reason,
                "next_step": next_step(verdict=TAMPERED, long_enough=False),
            }

    forward = forward_slice(net.dropna(), entry.entered_at)
    n_obs = int(forward.shape[0])
    values = forward.to_numpy(dtype=float)
    mean = float(np.mean(values)) if n_obs else 0.0
    sd = float(np.std(values, ddof=1)) if n_obs > 1 else 0.0
    sharpe_period = mean / sd if sd > 0 else None
    sharpe_annual = None if sharpe_period is None else sharpe_period * math.sqrt(bars_per_year)
    threshold = board_threshold(n_on_board, n_obs=n_obs, alpha=alpha) if n_obs > 1 else math.inf
    # 年限用**上板时钉住的** `claimed_sharpe`，不用刚算出来的 `sharpe_annual`。后者会让一个
    # 早期走运的候选把自己的年限缩短到已经观察到的长度，于是「够久了」变成「今天恰好好看」。
    # N 用今天的板大小，所以年限会随板变长——那是加板位的价钱，该由每个在板的候选一起付。
    years = years_to_decide(entry.claimed_sharpe, n_on_board=n_on_board, alpha=alpha)
    observed_years = n_obs / bars_per_year if bars_per_year > 0 else 0.0

    passes = sharpe_period is not None and math.isfinite(threshold) and sharpe_period > threshold
    long_enough = years is not None and observed_years >= years
    verdict = PASSES if (passes and long_enough) else OBSERVING
    return {
        "candidate": entry.candidate,
        "param_key": entry.param_key,
        "universe": entry.universe,
        "entered_at": entry.entered_at,
        "bars_forward": n_obs,
        "years_forward": round(observed_years, 4),
        "sharpe_annual": sharpe_annual,
        "threshold_period": threshold if math.isfinite(threshold) else None,
        "threshold_annual": (threshold * math.sqrt(bars_per_year)) if math.isfinite(threshold) else None,
        "n_on_board": n_on_board,
        "claimed_sharpe": entry.claimed_sharpe,
        "years_to_decide": years,
        # 到点了没有，与过门没过门是两件事，分开记：一个候选可以今天就在门上面，而它要到
        # `years_to_decide` 才有足够的观察让那件事不是噪声。
        "long_enough": long_enough,
        "verdict": verdict,
        # 读完之后谁该做什么。挡的不是「把板当排行榜读」（`verdict` 与 `years_to_decide` 已经挡住
        # 了那个），是另一件事：读完没人知道该做什么，于是什么都不做。
        "next_step": next_step(verdict=verdict, long_enough=long_enough),
    }


def board_report(readings: Sequence[Mapping[str, Any]], *, generated_at: str | None = None) -> dict[str, Any]:
    """整块板的读数。`decidable` 是「今天有几条到了可判的年数」，通常是 0，而那是诚实的。"""
    stamp = generated_at or datetime.now(UTC).isoformat(timespec="seconds")
    return {
        "generated_at": stamp,
        "n_on_board": len({(r.get("candidate"), r.get("param_key"), r.get("universe")) for r in readings}),
        "tampered": sum(1 for r in readings if r.get("verdict") == TAMPERED),
        "decidable": sum(1 for r in readings if r.get("long_enough")),
        "passing": sum(1 for r in readings if r.get("verdict") == PASSES),
        "readings": list(readings),
    }
