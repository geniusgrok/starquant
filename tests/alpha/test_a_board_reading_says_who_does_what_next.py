"""板的出口契约（Q-SY2 的前置 (a)，2026-09-18）。

K-SY08 的原话：**「板 PASS 只产生一条读数，没有后续契约」**。这是 O-SY2「默认不上」的两个理由
之一——一个没有出口的观察机制是停车场：候选进来、年限到了、没有任何人被要求做任何事，而
`years_to_decide` 还会随着别人上板继续变长。

所以出口与入口一起写死，两个方向：

* **过门**走四步（新预登记 → 前向假设 → probe，**不解除任何 `reopen.yaml` 条件**）。第四步是
  防后门的：不写这一条，板就是绕过重开条件的路。
* **到点没过门**退役，不延期、不换 `claimed_sharpe`。延期是事后把年限改成「再等等看」，
  而那个年限正是上板时钉死 claimed 要防的循环，只是换了个方向。

契约住在 artefact 里（每份读数的 `next_step`），不住在一份分析文档的第 7 节里——三年后读这块板
的人可能不是今天这个人。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from starquant_alpha.validation.forward_board import (
    BOARD_EXIT_CONTRACT,
    BOARD_PASS_CONTRACT,
    OBSERVING,
    PASSES,
    TAMPERED,
    BoardEntry,
    board_param_key,
    board_report,
    forward_reading,
    next_step,
)

BPY = 24 * 365.0


def _entry(*, claimed_sharpe: float = 1.5, entered_at: str = "2026-06-01T00:00:00+00:00") -> BoardEntry:
    params = {"horizon": 168}
    return BoardEntry(
        candidate="tsmom",
        param_key=board_param_key("tsmom", params),
        params=params,
        universe="pit",
        construction_digest="46b8d731530a",
        entered_at=entered_at,
        run_id="board-test",
        claimed_sharpe=claimed_sharpe,
    )


def _net(per_bar: float, *, years: float, start: str = "2026-06-01T00:00:00+00:00") -> pd.Series:
    """常数收益，长到足以越过 `years_to_decide`。常数是故意的：断言不靠随机数。"""
    index = pd.date_range(start, periods=int(years * BPY), freq="h", tz="UTC")
    rng = np.random.default_rng(3)
    # 全常数的序列 sd=0，Sharpe 无定义。加一点噪声，均值仍由 `per_bar` 定。
    return pd.Series(per_bar + rng.normal(0.0, 1e-4, len(index)), index=index, dtype=float)


def test_every_reading_carries_a_next_step_whatever_its_verdict() -> None:
    """三种裁决、四种处境，一句都不能空——空的那一句就是「读完没人知道该做什么」。"""
    for verdict in (PASSES, OBSERVING, TAMPERED):
        for long_enough in (True, False):
            assert next_step(verdict=verdict, long_enough=long_enough).strip()


def test_passing_the_board_gate_buys_a_pre_registration_not_a_verdict() -> None:
    """四步里最要紧的是第四步：板 PASS 不解除 `reopen.yaml`，否则板就是绕过重开条件的后门。"""
    contract = next_step(verdict=PASSES, long_enough=True)

    assert contract == BOARD_PASS_CONTRACT
    assert "这不是裁定" in contract
    assert "预登记" in contract and "probe" in contract
    assert "reopen.yaml" in contract and "不因板 PASS 而解除" in contract
    # 板不豁免那一笔 validate——它买的是「值不值得花这一笔」的证据
    assert "板读数不是那份报告" in contract and "validate" in contract


def test_reaching_the_horizon_without_clearing_it_means_retire_not_extend() -> None:
    """停车场就是这么长出来的：到点了、没过门、然后谁也不动手。"""
    contract = next_step(verdict=OBSERVING, long_enough=True)

    assert contract == BOARD_EXIT_CONTRACT
    assert "retire" in contract and "不延期" in contract
    assert "不换 `claimed_sharpe`" in contract


def test_a_slot_still_inside_its_horizon_is_told_that_today_does_not_count() -> None:
    contract = next_step(verdict=OBSERVING, long_enough=False)

    assert "不构成任何裁定" in contract
    assert "今天恰好好看" in contract


def test_the_contract_travels_in_the_reading_itself_not_in_a_document() -> None:
    """三年后读这块板的人可能不是今天这个人。artefact 要自带出口。"""
    entry = _entry(claimed_sharpe=1.5)
    # 1.5 年前向、板上 1 个 → 门 z=1.645，年限 (1.645/1.5)^2 = 1.20 年，足够到点
    reading = forward_reading(_net(0.0006, years=1.5), entry, bars_per_year=BPY, n_on_board=1, params_now=entry.params)

    assert reading["long_enough"] is True
    assert reading["verdict"] == PASSES, reading
    assert reading["next_step"] == BOARD_PASS_CONTRACT


def test_a_slot_that_ran_out_of_time_without_clearing_is_told_to_retire() -> None:
    entry = _entry(claimed_sharpe=1.5)
    # 同样 1.5 年、同样到点，但前向收益是零：过不了门
    reading = forward_reading(_net(0.0, years=1.5), entry, bars_per_year=BPY, n_on_board=1, params_now=entry.params)

    assert reading["long_enough"] is True
    assert reading["verdict"] == OBSERVING
    assert reading["next_step"] == BOARD_EXIT_CONTRACT


def test_a_tampered_slot_is_told_to_retire_and_re_add_at_its_own_cost() -> None:
    entry = _entry()
    reading = forward_reading(
        _net(0.0006, years=1.5), entry, bars_per_year=BPY, n_on_board=1, params_now={"horizon": 336}
    )

    assert reading["verdict"] == TAMPERED
    assert "再计一笔" in reading["next_step"], "换参数重来不能免费，否则参数就是可调的"


def test_the_board_report_still_counts_the_same_three_things() -> None:
    """加一个字段不该改变板报告的口径——`decidable` 数的仍是到点的，不是好看的。"""
    entry = _entry(claimed_sharpe=1.5)
    passing = forward_reading(_net(0.0006, years=1.5), entry, bars_per_year=BPY, n_on_board=1, params_now=entry.params)
    waiting = forward_reading(_net(0.0006, years=0.2), entry, bars_per_year=BPY, n_on_board=1, params_now=entry.params)
    report = board_report([passing, waiting])

    assert report["passing"] == 1 and report["decidable"] == 1
    assert all("next_step" in reading for reading in report["readings"])
