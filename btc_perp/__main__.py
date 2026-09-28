"""Replay the research measurement, or refuse to trade.

``--measure`` runs the 1-minute account replay. Any other invocation prints a
refusal and exits. It does not start ``Session`` and it does not send orders.
"""

from __future__ import annotations

import sys

from btc_perp.config import load_config
from btc_perp.exchange import BinanceExchange


def main() -> None:
    cfg = load_config()
    if "--measure" in sys.argv:
        from btc_perp.measure import run_official

        report = run_official()
        print(
            f"passed={report['passed']} cagr={report['cagr']:.3f} "
            f"end={report['end_cny']:,.0f} ratio={report['min_equity_over_peak']:.3f} "
            f"long={report['n_long']} short={report['n_short']}"
        )
        return
    venue = BinanceExchange(cfg.live_orders, measurement_passed=False, checks_passed=False, api_key=None)
    if venue.allowed():
        raise RuntimeError("live path is not wired; the gate should be closed")
    print(
        "禁止实盘。这是私人研究，不会下单，也不会启动会话。"
        f"配置里的轮询是每 {cfg.poll_seconds} 秒一次、最长 {cfg.session_seconds} 秒，本入口不用它。"
        "重放全样本请运行 python -m btc_perp --measure。"
    )


if __name__ == "__main__":
    main()
