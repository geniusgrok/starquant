"""默认值与 profile 不一致时，要失败，而不是安静地等人读错（2026-09-14）。

**这条是被一次真实的误读换来的。** 2026-09-14 的一次外部体检把
`RiskBudgetParams.vol_band` 读成 `(0.26, 0.38)`，据此断言「这条带没有随 `vol_target` 0.30 → 0.60
重标，一冻结满 10 天打开 `realised_vol` 就是假警报」。**那是错的**：`config/live.demo.yaml` 的
`risk_budget:` 块当天已经把它重标成 `[0.52, 0.76]`（"scaled x2 ... keeps exactly its old relative
width"），而 `starquant report daily` 走的正是 `RiskBudgetParams.from_mapping(payload["risk_budget"])`
（`starquant_cli/live_cmd.py:833`）。误读的来源不是缺证据，是 dataclass 默认值落在了 profile 后面：
同一个类里紧挨着的四个档位常数当天被重标了，`vol_band` 没有。

一个落后于 profile 的默认值不改变任何在役读数（唯一消费 `vol_band` 的 `realised_vol` 只在
daily 报告那条路上被调用，而那条路带 profile），所以它不会失败——它只会让下一个读代码的人得出
和那次体检一样的结论。**这个测试就是那个失败。**

不对整个 `risk_budget:` 块做全等断言：profile 可以合法地携带代码没有默认值的键。
只钉「两边都声明了的键必须相等」。
"""

from __future__ import annotations

from pathlib import Path

from starquant_live.config import load_profile
from starquant_live.risk_budget import RiskBudgetParams

ROOT = Path(__file__).resolve().parents[2]


def _shipped_block() -> dict[str, object]:
    return dict(load_profile(str(ROOT / "config" / "live.demo.yaml")).get("risk_budget", {}) or {})


def test_every_key_the_profile_and_the_default_both_declare_agrees() -> None:
    block = _shipped_block()
    default = RiskBudgetParams()
    from_profile = RiskBudgetParams.from_mapping(block)
    differing = {
        key: (getattr(default, key), getattr(from_profile, key))
        for key in RiskBudgetParams.__dataclass_fields__
        if key in block and getattr(default, key) != getattr(from_profile, key)
    }
    assert not differing, (
        f"这些键的 dataclass 默认值落在了 config/live.demo.yaml 的 risk_budget: 后面 "
        f"{differing}（左=默认，右=profile）。profile 是权威，但落后的默认值会让读代码的人读错——"
        "2026-09-14 就发生过一次。把默认值改成 profile 的值，或者说明为什么两者应当不同。"
    )


def test_the_band_moves_with_the_vol_target_it_was_derived_against() -> None:
    """带是绝对值、不随 `vol_target` 缩放（`risk_budget.py` 直接拿年化实现波动比 low/high），

    所以它必须跟着 target 走，否则 M-002 按构造每个周期都报 outside。钉住这个比例关系而不是钉数字：
    数字会随下一次 k 的裁定再动，比例是那条被转写的规则（"keeps exactly its old relative width"）。
    """
    payload = load_profile(str(ROOT / "config" / "live.demo.yaml"))
    target = float((payload.get("portfolio", {}) or {})["vol_target"])
    low, high = RiskBudgetParams.from_mapping(_shipped_block()).vol_band
    assert low < target < high, f"vol_band {(low, high)} 不含 vol_target {target}"
    # k=0.30 的那一对是 (0.26, 0.38)，即 target 的 0.8667x / 1.2667x。
    assert abs(low / target - 0.26 / 0.30) < 1e-9
    assert abs(high / target - 0.38 / 0.30) < 1e-9
