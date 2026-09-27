"""板读的是这个仓库**真的写出来的**报告，不是我为了写测试编的那种形状。

2026-09-17 第一次拿在架的 tsmom 证据上板，`claimed_sharpe_from` 读出 `None`。原因不是报告坏了，
是 `CLAIMED_SHARPE_PATHS` 照一份**手写 fixture** 的形状写成了 `oos.annualized_sharpe`——而这个仓库的
`validate` 根本不产生那个键，它写的是 `walk_forward.oos_sharpe`。原来那批测试全都用自己编的
payload，所以它们从头到尾一致地测了一个不存在的契约。

所以这个文件不造数据：它扫 `reports/research/` 里真正的归档报告。报告形状再变，这里就是红的，
而不是安静地读不到一个数然后拒绝上板（或者更糟，读到 0.0 当成「这个候选没希望」）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from starquant_alpha.validation.forward_board import claimed_sharpe_from, full_sample_tail, years_to_decide

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "reports" / "research"

#: 在架 tsmom 的证据指针（`config/alpha_registry.yaml` 的 `evidence.report`）。
SHIPPED = REPORTS / "tsmom-validation-20260913T182325Z.json"


def _validations() -> list[Path]:
    return sorted(REPORTS.rglob("*-validation-*.json"))


def test_there_are_archived_validation_reports_to_read() -> None:
    """这个文件的全部价值在于它读的是真东西。归档空了，下面每一条都变成空转。"""
    assert _validations(), "reports/research 下一份 validation 报告都没有——本文件已无意义"


def test_the_shipped_pointer_is_readable_at_all() -> None:
    """在架那份读不出来，板就连第一个候选都上不了——这正是 2026-09-17 发生的事。"""
    assert SHIPPED.exists(), "在架证据报告不在了，重新指一份"
    value, where = claimed_sharpe_from(json.loads(SHIPPED.read_text(encoding="utf-8")))
    assert value is not None, "读不出在架证据的 Sharpe：板的第一个候选就上不去"
    assert where == "walk_forward.oos_sharpe", f"读到的是 {where}，不是 walk-forward 的样本外"
    assert value == pytest.approx(1.5919, abs=1e-3)


@pytest.mark.parametrize("path", _validations(), ids=lambda p: p.name)
def test_every_archived_validation_report_yields_a_number(path: Path) -> None:
    """不是只有在架那份读得出。一份读不出的报告 = 一个上不了板的候选。"""
    value, where = claimed_sharpe_from(json.loads(path.read_text(encoding="utf-8")))
    assert value is not None, f"{path.name} 读不出年化 Sharpe（键：{sorted(json.loads(path.read_text()))[:8]}…）"
    assert where, "读到了值却说不出它从哪来"


def test_out_of_sample_wins_over_full_sample() -> None:
    """顺序是契约：`validate` 的报告里全样本 Sharpe 更高，而板要钉的是样本外那个。"""
    payload = json.loads(SHIPPED.read_text(encoding="utf-8"))
    oos, _ = claimed_sharpe_from(payload)
    full = (payload.get("full_sample") or {}).get("annualized_sharpe")
    assert full is not None and full > oos, "这份报告的全样本没有比样本外高，换一份来测这条顺序"


# ---- D-043：一条全样本尾巴不许安静地变成 claimed_sharpe -----------------------------------


def test_the_shipped_pointer_is_a_full_sample_tail_and_says_so() -> None:
    """在架 tsmom 的「样本外」是全样本尾巴——D-043 因此给它封顶 WEAK_PASS。

    这条不是在批评那份报告，是在证明**板看得见**这件事。看不见就会拿 1.5919 当基准算年限。
    """
    assert full_sample_tail(json.loads(SHIPPED.read_text(encoding="utf-8"))) is True


def test_an_optimistic_claim_shortens_the_horizon_which_is_the_wrong_direction() -> None:
    """为什么要管尾巴：声称越高，年限越短，板就判得越早。

    在架的尾巴 1.5919 对真选择网格下的样本外 1.27（RESEARCH_LOG 2026-09-17，E-AM22）——
    差的不是一点点年限，而误差的方向是「太早判」，不是「太晚判」。
    """
    optimistic = years_to_decide(1.5919, n_on_board=1)
    honest = years_to_decide(1.2757, n_on_board=1)
    assert optimistic is not None and honest is not None
    assert optimistic < honest, "乐观的声称没有缩短年限？那这道守卫就没有理由存在"
    assert honest - optimistic > 0.2, f"差距只有 {honest - optimistic:.3f} 年，小到不值得设这道门"


def test_a_report_without_the_field_is_not_treated_as_a_tail() -> None:
    """旧报告没有这个字段。没有 ≠ 是尾巴——那会把一批本来能上板的候选全挡在外面。"""
    assert full_sample_tail({"walk_forward": {}}) is False
    assert full_sample_tail({}) is False
