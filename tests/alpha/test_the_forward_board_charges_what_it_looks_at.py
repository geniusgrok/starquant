"""前向板的四条不变式，每条都对应一个已写下的失败模式。

操作者 2026-09-17 裁定 Q-C = 建。方案（`docs/analysis/2026-09-17-alpha-module-deep-analysis.md`
C-AM08 / O-5 / RISK-AM03 / FM-AM4）把这块东西的价钱和危险都写过了，这个文件是把那些话变成会执行的
检查：一块只给 Sharpe 的板会被当排行榜读，而排行榜正是它唯一真正的危险。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from starquant_alpha.validation.forward_board import (
    FORWARD_BOARD_STRATEGY,
    OBSERVING,
    TAMPERED,
    BoardEntry,
    Retirement,
    board_param_key,
    board_report,
    board_threshold,
    census,
    forward_reading,
    forward_slice,
    live_entries,
    read_board,
    tampering,
    years_to_decide,
)
from starquant_alpha.validation.ledger import TrialRecord, ledger_scope, parse_ledger, unique_trials

BPY = 24 * 365.0


def _entry(
    candidate: str = "tsmom",
    params: dict | None = None,
    entered_at: str = "2026-06-01T00:00:00+00:00",
    claimed_sharpe: float = 1.5,
) -> BoardEntry:
    params = params or {"horizon": 168}
    return BoardEntry(
        candidate=candidate,
        param_key=board_param_key(candidate, params),
        params=params,
        universe="pit",
        construction_digest="46b8d731530a",
        entered_at=entered_at,
        run_id="board-test",
        claimed_sharpe=claimed_sharpe,
    )


def _net(*, before: float, after: float, split: str = "2026-06-01T00:00:00+00:00") -> pd.Series:
    """一段收益：上板之前每根 `before`，之后每根 `after`。故意做成常数，好让断言不靠随机数。"""
    index = pd.date_range("2026-01-01", periods=24 * 300, freq="h", tz="UTC")
    values = np.where(index >= pd.Timestamp(split), after, before)
    return pd.Series(values, index=index, dtype=float)


# ---- 一、前向就是前向 -------------------------------------------------------------------


def test_the_run_before_it_went_on_the_board_earns_nothing() -> None:
    """上板之前那段漂亮的收益，一分都不算——它正是「这个候选值得上板」所用掉的那部分样本。"""
    entry = _entry()
    net = _net(before=0.01, after=0.0)  # 上板前一路涨，上板后完全平
    reading = forward_reading(net, entry, bars_per_year=BPY, n_on_board=1, params_now=entry.params)
    assert reading["sharpe_annual"] is None, "上板后是常数 0，没有波动就没有 Sharpe——前一段没有漏进来"
    assert reading["bars_forward"] < len(net), "前向窗口必须比全样本短"


def test_the_forward_window_starts_at_the_entry_bar_inclusive() -> None:
    entry = _entry(entered_at="2026-06-01T00:00:00+00:00")
    net = _net(before=-0.01, after=0.01)
    forward = forward_slice(net, entry.entered_at)
    assert forward.index[0] == pd.Timestamp("2026-06-01T00:00:00+00:00")
    assert (forward > 0).all(), "切片里不该有任何上板前的 bar"


def test_a_naive_timestamp_does_not_silently_drop_everything() -> None:
    """无时区的索引要被当 UTC 读，而不是与带时区的边界比较时抛错或全空。"""
    index = pd.date_range("2026-01-01", periods=100, freq="h")  # 无 tz
    net = pd.Series(1.0, index=index)
    assert len(forward_slice(net, "2026-01-03T00:00:00+00:00")) > 0


# ---- 二、板越大，每个候选越难过门 -------------------------------------------------------


@pytest.mark.parametrize("n", [1, 2, 5, 30, 100])
def test_the_gate_never_falls_as_the_board_grows(n: int) -> None:
    """多看一个候选是在抬高**所有**候选的门，包括已经看了两年的那个。

    这与 D-028「搜得越多越退休自己的 incumbent」是同一条性质换到前向上。它是加板位的价钱，
    所以必须是一条会执行的检查而不是一句话。
    """
    assert board_threshold(n, n_obs=8760) >= board_threshold(1, n_obs=8760)
    if n > 1:
        assert board_threshold(n, n_obs=8760) > board_threshold(n - 1, n_obs=8760) or n == 1


def test_one_candidate_still_has_to_clear_something() -> None:
    """D-028 的选择门在 N=1 时按约定是 0；板不能照抄那个约定。

    在 `validate` 里显著性由别的门负责，在板上没有别人负责——一块 N=1 时门为 0 的板，
    第一个候选只要 Sharpe 为正就「过」了。
    """
    assert board_threshold(1, n_obs=8760) > 0.0


def test_the_thirty_candidate_horizon_matches_what_the_analysis_priced() -> None:
    """方案里「30 个候选约 3.8 年」是这块东西被批准时的价钱，实现必须还是那个数。"""
    assert years_to_decide(1.5, n_on_board=30) == pytest.approx(3.8, abs=0.1)


def test_a_losing_candidate_has_no_horizon_at_all() -> None:
    assert years_to_decide(-0.2, n_on_board=5) is None
    assert years_to_decide(0.0, n_on_board=5) is None


def test_a_lucky_start_does_not_shorten_its_own_horizon() -> None:
    """判定年限由上板时钉住的 `claimed_sharpe` 决定，不由观察到的表现决定。

    这是最容易写错、写错了最不容易发现的一处：用观察值算年限，一个早期走运的候选会把年限缩短到
    它已经观察到的长度，于是每一个走运的候选都「刚好够久了」。板就成了它本来要防的那个东西。
    """
    entry = _entry(claimed_sharpe=1.5)
    index = pd.date_range("2026-01-01", periods=24 * 300, freq="h", tz="UTC")
    lucky = pd.Series(np.full(len(index), 0.003), index=index)  # 上板后一路稳赚，Sharpe 极高
    lucky = lucky + pd.Series(np.random.default_rng(1).normal(0, 1e-5, len(index)), index=index)
    reading = forward_reading(lucky, entry, bars_per_year=BPY, n_on_board=1, params_now=entry.params)

    assert reading["sharpe_annual"] > 100, "这段收益确实好看——测试的前提成立"
    assert reading["years_to_decide"] == pytest.approx(years_to_decide(1.5, n_on_board=1)), (
        "年限跟着观察值走了：走运的候选正在自己缩短自己的判定期"
    )
    assert reading["long_enough"] is False, "才看了不到半年，再好看也不够久"
    assert reading["verdict"] == OBSERVING


def test_growing_the_board_can_push_a_candidate_back_out_of_decidability() -> None:
    """加一个板位，是让**已经在板上的**候选也要再等——这是多重检验的代价，该看得见。"""
    entry = _entry(claimed_sharpe=1.5)
    small = years_to_decide(entry.claimed_sharpe, n_on_board=2)
    large = years_to_decide(entry.claimed_sharpe, n_on_board=40)
    assert large > small, "板变大而年限没变长，说明多重检验的代价没有被收取"


# ---- 三、板上的候选不许被换参数 ---------------------------------------------------------


def test_changed_params_void_the_slot_instead_of_reading_it() -> None:
    entry = _entry(params={"horizon": 168})
    reading = forward_reading(
        _net(before=0.0, after=0.001), entry, bars_per_year=BPY, n_on_board=1, params_now={"horizon": 336}
    )
    assert reading["verdict"] == TAMPERED
    assert "sharpe_annual" not in reading, "作废的板位不该顺带给出一个读数"


def test_a_json_round_trip_is_not_tampering() -> None:
    """`168` 经 YAML/JSON 往返可能变 `168.0`。误报会作废一个再也补不回来的板位。"""
    entry = _entry(params={"horizon": 168, "scale": 2.0})
    assert tampering(entry, {"horizon": 168.0, "scale": 2}) == ""


def test_a_string_is_still_a_different_candidate() -> None:
    """归一只处理整值浮点。`"168"` 与 `168` 是不同的输入，不该被抹平。"""
    entry = _entry(params={"horizon": 168})
    assert tampering(entry, {"horizon": "168"}) != ""


# ---- 四、上板即计费，计到独立桶，不进任何 family gate --------------------------------------


def test_the_bucket_is_never_pulled_into_a_real_strategys_denominator() -> None:
    """RISK-AM03 的正面形式：板的计费与 family gate 的分母之间没有通路。"""
    for strategy in ("tsmom", "meanrev", "mined_594a12f9307a15d9", "pairs", "flow"):
        assert FORWARD_BOARD_STRATEGY not in ledger_scope(strategy), f"{strategy} 的分母里混进了板的计费"
    assert ledger_scope(FORWARD_BOARD_STRATEGY) == (FORWARD_BOARD_STRATEGY,)


def test_putting_a_tsmom_candidate_on_the_board_does_not_move_tsmoms_gate() -> None:
    """这是 C-AM08 那条 falsifier 的可执行形式：上板要花钱，但花的不是在位者的名额。"""
    prior = [
        TrialRecord(
            strategy="tsmom",
            param_key="h=168",
            sharpe_annual=1.5,
            bars_per_year=BPY,
            recorded_at="2026-09-01T00:00:00+00:00",
            range_start="2026-01-01",
            range_end="2026-09-01",
            symbols=17,
            run_id="r1",
        )
    ]
    board_charge = [
        TrialRecord(
            strategy=FORWARD_BOARD_STRATEGY,
            param_key="tsmom|h=168",
            sharpe_annual=None,
            bars_per_year=BPY,
            recorded_at="2026-09-17T00:00:00+00:00",
            range_start="2026-09-17",
            range_end="2026-09-17",
            symbols=17,
            run_id="board-1",
        )
    ]
    lines = [record.to_json() for record in (*prior, *board_charge)]

    before = unique_trials(parse_ledger([prior[0].to_json()], ledger_scope("tsmom")), range_end_granularity_days=7)
    after = unique_trials(parse_ledger(lines, ledger_scope("tsmom")), range_end_granularity_days=7)
    assert len(after) == len(before) == 1, "板的那一行进了 tsmom 的分母"

    on_board = parse_ledger(lines, ledger_scope(FORWARD_BOARD_STRATEGY))
    assert len(on_board) == 1, "板自己的桶里必须真有那一行——不计费的板就是免费窥视通道"


# ---- 读数本身的形状 ---------------------------------------------------------------------


def test_a_reading_never_comes_without_its_horizon() -> None:
    """只给 Sharpe 的板会被当排行榜读。每一份读数都要自带「还要看多久」。"""
    entry = _entry()
    rng = np.random.default_rng(11)
    index = pd.date_range("2026-01-01", periods=24 * 300, freq="h", tz="UTC")
    net = pd.Series(rng.normal(0.0003, 0.01, len(index)), index=index)
    reading = forward_reading(net, entry, bars_per_year=BPY, n_on_board=12, params_now=entry.params)
    for field in ("verdict", "years_to_decide", "years_forward", "n_on_board", "threshold_annual"):
        assert field in reading, f"读数缺 {field}"
    assert reading["verdict"] == OBSERVING, "才看了几个月，不该给出任何裁定"
    assert reading["long_enough"] is False


def test_the_board_report_counts_what_is_decidable_not_what_looks_good() -> None:
    entry = _entry()
    rng = np.random.default_rng(3)
    index = pd.date_range("2026-01-01", periods=24 * 300, freq="h", tz="UTC")
    net = pd.Series(rng.normal(0.0005, 0.01, len(index)), index=index)
    readings = [forward_reading(net, entry, bars_per_year=BPY, n_on_board=1, params_now=entry.params)]
    report = board_report(readings, generated_at="2026-09-17T00:00:00+00:00")
    assert report["decidable"] == 0, "不到年数就是 0，而 0 是诚实的读数"
    assert report["passing"] == 0
    assert report["n_on_board"] == 1


# ---- 板文件本身 -------------------------------------------------------------------------


def test_the_board_survives_a_broken_line() -> None:
    """append-only 的记录，一行坏掉不该让整块读不出来。"""
    good = _entry().to_json()
    assert len(read_board([good, "{ not json", "", good])) == 2


def test_the_same_candidate_twice_is_one_slot() -> None:
    entry = _entry()
    assert census([entry, _entry()]) == 1
    assert census([entry, _entry(params={"horizon": 336})]) == 2


# ---- 退役：能更正一个钉错的板位，但不能靠它降低别人的门 ------------------------------------


def _retire(entry: BoardEntry, reason: str = "claimed 钉错了") -> Retirement:
    return Retirement(
        candidate=entry.candidate,
        param_key=entry.param_key,
        universe=entry.universe,
        construction_digest=entry.construction_digest,
        retired_at="2026-09-17T22:00:00+00:00",
        reason=reason,
    )


def test_retiring_takes_a_slot_out_of_the_report() -> None:
    entry = _entry()
    lines = [entry.to_json(), _retire(entry).to_json()]
    assert live_entries(lines) == []


def test_retiring_does_not_lower_the_gate_for_anyone_else() -> None:
    """这是这套机制唯一真正危险的地方：退掉表现差的板位来降低别人的门。

    `census` 数的是**曾经**上过板的，所以退役对门的 N 一点作用都没有。
    """
    a, b = _entry(candidate="tsmom"), _entry(candidate="meanrev")
    lines = [a.to_json(), b.to_json(), _retire(b).to_json()]
    assert len(live_entries(lines)) == 1, "退役的没被撤出报告"
    assert census(read_board(lines)) == 2, "退役把门的 N 降下来了——那是这套机制的后门"
    assert board_threshold(2, n_obs=8760) > board_threshold(1, n_obs=8760), "前提：N 更大门更高"


def test_a_slot_re_added_after_retirement_is_live_again() -> None:
    """**按文件顺序折叠，不是按身份相减。** 第一版就错在这里。

    退役与重上的板位身份完全相同（同参数、同 universe、同构造），按身份相减会把重上的那个也一起
    减掉，板读成空的——2026-09-17 更正 tsmom 的 claimed 时正是这样，板显示「全部已退役」。
    位置是有意义的：一条退役只作用于它**之前**的那个条目。
    """
    old = _entry(claimed_sharpe=1.5919)
    new = _entry(claimed_sharpe=1.2757)
    lines = [old.to_json(), _retire(old).to_json(), new.to_json()]
    live = live_entries(lines)
    assert len(live) == 1, "重上的板位被退役记录误伤了"
    assert live[0].claimed_sharpe == pytest.approx(1.2757), "读到的还是旧的那个声称值"


def test_re_adding_does_not_raise_the_gate_because_it_is_the_same_hypothesis() -> None:
    """重新钉一次声称值不是一个新候选，所以它不抬门。计一笔是审计痕迹，与 N 是两件事。"""
    old = _entry(claimed_sharpe=1.5919)
    new = _entry(claimed_sharpe=1.2757)
    assert census(read_board([old.to_json(), _retire(old).to_json(), new.to_json()])) == 1


def test_a_retirement_for_something_never_on_the_board_is_ignored() -> None:
    assert len(live_entries([_entry().to_json(), _retire(_entry(candidate="xsmom")).to_json()])) == 1


def test_a_correction_lengthens_the_horizon_which_is_the_point() -> None:
    """更正的方向：从尾巴 1.5919 换成真选择网格的 1.2757，年限 1.07 -> 1.66 年。"""
    assert years_to_decide(1.5919, n_on_board=1) == pytest.approx(1.07, abs=0.02)
    assert years_to_decide(1.2757, n_on_board=1) == pytest.approx(1.66, abs=0.02)
