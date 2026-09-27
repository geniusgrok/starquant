"""操作者裁定 2026-09-14：构造冻结到 2026-10-13，因为留出不是靠等变大的，是靠不动。

**为什么需要一条会执行的检查，而不是一句话。** `starquant_governance/policy.py` 的 0.3.1 已经把这条
写死过一次：「A "just this once" with no executing check is a promise, which is precisely the category
the 2026-09-09 audit spent a day separating from controls.」冻结构造是同一形状——它不改任何阈值、
不改任何权重，它要求的恰恰是**什么都不做**，而"什么都不做"没有任何既有测试会注意到它被违反。

**冻结买的是什么，以及不是什么**（`docs/analysis/2026-09-14-backtest-expert-evaluation.md` O-4）：

* **不是统计功效。** `SE(Sharpe) ≈ √((1+S²/2)/T)`，S=1.5919：冻 30 天 t=0.30，冻一年 t=1.06，
  要 t=2 得连续不动 **3.58 年**。任何现实的冻结长度都判不了 Sharpe，说它"攒样本外证据"是数量级错误。
* **是三个正被构造抖动关掉的监控。** 2026-09-03 起的 11.25 个 armed 日里 `construction` 换了
  **10 次**，最长一段 4.7 天。直接后果是 `risk_budget.realised_vol` 拒绝出数，理由逐字是
  「窗口内有 N 个构造」——它需要 30 天窗口内只有一个构造，外加 `min_vol_bars` 240 根（10 天）。
  `starquant live soak` 的 L3 要 7 天无 ERROR 相决定；M-010 的 30 天收入归因窗口自
  2026-09-17T16:07:34Z（重启 #53）重新起算，满期是 10-17T16:07。`FREEZE_ENDS` 比它早约四天，
  那是 2026-09-23 的裁定，理由与代价写在那个常量上面。

**为什么住在测试里而不是 `Policy`。** `test_policy_is_the_only_place_a_threshold_lives` 管的是
**机器据以晋级/降级的治理阈值**；这条不是——没有任何自动流程读它，它是一条人的承诺。放进 `Policy`
还要动 `POLICY_VERSION` 和被钉死的 `policy_digest()`，而那是给规则变更用的版本号，不是给承诺用的。

**方向与先例相反，这是有意的。** `test_the_single_window_mine_opening_is_returned` 在窗口内通过、
到期后失败，逼人把开的口收回去。这一条相反：**冻结期内构造一变就红，到期后自动变惰**——
冻结结束不需要任何人来清理它。
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from starquant_live.composition import load_registry
from starquant_live.config import live_config, load_profile
from starquant_live.construction import canonical_construction
from starquant_live.engine import construction_fingerprint

ROOT = Path(__file__).resolve().parents[2]

#: 冻结到期。**2026-09-23 操作者裁定：按 10-13。** 取 00:00Z，与 `deploy/run_live.sh` 的
#: `BRIDGE_UNTIL`、`governance/reopen.yaml` 里那几条 `date_after` 同一个日界。此前那两处写 10-13、
#: 只有这里写 10-17T16:07：09-17 那次后移（下面原文）没有传到另外两处。
#:
#: 代价写在这里：现行构造 09-17T16:07:34Z 起跑，M-010 满 30 天是 10-17T16:07，这个到期日比它早约
#: 四天。10-13 当天就改构造的话，这套构造拿不到完整 30 天的 M-010 读数。K-EX14 不受影响：它的钟
#: 在 `starquant_governance/admission.py` 里按实盘记录现算，机器经 `governance apply` 的写入仍要等到那时。
#:
#: 以下是 09-17 那次后移的原文，保留。
#:
#: **2026-09-17 操作者重新裁定**：上一轮钉的是 2026-10-13T19:00Z，对应自
#: 2026-09-13T19:00:25Z 起算的 M-010 窗口；D1+D2+D3 把三个时钟一起清零，窗口从这次重启重新起算，
#: 所以到期日同步后移。
#:
#: **已回填（重启 #53，2026-09-17T16:07:34Z）。** PR #53 合入时这里写的是上界 10-18T00:00Z，理由是
#: 重启时刻在那个提交写下时还不存在，宁可多冻几个小时也不钉一个还没发生的时刻。它现在发生了：
#: `state.json` 的 `restarted_at` 是 16:07:34Z，+30 天取整到分钟就是下面这个值，比精确的 +30 天早
#: 34 秒——与上一轮 19:00:00 对 19:00:25Z 的写法同一个惯例。可观测事实记在 `docs/RESEARCH_LOG.md`
#: 同日那节。
FREEZE_ENDS = "2026-10-13T00:00:00+00:00"

#: 2026-09-17 起 armed 循环持有的那套构造：D1 `exempt_crossings`、D2 `flat_inside_band`、
#: D3 `band_entry_multiple: 2.0` 同时打开，payload v9。**这不是 `46b8d731530a` 的别名**，它是另一
#: 本账——`starquant_live/construction.py` 的 v9 那段写明了为什么这一次没有别名。
#:
#: 上一轮钉的 `46b8d731530a2f2375f816a1de69e4c357e41a682816c4d947832617550d2a10` 不再是 shipped 的那
#: 套，但它仍然是 `tests/live/test_construction_identity.py` 的 `FROZEN`：历史不重写，那套构造确实
#: 被冻过，AFTER_V7 与 AFTER_TRAILING_ACTIVATE 仍然解析到它。
FROZEN_CONSTRUCTION = "0c555e1c837e342a8af1edca0089b12461a9bdbe3b9a0f122142c63d6ba54bd7"


def _shipped_construction() -> str:
    payload = load_profile(str(ROOT / "config" / "live.demo.yaml"))
    registry = load_registry(str(ROOT / payload.get("registry", "config/alpha_registry.yaml")))
    config = live_config(payload, list(registry.universe), registry, dry_run=True)
    return canonical_construction(construction_fingerprint(config)["digest"])


def test_the_construction_is_frozen_until_the_holdout_matures() -> None:
    if datetime.now(UTC) >= datetime.fromisoformat(FREEZE_ENDS):
        return  # 冻结已到期，这条检查自动变惰，不需要任何人来收拾
    assert _shipped_construction() == FROZEN_CONSTRUCTION, (
        f"构造在冻结期内变了。操作者 2026-09-23 裁定冻结到 {FREEZE_ENDS}，理由与 09-14 那次相同："
        "M-010 的 30 天窗口、`realised_vol` 的单构造条件与 L3 的 7 天条件都要求构造不动。"
        "改构造会把这三个时钟一起清零。要么把改动撤回，要么由操作者重新裁定冻结期并在同一个提交里"
        "更新 FROZEN_CONSTRUCTION 与 FREEZE_ENDS——后者是一次裁定，不是让测试变绿的手段。"
    )


def test_the_universe_list_is_not_what_this_pins() -> None:
    """名单不在指纹里（在里面的是 `min_history_bars`），所以池子重排不会触发上面那条。

    证明放在这里而不是注释里：这条冻结如果连每日重排都拦，它一天就会被绕过去。
    """
    payload = load_profile(str(ROOT / "config" / "live.demo.yaml"))
    registry = load_registry(str(ROOT / payload.get("registry", "config/alpha_registry.yaml")))
    full = live_config(payload, list(registry.universe), registry, dry_run=True)
    single = live_config(payload, ["BTCUSDT"], registry, dry_run=True)
    assert construction_fingerprint(full)["digest"] == construction_fingerprint(single)["digest"]


def test_the_frozen_digest_is_the_one_the_live_loop_recorded() -> None:
    """钉的是循环真正持有过的那套，不是从配置里推出来的一个数。

    读 `cycles.jsonl` 而不是 `state.json`：后者是循环此刻持有的那套，前者是它逐周期写下的记录。
    本机没有实盘记录时跳过——CI 上没有 `.starquant/live`。
    """
    import json

    path = ROOT / ".starquant" / "live" / "cycles.jsonl"
    if not path.exists():
        return
    seen = {
        str(row.get("construction"))
        for row in (json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
        if row.get("construction") and not row.get("dry_run")
    }
    assert FROZEN_CONSTRUCTION in seen, "钉的这个摘要从未出现在 armed 实盘记录里"
