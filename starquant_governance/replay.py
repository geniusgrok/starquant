"""Phase 0: replay the rules against the record they claim to reproduce, and name every difference.

The rules in `policy` and `lifecycle` were written to describe what a careful operator has been doing
by hand since 2026-09-03.  That claim is testable, and this module is the test: run the rules over
the artefacts that already exist - the adopted registry pointers, the validation and book reports,
the live cycle record - and list every place where the machine would have decided differently.

AC-G0 is not "the rules reproduce history".  They will not, and a rule set that did would be a rule
set fitted to it.  The acceptance is that **every difference has a name**: a declared operator
exception, a rule that did not exist when the artefact was written, or a fact the artefact does not
carry.  An unnamed difference means the rules are doing something nobody decided, which is the exact
failure that makes autonomous promotion unsafe.

Nothing here writes.  No ledger row, no registry, no state file (K-EX07's descriptive-replay ruling
is about research replays that could inform a selection; this one reads decisions already taken and
cannot inform any).
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from starquant_alpha.validation.multiple_testing import SELECTION_GATE
from starquant_governance.lifecycle import Book, Candidate, Event, Facts, State, evaluate
from starquant_governance.policy import Policy

EXCEPTION = "exception"
RULE_VERSION = "rule_version"
EVIDENCE_GAP = "evidence_gap"
UNATTRIBUTED = "unattributed"

# When each instrument started existing.  A rule cannot be applied to an artefact written before the
# field it reads, and calling that a violation would make the replay's output meaningless.  Both dates
# are measured, not remembered: the first `oos_selection` block and the first cycle carrying a
# `construction` fingerprint.
D028_SELECTION_BLOCK = "2026-09-04"
KILLQ3_GATE_NAMED = "2026-09-06"
D026_CONSTRUCTION_DIGEST = "2026-09-04T04:21:22+00:00"


@dataclass(frozen=True)
class ExceptionEntry:
    """An operator ruling the rules deliberately do not encode.

    `why_not_encoded` is the field that earns this table its place.  Anything here could be turned
    into a rule; the entry says why it should not be, and a reader who disagrees has something
    specific to argue with instead of a gap.
    """

    id: str
    date: str
    ruling: str
    rule_conflict: str
    why_not_encoded: str
    covers: tuple[str, ...]  # substrings of the artefacts or reasons this entry accounts for


#: The seven rulings Phase 0 was told to account for, plus what each one costs the rule set.
EXCEPTIONS: tuple[ExceptionEntry, ...] = (
    ExceptionEntry(
        id="D-019",
        date="2026-09-04",
        ruling="flow 空头腿以探针书上线：书级 ACCEPT、信号级 FAIL（DSR p 0.81）、静态 universe 上为零，"
        "操作者仍让它跑——1/3 预算、30 天 P&L 自动止损、定期复审。它是为产出样本外证据的有界实验。",
        rule_conflict="§3 candidate->validated 要求 verdict PASS；flow 的信号级判定不是 PASS。",
        why_not_encoded="把「信号级 FAIL 也能上线」写成规则，等于取消 D-020 的判据。它是一次具名的、"
        "有预算上限和自动止损的例外，代价已由 R3 与 P&L stop 承接；§3 的 Grandfather 条款只记录它的既成状态。",
        covers=("flow-validation", "flow_short"),
    ),
    ExceptionEntry(
        id="D-029",
        date="2026-09-04",
        ruling="探针书可以引用 verdict REJECT 的书级报告，但 registry 必须写明 `probe.accepted_despite: REJECT`。",
        rule_conflict="§3 validated->booked 要求书级六项通过；三份被采纳的 book 报告是 REJECT。",
        why_not_encoded="这条已经**部分成为规则**：`starquant_alpha/registry.py` 强制那句书面承认，"
        "启动闸拒绝没有它的 REJECT 指针。剩下的例外部分是「谁来写那句话」——今天是人，"
        "Phase 2 之后是事务，但承认的内容仍需一次具名裁定，不能由机器自己给自己出具。",
        covers=("book-tsmom-flow", "accepted_despite"),
    ),
    ExceptionEntry(
        id="K-EX07",
        date="2026-09-07",
        ruling="窗口 ≤ 100 bar、不用于选择任何参数的描述性实盘重放不计入 `trials.jsonl`；"
        "条件是报告标 E5 并写明 n，且不得据此改配置。",
        rule_conflict="R1 按窗口计账本行数，R2 按 search_space_version 决定是否允许 mine；"
        "两者都只会计费，没有「不计费」这一档。",
        why_not_encoded="不计费的判据是「有没有用于选择」，那是意图，不是可从 artefact 读出的事实。"
        "机器能读的是 bar 数和是否改了配置；意图必须由人一次性裁定并留痕。",
        covers=("descriptive-replay",),
    ),
    ExceptionEntry(
        id="Q7",
        date="2026-09-08",
        ruling="P20 重跑追加的 514 行账本按 K-EX07 先例回退——同一搜索空间的第二次枚举不再向家族收费。",
        rule_conflict="R2 会**拒绝**这次重跑；历史是先跑了、写了 514 行、再由裁定把行删掉。",
        why_not_encoded="R2 只能防住下一次；它没有、也不该有回溯删除账本行的能力——"
        "账本只追加是 DSR 分母可信的前提。删行是一次带署名的例外，不是一条规则。",
        covers=("mine-shortlist",),
    ),
    ExceptionEntry(
        id="P10-cellB",
        date="2026-09-04",
        ruling="`no_trade_rel_band` 0.25 → 0.40 采纳（OOS Sharpe +0.14、配对 t 4.18），"
        "并预登记一条实盘证伪线「换手应下降约 12%」。",
        rule_conflict="§8 的构造冻结：窗口之间不改 construction_fingerprint。这次改动发生在任何批次窗口之外。",
        why_not_encoded="构造改动的证据是配对回测，不是实盘窗口；把它塞进晋级流水线会让每次参数调整"
        "都消耗一个晋级名额并清零 M-010。方案把它单列为 Phase 4a「批次窗口 #1（构造）」，"
        "与晋级（4b）拆开——即：这条例外的处置是改流程，不是改规则。",
        covers=("no_trade_rel_band",),
    ),
    ExceptionEntry(
        id="P11",
        date="2026-09-04",
        ruling="预登记网格里没有一格带止损的通过 D-017，按预登记应「不启用止损并交回操作者」；"
        "操作者改为加宽网格重跑（P11-b），6σ 在**未经修改的 D-017 规则**下双通过并上线。",
        rule_conflict="R2 会把加宽后的网格当作新的 search_space_version 允许重跑，但没有任何规则"
        "允许在预登记结论已经出来之后改网格——那正是选择性报告的形状。",
        why_not_encoded="「加宽网格」与「换个网格直到过关」在 artefact 上完全同形，区别只在于加宽的理由"
        "是否在看到结果之前就成立。P11-b 把理由写在跑之前，这是人能做而规则读不出的动作。"
        "机器侧的对应控制是 R1 的预算与账本收费，不是禁止。",
        covers=("overlay-2026090",),
    ),
    ExceptionEntry(
        id="P13",
        date="2026-09-04",
        ruling="`vol_target` 0.15 → 0.30；同时把探针 `max_loss` 0.01 → 0.02「按比例调整以保持预登记规则的原意」；"
        "并明确作废 P10 cell B 的实盘证伪线（换手反升 74.8%）。",
        rule_conflict="R10：阈值只在代码里、改动带版本与预登记；机器不得改自己的阈值。"
        "这次一次动了构造、动了一条预登记阈值、作废了一条证伪线。",
        why_not_encoded="按比例保持原意需要知道「原意」，机器只有数值。作废一条证伪线更是如此："
        "它要求判断证伪线的前提是否还成立。两者都必须是人的一次具名裁定；R10 的作用是"
        "让机器不能悄悄做同样的事。",
        covers=("max_loss", "vol_target"),
    ),
)

EXCEPTIONS_BY_ID: dict[str, ExceptionEntry] = {entry.id: entry for entry in EXCEPTIONS}


@dataclass(frozen=True)
class SuspendedCondition:
    """A rule condition this replay could not enforce, because no artefact carries the fact.

    These are not differences - suspending a condition means the replay says nothing about it - and
    they are the most actionable thing Phase 0 produces: a rule that reads a field nothing writes
    cannot run, no matter how well it is argued.  `fix` is what Phase 1 has to build for the
    condition to become enforceable.
    """

    condition: str
    reads: str
    why_unreadable: str
    fix: str


#: Measured against the 201 archived reports and the 153-cycle live record, not assumed.
SUSPENDED: tuple[SuspendedCondition, ...] = (
    SuspendedCondition(
        condition="DL-K3 预登记早于报告",
        reads="Facts.prereg_before_report",
        why_unreadable="早于 DL-G9 的报告不携带预登记指针；那时预登记只记在 RESEARCH_LOG 的散文和 git 提交里。"
        "**DL-G9 已交付**：`research validate --prereg <commit>` 把 commit 与它自己的提交时间写进报告，"
        "此后的报告按 artefact 判定，更早的仍挂起",
        fix="Phase 1 ✔ DL-G9：`--prereg` + 报告的 `preregistration` 块",
    ),
    SuspendedCondition(
        condition="KILL-AR-07 证据构造 ≡ 实盘构造",
        reads="Facts.evidence_construction_matches_live",
        why_unreadable="早于 DL-G9 时两侧没有可比对的东西：`cycles.jsonl` 只存构造 digest 而 digest 不可反解，"
        "报告存 `portfolio`/`exits` 却算不出同一个数。**DL-G9 已交付**：两侧各落一个 "
        "`evidence_construction`（只覆盖 `construction_problems` 比对的那三块），字符串相等即可判定",
        fix="Phase 1 ✔ DL-G9：报告的 `evidence_construction` + 每周期落盘的同名字段 + 每进程一次的 `construction_full`",
    ),
    SuspendedCondition(
        condition="§3 滑点压力 5.5 档",
        reads="Facts.slippage_stress_pass",
        why_unreadable="book 报告不含 `slippage_stress`（validation 报告含）。**已交付**："
        "`research book` 的 `book_limits.slippage_stress` 把 D-018 的三条边际判据在 5.5 bps 上重算一遍并写下 "
        "`pass`；此后的 book 报告按 artefact 判定，早于该块的 6 份仍挂起——那三个数要重跑才能有，"
        "档案里没有任何产物能补算出来",
        fix="Phase 1 ✔：book 报告的 `book_limits.slippage_stress.pass`",
    ),
    SuspendedCondition(
        condition="§3 与在跑的书 corr < 0.5",
        reads="Facts.max_correlation_with_running",
        why_unreadable="`research correlate` 的结果是独立报告，没有任何字段把它链回 book 报告。**已交付**："
        "`book_limits.max_correlation_with_running` 在 book 这一步就对 registry 说在跑的每一本书量一次，"
        "取最大。旧的 6 份只有 `universes[*].correlation.full`（候选对主账本），那是**下界**不是最大值，"
        "拿来当 `< 0.5` 的输入就是 fail-open，所以仍挂起",
        fix="Phase 1 ✔：book 报告的 `book_limits.max_correlation_with_running`",
    ),
    SuspendedCondition(
        condition="§3 换手 ≤ 3x 主账本",
        reads="Facts.turnover_ratio_to_main",
        why_unreadable="同上，没有字段。**已交付**：`book_limits.turnover_ratio_to_main`（候选单独、未按 "
        "fraction 缩放的 `turnover_units` ÷ 主账本的），与 RESEARCH_LOG 历次预登记同一口径。"
        "旧的 6 份**可以补算**——两个 `turnover_units` 都在报告里——但补算要由读的人做，"
        "回放只判 artefact 自己写下的数",
        fix="Phase 1 ✔：book 报告的 `book_limits.turnover_ratio_to_main`",
    ),
    SuspendedCondition(
        condition="M-011 面板平价义务",
        reads="Facts.parity_met",
        why_unreadable="平价义务随 DL-D4 才存在，本期没有任何一列数据受它约束",
        fix="Phase 3：DL-D4 落地后自然可读",
    ),
    SuspendedCondition(
        condition="L4 Canary 浸泡",
        reads="Facts.canary_healthy",
        why_unreadable="Canary 尚不存在",
        fix="Phase 2：DL-G5",
    ),
)


#: Which suspensions an artefact of a given kind can LIFT, so the replay can report "N judged, M still
#: suspended" per condition rather than only counting the blind spots.  A condition absent from this map
#: is one no artefact can decide yet (M-011, L4) and it is only ever counted as suspended.
JUDGEABLE: dict[Event, tuple[str, ...]] = {
    Event.VALIDATE: ("DL-K3 预登记早于报告", "KILL-AR-07 证据构造 ≡ 实盘构造"),
    Event.BOOK: ("§3 滑点压力 5.5 档", "§3 与在跑的书 corr < 0.5", "§3 换手 ≤ 3x 主账本"),
}


@dataclass(frozen=True)
class Difference:
    """One place the machine would have decided differently from the record.

    `attribution` names the cause; `fix` is required when the cause is that an artefact does not
    carry a fact, because "we cannot tell" only counts as attributed if we can say what would make
    it tellable.  Without that rule `evidence_gap` becomes a wastebasket and AC-G0 passes trivially.
    """

    subject: str
    history: str
    rules_say: str
    kind: str
    attribution: str
    fix: str = ""

    @property
    def attributed(self) -> bool:
        if self.kind == UNATTRIBUTED or not self.attribution:
            return False
        return bool(self.fix) if self.kind == EVIDENCE_GAP else True


@dataclass(frozen=True)
class ReplayResult:
    reproduced: tuple[str, ...]
    differences: tuple[Difference, ...]

    @property
    def unattributed(self) -> tuple[Difference, ...]:
        return tuple(d for d in self.differences if not d.attributed)

    @property
    def passes_ac_g0(self) -> bool:
        return not self.unattributed


def _gate_readable(report: Mapping[str, Any]) -> bool:
    """Whether R0 can be applied to this artefact at all.

    A report with no `oos_selection` block, or one whose block cannot name the gate that produced its
    threshold, is not judged by R0 - `starquant_alpha.validation.verdict` takes the same position for the
    same reason.  Keeping the distinction matters most in the direction nobody checks: a candidate the
    operator did NOT adopt, which the rules also refuse, looks like agreement until you notice the
    rule refused on a missing field and the operator refused on the book's marginal contribution.
    """
    selection = report.get("oos_selection") or {}
    return bool(selection) and selection.get("gate") == SELECTION_GATE


def _report_time(report: Mapping[str, Any]) -> str:
    return str(report.get("generated_at") or "")


def _facts_for(
    report: Mapping[str, Any], *, acknowledged: bool, live_constructions: frozenset[str] = frozenset()
) -> tuple[Event, Facts, tuple[str, ...]]:
    """Route a report to the transition it is evidence for, and read only what it actually says.

    A suspended condition is set to its passing value and NAMED in the third return value; that is the
    difference between "the rule held" and "the rule was not applied", and conflating them is how a
    replay ends up reporting its own blind spots as findings.

    DL-G9 turned two of them from permanent blind spots into artefact-age questions.  A report that
    carries `preregistration` and `evidence_construction` is judged on them; one written before those
    fields existed still suspends them, the same way `construction_problems` skips a report with no
    `portfolio` block rather than refusing it.

    `book_limits` does the same for the other three, and they are the ones that had never been read at
    all: three of the four conditions on `validated -> booked` were a literal `True`/`0.0`/`0.0`
    written here, because no book report carried the fields.  A missing or null value still suspends -
    `None` is "nobody measured it", which is exactly what must not be allowed to read as 0.0, since
    0.0 is the PASSING value for both of the numeric limits.
    """
    kind = str(report.get("kind") or "")
    if kind == "book":
        verdict = str(report.get("book_verdict") or "")
        limits = report.get("book_limits")
        limits = limits if isinstance(limits, Mapping) else {}
        suspended_book: list[str] = []
        stress = limits.get("slippage_stress")
        stress_pass = stress.get("pass") if isinstance(stress, Mapping) else None
        if not isinstance(stress_pass, bool):
            stress_pass = True
            suspended_book.append("§3 滑点压力 5.5 档")
        correlation = limits.get("max_correlation_with_running")
        if not isinstance(correlation, (int, float)) or isinstance(correlation, bool):
            correlation = 0.0
            suspended_book.append("§3 与在跑的书 corr < 0.5")
        turnover = limits.get("turnover_ratio_to_main")
        if not isinstance(turnover, (int, float)) or isinstance(turnover, bool):
            turnover = 0.0
            suspended_book.append("§3 换手 ≤ 3x 主账本")
        return (
            Event.BOOK,
            Facts(
                book_checks_pass=verdict == "ACCEPT" or (verdict == "REJECT" and acknowledged),
                slippage_stress_pass=stress_pass,
                max_correlation_with_running=float(correlation),
                turnover_ratio_to_main=float(turnover),
            ),
            tuple(suspended_book),
        )
    selection = report.get("oos_selection") or {}
    wf = report.get("walk_forward") or {}
    oos = wf.get("oos_sharpe")
    threshold = selection.get("threshold_annual")
    gate_pass = (
        selection.get("gate") == SELECTION_GATE
        and isinstance(oos, (int, float))
        and isinstance(threshold, (int, float))
        and oos >= threshold
    )
    suspended: list[str] = []
    prereg = report.get("preregistration")
    committed = _instant(prereg.get("committed_at")) if isinstance(prereg, Mapping) else None
    generated = _instant(report.get("generated_at"))
    if committed is not None and generated is not None:
        prereg_ok = committed < generated
    else:
        prereg_ok = True
        suspended.append("DL-K3 预登记早于报告")
    recorded = report.get("evidence_construction")
    if isinstance(recorded, str) and recorded and live_constructions:
        construction_ok = recorded in live_constructions
    else:
        construction_ok = True
        suspended.append("KILL-AR-07 证据构造 ≡ 实盘构造")
    return (
        Event.VALIDATE,
        Facts(
            verdict_pass=report.get("verdict") == "PASS",
            prereg_before_report=prereg_ok,
            quantile_gate_pass=bool(gate_pass),
            evidence_construction_matches_live=construction_ok,
        ),
        tuple(suspended),
    )


def _instant(value: Any) -> datetime | None:
    """One ISO stamp as an instant, or None when it cannot be read as one.

    DL-K3 used to compare these as STRINGS.  `git` writes `committed_at` with the COMMITTER's local
    offset and a report writes `generated_at` in UTC, so the two are routinely in different zones and
    the comparison was answering a question about text.

    It failed both ways, and the second way is the one that matters.  Measured 2026-09-09 on the
    pointer the live registry cites: prereg `2026-09-09T02:18:34+08:00`, report
    `2026-09-08T18:22:04Z` - the pre-registration is 211 seconds EARLIER and the string compare said
    it was later, so valid evidence was refused.  Turn the offset around and it lets a forgery
    through: a "pre-registration" committed `2026-09-08T20:00:00-05:00` is 30 minutes AFTER a report
    generated `2026-09-09T00:30:00+00:00`, and sorts before it as text.  DL-K3 is the rule that stops
    a result being registered after it is known; a `<` on strings is not that rule.

    Unreadable is None rather than a guess, so the caller suspends the condition instead of deciding
    it - an artefact that cannot answer is not an artefact that answers "no".
    """
    if not isinstance(value, str) or not value:
        return None
    try:
        stamp = datetime.fromisoformat(value)
    except ValueError:
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=UTC)


def _attribute(reason: str, name: str, report: Mapping[str, Any], history: str) -> Difference:
    """Map one refusal to a named cause by inspecting the artefact, never by guessing at a category."""
    selection = report.get("oos_selection") or {}
    if reason.startswith("D-018") and str(report.get("book_verdict")) == "REJECT":
        entry = EXCEPTIONS_BY_ID["D-029"]
        return Difference(
            name,
            history,
            reason,
            EXCEPTION,
            f"{entry.id}（{entry.date}）：探针书可引用 REJECT，"
            "但 registry 必须写明 `probe.accepted_despite: REJECT`；本条指针正是那样写的",
        )
    if reason.startswith("R0"):
        if not selection:
            return Difference(
                name,
                history,
                reason,
                RULE_VERSION,
                f"报告无 `oos_selection` 块：D-028 的门 {D028_SELECTION_BLOCK} 才存在",
            )
        if selection.get("gate") != SELECTION_GATE:
            stored = selection.get("threshold_annual")
            stored_text = f"{stored:.2f}" if isinstance(stored, (int, float)) else "—"
            return Difference(
                name,
                history,
                reason,
                RULE_VERSION,
                f"`oos_selection.gate` 缺失：KILL-Q3 {KILLQ3_GATE_NAMED} 才把门写进 artefact，"
                f"此前存的阈值（{stored_text}）出自 E[max]，比现行门低约 0.32",
            )
    return Difference(name, history, reason, UNATTRIBUTED, "")


def replay_adoptions(
    reports: Mapping[str, Mapping[str, Any]],
    adoptions: Mapping[str, str],
    *,
    acknowledged_rejects: Sequence[str] = (),
    policy: Policy | None = None,
    live_constructions: Sequence[str] = (),
) -> ReplayResult:
    """Replay §3's evidence-side transitions against every registry pointer, in both directions.

    Adopted pointers ask "would the machine have admitted this?".  Reports that PASSED and were never
    adopted ask the more dangerous question - "would the machine have admitted something the operator
    did not?" - which is RISK-G1's shape and the reason the replay does not stop at the adopted set.
    """
    policy = policy or Policy()
    book = Book()
    reproduced: list[str] = []
    differences: list[Difference] = []
    acknowledged = set(acknowledged_rejects)
    live = frozenset(live_constructions)
    suspensions: dict[str, int] = {}
    judged: dict[str, int] = {}

    adopted_names = {path.rsplit("/", 1)[-1] for path in adoptions}
    for path, adopted_on in sorted(adoptions.items(), key=lambda kv: kv[1]):
        name = path.rsplit("/", 1)[-1]
        report = reports.get(path)
        history = f"{adopted_on} 写进 registry"
        if report is None:
            differences.append(
                Difference(
                    name,
                    history,
                    "报告文件不在仓库里",
                    EVIDENCE_GAP,
                    "被引用的 artefact 已不在磁盘上，指针指向一份不可复现的报告",
                    fix="Phase 1：启动闸已按 sha256 比对；补一条「被引用报告必须在仓库里」的检查",
                )
            )
            continue
        event, facts, suspended = _facts_for(report, acknowledged=name in acknowledged, live_constructions=live)
        for condition in suspended:
            suspensions[condition] = suspensions.get(condition, 0) + 1
        for condition in JUDGEABLE.get(event, ()):
            if condition not in suspended:
                judged[condition] = judged.get(condition, 0) + 1
        state = State.CANDIDATE if event is Event.VALIDATE else State.VALIDATED
        decision = evaluate(book, Candidate(id=name, state=state), event, facts, policy)
        if decision.allowed:
            basis = "；凭 registry 的 D-029 书面承认" if name in acknowledged else ""
            reproduced.append(f"{name}：规则同意采纳（{event.value}{basis}）")
            continue
        differences.extend(_attribute(reason, name, report, history) for reason in decision.reasons)

    for condition, count in sorted(judged.items()):
        reproduced.append(
            f"{condition}：{count} 份指针**已可判定**（字段在场）；"
            f"另有 {suspensions.get(condition, 0)} 份早于该字段仍挂起"
        )
    for path, report in sorted(reports.items()):
        name = path.rsplit("/", 1)[-1]
        if name in adopted_names or report.get("kind") != "validation" or report.get("verdict") != "PASS":
            continue
        event, facts, _ = _facts_for(report, acknowledged=False, live_constructions=live)
        decision = evaluate(book, Candidate(id=name), event, facts, policy)
        substantive = [r for r in decision.reasons if not (r.startswith("R0") and not _gate_readable(report))]
        if substantive:
            reproduced.append(f"{name}：PASS 但规则同样不采纳（{substantive[0]}）")
            continue
        differences.append(_why_not_adopted(name, report, reports, adopted_names))
    return ReplayResult(tuple(reproduced), tuple(differences))


#: What has to be identical before two reports count as two arms of ONE measurement.  A pair that
#: differs anywhere here was not run to compare anything; it is two runs that happen to differ by a
#: construction key, and a coincidence must not buy an exemption.
ARM_SETTINGS: tuple[str, ...] = (
    "strategy",
    "range",
    "symbols",
    "interval",
    "universe_mode",
    "min_tenure",
    "execution",
    "folds",
    "min_train",
    "purge",
    "embargo",
    "grid",
)


def _construction_agrees(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    """Equal on every key the two SHARE - `construction_problems`' rule, and for its reason.

    A report predates the keys added after it: the pointer adopted on 2026-09-13 carries no
    `flat_inside_band` because the key did not exist.  Comparing key SETS would mean every new
    construction key silently disqualifies the incumbent from anchoring a pair, which is the
    opposite of what the anchor is for.
    """
    return all(left[key] == right[key] for key in set(left) & set(right))


def paired_construction_arm(
    name: str,
    report: Mapping[str, Any],
    reports: Mapping[str, Mapping[str, Any]],
    adopted_names: set[str],
) -> str:
    """The fifth attribution route (operator's ruling, 2026-09-14): one arm of a paired measurement.

    Returns the attribution sentence, or ``""`` when this report is not such an arm.

    A PASS nobody adopted is normally a question - "the rules would have let this in, why is it not
    in?".  For an arm of a matched pair the question does not arise: **no decision was asked for**.
    The pair measures what one construction knob costs; adopting the knob is a separate act that moves
    the registry pointer.

    Three conditions, and the third is the one that matters.  This route excuses the artefacts of
    whoever proposes it, so it is written to be useless as a blank cheque:

    1. another validation report for the same strategy with **identical run settings** (`ARM_SETTINGS`)
       - a pair is a design, not a coincidence;
    2. their constructions differ in **exactly one** key - one knob, or it is not a measurement of a
       knob but a different book;
    3. **one of the two arms is today's book** - it agrees with the adopted pointer's construction on
       every shared key.  Without this, two novel constructions could be paired with each other and
       both walk; with it, the pair is anchored to what is actually being traded.

    Condition 3 also refuses to run when nothing is adopted yet: an anchor must be a pointer somebody
    else accepted, never one of the two reports asking to be excused.
    """
    strategy = report.get("strategy")
    mine = report.get("portfolio") or {}
    anchors = [
        other.get("portfolio") or {}
        for path, other in reports.items()
        if path.rsplit("/", 1)[-1] in adopted_names and other.get("strategy") == strategy
    ]
    if not (mine and anchors):
        return ""
    for path, other in sorted(reports.items()):
        partner = path.rsplit("/", 1)[-1]
        theirs = other.get("portfolio") or {}
        if partner == name or partner in adopted_names or other.get("kind") != "validation" or not theirs:
            continue
        if any(other.get(key) != report.get(key) for key in ARM_SETTINGS):
            continue
        moved = sorted(key for key in set(mine) | set(theirs) if mine.get(key) != theirs.get(key))
        if len(moved) != 1:
            continue
        if not any(_construction_agrees(arm, anchor) for arm in (mine, theirs) for anchor in anchors):
            continue
        return (
            f"成对的构造对照臂：与 `{partner}` 逐项同跑法、构造只差 `{moved[0]}` 一个键，"
            "且其中一臂就是在位指针的构造——这对报告测的是那个旋钮的代价，"
            "没有人在这里请求过晋级裁定"
        )
    return ""


def _why_not_adopted(
    name: str,
    report: Mapping[str, Any],
    reports: Mapping[str, Mapping[str, Any]],
    adopted_names: set[str],
) -> Difference:
    """A PASS the operator did not adopt.  Four checks, each readable off the artefacts.

    Order is by specificity, and the first version of this function got it wrong in a way worth
    recording: it matched a book report by substring, so every `tsmom-validation-*` matched
    `book-tsmom-flow-*` and was reported as "the rules refuse at the book" beside that book's own
    ACCEPT verdict.  A matcher that can produce a self-contradictory sentence is not a matcher.
    """
    strategy = str(report.get("strategy") or "")
    rules_say = "§3：证据侧无拒绝理由，机器会让它进入 validated"
    when = _report_time(report)

    for other_path, other in sorted(reports.items()):
        if other.get("kind") != "book":
            continue
        if str((other.get("sleeve") or {}).get("strategy") or "") != strategy:
            continue
        verdict = str(other.get("book_verdict"))
        if verdict == "ACCEPT":
            continue
        reasons = ", ".join(str(r) for r in (other.get("reasons") or [])) or "—"
        return Difference(
            name,
            "从未写进 registry",
            rules_say,
            RULE_VERSION,
            f"链条不停在证据侧：`{other_path.rsplit('/', 1)[-1]}` 判 {verdict}（{reasons}），"
            "规则在 validated->booked 同样拒绝——历史与规则一致，只是停在下一步",
        )

    later = sorted(
        p.rsplit("/", 1)[-1]
        for p, r in reports.items()
        if r.get("strategy") == strategy and _report_time(r) > when and p.rsplit("/", 1)[-1] in adopted_names
    )
    if later:
        return Difference(
            name,
            "从未写进 registry",
            rules_say,
            RULE_VERSION,
            f"被同策略的后续指针取代：`{later[0]}` 更晚且被采纳——旧报告不是被拒绝，是被超越",
        )

    capital = float((report.get("impact_model") or {}).get("capital") or 0.0)
    if capital > 0:
        return Difference(
            name,
            "从未写进 registry",
            rules_say,
            RULE_VERSION,
            f"DL-C1 的容量臂：按 {capital:,.0f} USDT 计冲击成本，而本账本约 1.1 万——"
            "被采纳的同策略指针都是 `capital: 0`（尺度无关的平模型）。"
            "它回答的是「9 倍规模下判定还成不成立」，不是「该不该晋级」，与 `universe_mode: static` 同形",
        )

    if report.get("universe_mode") == "static":
        return Difference(
            name,
            "从未写进 registry",
            rules_say,
            RULE_VERSION,
            "`universe_mode: static`：这是配对跑的稳健性臂，不是晋级候选——"
            "被采纳的同策略指针都是 `pit`（或早于 universe_mode 字段）",
        )

    # Fifth and last, deliberately after the four that read off ONE artefact: this one needs a second
    # report to exist, so it must not pre-empt an explanation that stands on its own.
    if arm := paired_construction_arm(name, report, reports, adopted_names):
        return Difference(name, "从未写进 registry", rules_say, RULE_VERSION, arm)

    return Difference(name, "从未写进 registry", rules_say, UNATTRIBUTED, "")


def replay_live(
    cycles: Sequence[Mapping[str, Any]],
    attribution: Sequence[Mapping[str, Any]],
    *,
    policy: Policy | None = None,
    construction_aliases: Mapping[str, str] | None = None,
) -> ReplayResult:
    """The downgrade side, replayed against the live record (§8 Phase 0 item D).

    What this can answer: whether the P&L stop would have fired, whether R5 would have frozen
    promotion, how many cycles produce no decision at all, and how often the construction changed
    against a rule that allows one change per window.  What it cannot answer is whether any of that
    was *right* - the record is five days long and the rules count in months.
    """
    policy = policy or Policy()
    differences: list[Difference] = []
    reproduced: list[str] = []

    no_decision = [c for c in cycles if c.get("phase") in policy.no_decision_phases]
    skipped = [c for c in cycles if c.get("phase") == "SKIPPED"]
    rebaselined = [c for c in cycles if (c.get("external_flows") or {}).get("rebaselined")]
    decided = [c for c in cycles if c.get("phase") not in policy.no_decision_phases and c.get("phase") != "SKIPPED"]
    reproduced.append(
        f"no-decision 正确排除：ERROR {len(no_decision)}、SKIPPED {len(skipped)}、"
        f"重基 {len(rebaselined)}；可判周期 {len(decided)}（KILL-AR-20）"
    )

    stops = [p for c in decided for p in (c.get("probes") or []) if p.get("stop")]
    if not stops:
        reproduced.append("探针 P&L stop 从未触发：R5 连败计数 0，晋级不冻结，与 `stopped_books` 一致")

    # Canonicalise before counting.  `starquant_live.health.CONSTRUCTION_ALIASES` declares digests that
    # differ from an earlier one only in fields with no behavioural effect - `unit_mode` moved the
    # fingerprint without changing a byte of behaviour, and the four `regime_*` did the same.  Counting
    # raw digests reported six construction changes where four happened, which overstates the very
    # thing §8's freeze is about.  The map is passed in rather than imported: governance depends on
    # alpha and shared, never on live, so that live can record the policy digest without a cycle.
    aliases = dict(construction_aliases or {})
    fingerprints: list[tuple[str, str]] = []
    for cycle in decided:
        digest = str(cycle.get("construction") or "")
        if not digest:
            continue
        canonical = aliases.get(digest, digest)
        if not fingerprints or fingerprints[-1][1] != canonical:
            fingerprints.append((str(cycle.get("at")), canonical))
    seen: set[str] = set()
    if fingerprints:
        seen.add(fingerprints[0][1])
    for at, digest in fingerprints[1:]:
        rollback = digest in seen
        seen.add(digest)
        differences.append(
            Difference(
                f"construction {digest[:12]} @ {at}",
                "构造回到一个此前出现过的指纹（回滚）" if rollback else "构造在实盘运行中改变",
                f"§8 构造冻结：窗口之间不改 construction_fingerprint（窗口 = {policy.window_days} 天）",
                EVIDENCE_GAP,
                "记录只存 12 字符 digest，不存构造输入，因此这次改动**改了什么**无法从 artefact 读出，"
                "也就无法归因到某一条具名裁定",
                fix="Phase 1：构造变化时落全量构造（今天只有启动心跳有，且每次启动被覆盖）",
            )
        )
    if len(fingerprints) > 1:
        reproduced.append(
            f"构造改动共 {len(fingerprints) - 1} 次（已按 CONSTRUCTION_ALIASES 归一），"
            f"覆盖 {len(decided)} 个可判周期（≈{len(decided) / 24.0:.1f} 天）"
            f"——规则允许每 {policy.window_days} 天一次"
        )

    losses = sorted({p.get("max_loss") for c in decided for p in (c.get("probes") or []) if p.get("max_loss")})
    if len(losses) > 1:
        entry = EXCEPTIONS_BY_ID["P13"]
        differences.append(
            Difference(
                "probe max_loss",
                f"探针止损阈值在运行中取过 {losses}",
                "R10：阈值只在代码里，改动带版本 + 测试 + 预登记；机器不得改自己的阈值",
                EXCEPTION,
                f"{entry.id}（{entry.date}）：`max_loss` 0.01 -> 0.02 是为保持 D-019 预登记规则的**原意**"
                "（书翻倍则同比例放宽），操作者当场记录。机器没有「原意」可读",
            )
        )

    windows = len(decided) / 24.0 / policy.window_days if decided else 0.0
    reproduced.append(f"probe->main 不可达：记录覆盖约 {windows:.2f} 个窗口，规则要求 {policy.windows_to_main} 个")
    total = sum(float(row.get("total") or 0.0) for row in attribution)
    reproduced.append(f"R8 归因口径可算：{len(attribution)} 行归因合计 {total:+.2f} USDT（不读权益曲线）")
    return ReplayResult(tuple(reproduced), tuple(differences))


def render(adoptions: ReplayResult, live: ReplayResult, *, policy: Policy | None = None) -> str:
    """The Phase 0 artefact: rule conclusions, suspended conditions, exceptions, difference attribution."""
    policy = policy or Policy()
    differences = (*adoptions.differences, *live.differences)
    unattributed = tuple(d for d in differences if not d.attributed)
    lines = [
        "# 治理规则回放（Phase 0）",
        "",
        f"`policy_version={policy.version}` `policy_digest={policy.digest()}` 窗口 {policy.window_days} 天；"
        f"规则复现 {len(adoptions.reproduced) + len(live.reproduced)} 项，差异 {len(differences)} 条，"
        f"未归因 {len(unattributed)} 条。",
        "",
        "## 一、规则复现的部分",
        "",
    ]
    lines += [f"- {item}" for item in (*adoptions.reproduced, *live.reproduced)] or ["- （无）"]
    lines += [
        "",
        "## 二、被挂起的判据（artefact 不含该事实，本次回放不对它下结论）",
        "",
        "| 判据 | 读什么 | 为什么读不到 | 修法 |",
        "| --- | --- | --- | --- |",
    ]
    lines += [f"| {s.condition} | `{s.reads}` | {s.why_unreadable} | {s.fix} |" for s in SUSPENDED]
    lines += ["", "## 三、例外清单（规则刻意不编码的裁定）", ""]
    for entry in EXCEPTIONS:
        lines += [
            f"### {entry.id}（{entry.date}）",
            f"- **裁定**：{entry.ruling}",
            f"- **与规则的冲突**：{entry.rule_conflict}",
            f"- **为什么不写成规则**：{entry.why_not_encoded}",
            "",
        ]
    lines += [
        "## 四、差异归因",
        "",
        "| 对象 | 历史 | 规则说 | 类型 | 归因 | 修法 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for d in differences:
        lines.append(
            f"| {d.subject} | {d.history} | {d.rules_say} | {d.kind} | {d.attribution or '**未归因**'} | {d.fix or '—'} |"
        )
    lines += [
        "",
        f"**AC-G0：未归因项 {len(unattributed)} 条** — " + ("通过" if not unattributed else "不通过，规则第一版不定稿"),
        "",
    ]
    return "\n".join(lines)


def load_jsonl(text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            payload = json.loads(stripped)
        except ValueError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


__all__ = [
    "EXCEPTIONS",
    "EXCEPTIONS_BY_ID",
    "JUDGEABLE",
    "SUSPENDED",
    "Difference",
    "ExceptionEntry",
    "ReplayResult",
    "SuspendedCondition",
    "load_jsonl",
    "render",
    "replay_adoptions",
    "replay_live",
]
