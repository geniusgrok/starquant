"""How much of the live return was the market's (D-045): the daily block and `report beta`.

Checklist item #6.9 (performance attribution) of
`docs/analysis/2026-09-23-external-prompt-checklist-vs-starquant.md`.  The computation is
`benchmark.beta_reading`; this module feeds it the archive's closes and renders what it returns.
Since 2026-09-25 also #6.4's loadings on BTC, size, low volatility and funding beside the market:
`factor_loadings.factor_reading`, fed and rendered the same way.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pandas as pd

from starquant_alpha.report import render_markdown
from starquant_data.store import interval_ms
from starquant_live.benchmark import beta_reading
from starquant_live.factor_loadings import archive_funding, archive_history, factor_reading
from starquant_live.report_common import _fmt_num, _fmt_pct, _store_closes, json_dumps
from starquant_live.state import StateStore


def _beta_regression_lines(block: Mapping[str, Any]) -> dict[str, Any]:
    """One regression's readout.  The t printed is Newey-West, never OLS (see `benchmark` for why).

    The BANDWIDTH is on the page beside the t, which it was not until 2026-09-22.  `NW_LAGS` is 48
    and `MIN_BARS` is also 48, so a window that just cleared the minimum ran a Bartlett kernel as
    wide as its own sample and reported the result as if it were the same ruler the long window uses.
    A 55-bar window read alpha t = 5.49 that way against 2.23 on plain OLS.  Printing the constant's
    name while a different width was in force is the failure this repository keeps finding, one
    layer down from `giveback_since_hwm_in_usdt_pct`.
    """
    lags, wanted = block.get("nw_lags"), block.get("nw_lags_requested")
    covers = block.get("nw_covers_intended_horizon")
    clamped = covers is False
    return {
        "beta": _fmt_num(block.get("beta")),
        "beta_t (NW)": _fmt_num(block.get("beta_t")),
        "alpha": f"{_fmt_num(block.get('alpha_bps_per_hour'))} bps/h",
        "alpha_t (NW)": _fmt_num(block.get("alpha_t")),
        "NW 带宽": (
            f"{lags} bar"
            + (
                f"（被夹住：请求 {wanted}，样本不足其 4 倍，修正够不到它要修的两天自相关）"
                if clamped
                else "（= NW_LAGS，够得到两天自相关）"
            )
            if lags is not None
            else "n/a"
        ),
        "alpha annualised": (
            _fmt_pct(block.get("alpha_annualised"))
            if block.get("alpha_annualised") is not None
            else (
                "不年化（NW 带宽被夹住，标准误答的是更窄的问题）"
                if clamped
                else "不年化（|t| < 2，年化会把噪声放大三个数量级）"
            )
        ),
        "R^2": _fmt_num(block.get("r2")),
        "市场部分": _fmt_pct(block.get("market_part")),
        "残差部分": _fmt_pct(block.get("residual_part")),
    }


def market_beta(
    store: StateStore,
    *,
    closes: Callable[[str], pd.Series] | None = None,
    root: str | Path = ".starquant/data",
    interval: str = "1h",
) -> dict[str, Any]:
    """D-045 in the daily report: `report beta`'s reading, taken by the same `beta_reading`.

    Reported, never judged.  Nothing here pages: no threshold for the beta or the residual was
    registered before the book went live, and one picked after reading the number is not a threshold.

    The catch is broad for the reason `exit_counterfactuals` gives.  This runs inside the hourly check,
    and a reading that gates nothing must not take the rest of the report down with it.  The failure
    stays visible: the block carries its reason, and `report beta` on the same state raises it whole.
    """
    try:
        return beta_reading(
            store.read_jsonl(store.cycles_path),
            store.read_jsonl(store.attribution_path),
            closes or _store_closes(root, interval),
        )
    except Exception as exc:
        return {"measured": False, "reason": f"{type(exc).__name__}: {exc}"}


def _market_beta_lines(block: Mapping[str, Any]) -> dict[str, Any]:
    """The daily report's view of `market_beta`: one line per regression, and no verdict.

    Short on purpose.  The full page is `starquant report beta`, and its numbers are these numbers.  The
    all-long share comes before the regressions for the reason `beta_markdown` gives: over those bars
    no split of the return can credit the signal with anything.
    """
    decomposition = block.get("decomposition") or {}
    if not decomposition.get("measured"):
        return {"measured": "no", "reason": decomposition.get("reason") or block.get("reason") or "not computed"}
    window, basket, signal = block.get("window") or {}, block.get("benchmark") or {}, block.get("signal") or {}

    def regression(row: Mapping[str, Any]) -> str:
        return (
            f"beta {_fmt_num(row.get('beta'))}（t {_fmt_num(row.get('beta_t'))}）；"
            f"alpha {_fmt_num(row.get('alpha_bps_per_hour'))} bps/h（t {_fmt_num(row.get('alpha_t'))}）；"
            f"残差部分 {_fmt_pct(row.get('residual_part'))}"
            + (f"；年化 {_fmt_pct(row['alpha_annualised'])}" if row.get("alpha_annualised") is not None else "")
            + (f"；NW 带宽被夹到 {row.get('nw_lags')} bar" if row.get("nw_covers_intended_horizon") is False else "")
        )

    return {
        "窗口": f"{window.get('from')} → {window.get('to')}（{_fmt_num(window.get('days'))} 天）",
        "回归样本": f"{decomposition.get('bars')} 根 bar（剔除的 bar {decomposition.get('excluded_bars')}，D-032）",
        "收益 策略/PIT 基准": (
            f"{_fmt_pct(decomposition.get('strategy_return'))} / {_fmt_pct(decomposition.get('benchmark_return'))}"
        ),
        "净敞口 均值/峰值": (
            f"{_fmt_num(decomposition.get('exposure_mean'))}x / {_fmt_num(decomposition.get('exposure_max'))}x"
        ),
        "基准篮子": (
            f"每根 bar {_fmt_num(basket.get('symbols_per_bar'))} 个币；"
            f"因缺价跳过 {basket.get('prices_missing')} 个 symbol-bar"
        ),
        "全多头的 bar": (
            f"{signal.get('all_long_bars')}/{signal.get('bars')}（{_fmt_pct(signal.get('all_long_share'))}）"
            if signal.get("measured")
            else f"n/a（{signal.get('reason')}）"
        ),
        "constant beta": regression(decomposition.get("constant") or {}),
        "conditional（敞口 × 市场）": regression(decomposition.get("conditional") or {}),
        "读法": "只报告不告警：beta 与残差都没有预登记的阈值。t 按 Newey-West；完整一页见 `starquant report beta`",
    }


def beta_markdown(payload: dict[str, Any]) -> str:
    """`starquant report beta` (D-045): the market's share of the live book's return.

    The signal section comes BEFORE the regressions on purpose.  When every contribution is +1 the
    book is the constant-long comparator and no split of the return can attribute anything to the
    signal; a reader who meets the beta number first will have already formed a view by the time they
    reach that fact.
    """
    decomposition = payload.get("decomposition") or {}
    signal = payload.get("signal") or {}
    if not decomposition.get("measured"):
        sections: list[tuple[str, Any]] = [
            ("Window", payload.get("window") or {}),
            ("无法分解", {"reason": decomposition.get("reason", "unknown")}),
        ]
        return render_markdown("Live beta decomposition", sections)
    all_long = signal.get("all_long_share")
    return render_markdown(
        "Live beta decomposition (D-045)",
        [
            ("Window", payload.get("window") or {}),
            (
                # First, because it bounds what the rest can mean.
                "Signal state",
                {
                    "bars": signal.get("bars"),
                    "全多头的 bar": f"{signal.get('all_long_bars')} ({_fmt_pct(all_long)})",
                    # Renamed 2026-09-22: it counts (bar, symbol) pairs over the window, and read as
                    # a standing position count it produced the question "空头为什么冻在 394" - the
                    # answer being that a cumulative count stops growing, which is not the same event
                    # as a position being closed.  Both numbers now, each saying which it is.
                    "空头信号 bar·标的数（窗口累计）": signal.get("short_positions"),
                    "当前空头标的数（最后一根 bar）": signal.get("shorts_last_bar"),
                    "信号取值": json_dumps(signal.get("values") or {}),
                    "读法": (
                        "全多头的 bar 上这本书按定义等于 constant_long，那些 bar 里的收益不可能来自信号"
                        if (all_long or 0) > 0
                        else "信号在窗口内一直有多空区分"
                    ),
                }
                if signal.get("measured")
                else {"measured": "no", "reason": signal.get("reason")},
            ),
            (
                "Returns",
                {
                    "策略（USDT 权益，A-GB01）": _fmt_pct(decomposition.get("strategy_return")),
                    "PIT 等权基准": _fmt_pct(decomposition.get("benchmark_return")),
                    "净敞口 均值/峰值": f"{_fmt_num(decomposition.get('exposure_mean'))}x / "
                    f"{_fmt_num(decomposition.get('exposure_max'))}x",
                    "bars": decomposition.get("bars"),
                    "剔除的 bar (D-032)": decomposition.get("excluded_bars"),
                },
            ),
            (
                "Basket (point-in-time)",
                {
                    "每根 bar 的币数": _fmt_num((payload.get("benchmark") or {}).get("symbols_per_bar")),
                    "因缺价跳过的 symbol-bar": (payload.get("benchmark") or {}).get("prices_missing"),
                },
            ),
            ("Constant beta", _beta_regression_lines(decomposition.get("constant") or {})),
            (
                # The one that survives the operator moving `vol_target`; the gap to the block above
                # is the size of the error a constant-beta reading makes on this book.
                "Conditional (exposure x market)",
                _beta_regression_lines(decomposition.get("conditional") or {}),
            ),
        ],
    )


#: Display names, in print order.  The three sorts also say which way they point.
FACTOR_LABELS = {"market": "市场", "btc": "BTC", "size": "size", "low_vol": "低波", "funding": "资金费"}
FACTOR_SIGNS = {"size": "成交额大减小", "low_vol": "低减高", "funding": "高减低"}
#: The textbook rule of thumb for a variance inflation factor.  It labels a line; it pages nothing.
HIGH_VIF = 5.0


def factor_loadings(
    store: StateStore, *, root: str | Path = ".starquant/data", interval: str = "1h", strategy: str = "tsmom"
) -> dict[str, Any]:
    """#6.4 / #6.9 in the daily report: `report beta`'s factor page, taken by the same `factor_reading`.

    Reported, never judged, for `market_beta`'s reason: no loading had a threshold registered before
    the book went live.  The catch is broad for the same reason too, and the failure stays visible -
    the block carries its reason, and `report beta` on the same state raises it whole.
    """
    try:
        return factor_reading(
            store.read_jsonl(store.cycles_path),
            store.read_jsonl(store.attribution_path),
            archive_history(root, interval),
            archive_funding(root),
            strategy,
            step_ms=interval_ms(interval),
        )
    except Exception as exc:
        return {"measured": False, "reason": f"{type(exc).__name__}: {exc}"}


def _factor_fit_lines(fit: Mapping[str, Any]) -> dict[str, Any]:
    """One multi-factor regression's readout: a loading and its NW t per factor, then what is left."""
    loadings = fit.get("loadings") or {}
    lines: dict[str, Any] = {
        (f"{label}（{FACTOR_SIGNS[name]}）" if name in FACTOR_SIGNS else label): (
            f"{_fmt_num(loadings[name].get('loading'))}（t {_fmt_num(loadings[name].get('t'))}）"
        )
        for name, label in FACTOR_LABELS.items()
        if name in loadings
    }
    clamped = fit.get("nw_covers_intended_horizon") is False
    if fit.get("alpha_why") is not None:
        lines["alpha"] = f"不谈：{fit['alpha_why']}"
    else:
        lines["alpha"] = (
            f"{_fmt_num(fit.get('alpha_bps_per_hour'))} bps/h（t {_fmt_num(fit.get('alpha_t'))}），"
            f"只算信号有空头的 {fit.get('alpha_bars')} 根 bar；"
            + (
                f"年化 {_fmt_pct(fit['alpha_annualised'])}"
                if fit.get("alpha_annualised") is not None
                else ("不年化（NW 带宽被夹住）" if clamped else "不年化（t 在 ±2 以内）")
            )
        )
    return {
        **lines,
        "R^2": _fmt_num(fit.get("r2")),
        "残差波动（年化）": _fmt_pct(fit.get("residual_vol_annualised")),
        "因子部分 / 残差部分": f"{_fmt_pct(fit.get('factor_part'))} / {_fmt_pct(fit.get('residual_part'))}",
        "NW 带宽": f"{fit.get('nw_lags')} bar"
        + ("（被夹住：样本不足 4 × 48，够不到两天自相关）" if clamped else "（= NW_LAGS，同 D-045）"),
    }


def _archive_line(block: Mapping[str, Any]) -> str:
    """Where the archive stopped.  The keys after it are provisional until the next daily sync revises them."""
    archive = block.get("archive") or {}
    last, behind = archive.get("last_bar"), archive.get("bars_behind_sample_end")
    if last is None:
        return "n/a（归档里读不到最后一根 bar 持有的名字）"
    if behind is None:
        return str(last)
    if behind == 0:
        return f"{last}，已覆盖回归样本末端"
    return f"{last}，比回归样本末端早 {behind} 根。归档每天只同步一次，此后的排名是临时的，下次同步会回改"


def _collinearity_line(fit: Mapping[str, Any]) -> str:
    """The pair that moves most together, and the factors whose loadings it makes unstable."""
    collinear = fit.get("collinearity") or {}
    vif = collinear.get("vif") or {}
    pair = "~".join(FACTOR_LABELS.get(name, name) for name in collinear.get("max_pair") or [])
    high = "、".join(label for name, label in FACTOR_LABELS.items() if vif.get(name, 0.0) >= HIGH_VIF)
    return f"相关最高的一对 {pair or 'n/a'}：{_fmt_num(collinear.get('max_abs_correlation'))}。" + (
        f"{high} 的 VIF ≥ {HIGH_VIF:g}：载荷不稳、t 偏小，要合起来读" if high else f"VIF 都低于 {HIGH_VIF:g}"
    )


def _factor_loadings_lines(block: Mapping[str, Any]) -> dict[str, Any]:
    """The daily report's view of `factor_loadings`: the exposure-conditioned regression, and no verdict.

    Short on purpose, as `_market_beta_lines` is.  The unconditioned regression, every VIF and the
    sorts' coverage are on `starquant report beta`'s page, and its numbers are these numbers.
    """
    regression = block.get("regression") or {}
    if not regression.get("measured"):
        return {"measured": "no", "reason": regression.get("reason") or block.get("reason") or "not computed"}
    fit = regression.get("conditional") or {}
    only_market = (regression.get("market_only") or {}).get("r2")
    return {
        "回归样本": (
            f"{regression.get('bars')} 根 bar（D-032 剔除 {regression.get('excluded_bars')}，"
            f"因子缺值剔除 {regression.get('short_of_factors_bars')}）"
        ),
        "归档的最后一根 bar": _archive_line(block),
        # "回归样本内" because the D-045 section above counts the same name over every bar of the window.
        "全多头的 bar（回归样本内）": (
            f"{regression.get('all_long_bars')}/{regression.get('bars')}：单列截距，不算进 alpha"
        ),
        **_factor_fit_lines(fit),
        "R^2": f"{_fmt_num(fit.get('r2'))}；同一样本只用市场（含全多头截距） {_fmt_num(only_market)}",
        "共线性": _collinearity_line(fit),
        "conditional（敞口 × 因子）": "市场与 BTC 乘净敞口，三个多空因子乘毛敞口。简化：假设权重在三分位间的形状不变",
        "读法": "只报告不告警：载荷没有预登记的阈值。t 按 Newey-West，带宽规则同 D-045。完整一页见 `starquant report beta`",
    }


def factor_markdown(payload: Mapping[str, Any]) -> str:
    """`starquant report beta`'s second page: the multi-factor loadings, both regressions and their inputs."""
    regression = payload.get("regression") or {}
    head: list[tuple[str, Any]] = [("Window", payload.get("window") or {})]
    if not regression.get("measured"):
        head.append(("无法分解", {"reason": regression.get("reason") or payload.get("reason") or "unknown"}))
        return render_markdown("Factor loadings (#6.4 / #6.9)", head)
    conditional, constant = regression.get("conditional") or {}, regression.get("constant") or {}
    return render_markdown(
        "Factor loadings (#6.4 / #6.9)",
        [
            *head,
            (
                # First, for `beta_markdown`'s reason: it bounds what the alpha lines can mean.
                "Signal state",
                {
                    "全多头的 bar（回归样本内）": f"{regression.get('all_long_bars')}/{regression.get('bars')}",
                    "信号取值": json_dumps((payload.get("signal") or {}).get("values") or {}),
                    "读法": "全多头的 bar 另给截距。alpha 只在信号有空头的 bar 上估",
                },
            ),
            (
                "Factors (point-in-time)",
                {
                    "市场": "时点等权基准，与 D-045 同一个篮子",
                    "BTC": "BTCUSDT",
                    "size": "按 30 天成交额排名，前三分之一减后三分之一",
                    "低波": "按 30 天实现波动排名，低三分之一减高三分之一",
                    "资金费": "按 7 天累计资金费率排名，高三分之一减低三分之一",
                    "候选": "每根 bar 当时的 universe。排名只读该 bar 收盘前的数据",
                    "收益": "价格收益，t → t+1。多空两腿各自等权",
                },
            ),
            ("Conditional (exposure x factors)", _factor_fit_lines(conditional)),
            ("Constant", _factor_fit_lines(constant)),
            (
                "Collinearity",
                {
                    "conditional": _collinearity_line(conditional),
                    "constant": _collinearity_line(constant),
                    **{
                        f"VIF（{kind}）": "；".join(
                            f"{label} {_fmt_num(vif[name])}" for name, label in FACTOR_LABELS.items() if name in vif
                        )
                        for kind, vif in (
                            ("conditional", (conditional.get("collinearity") or {}).get("vif") or {}),
                            ("constant", (constant.get("collinearity") or {}).get("vif") or {}),
                        )
                    },
                },
            ),
            (
                "Sample and sorts",
                {
                    "回归样本": regression.get("bars"),
                    "D-032 剔除": regression.get("excluded_bars"),
                    "因子缺值剔除": f"{regression.get('short_of_factors_bars')}；按因子 "
                    + json_dumps(regression.get("factor_missing_bars") or {}),
                    "归档的最后一根 bar": _archive_line(payload),
                    **{
                        FACTOR_LABELS[name]: (
                            f"每根 bar 排名 {_fmt_num(row.get('ranked_per_bar'))} 个币，每腿 "
                            f"{_fmt_num(row.get('names_per_leg'))} 个；缺价跳过 {row.get('leg_names_without_price')}"
                        )
                        for name, row in (payload.get("sorts") or {}).items()
                    },
                },
            ),
        ],
    )
