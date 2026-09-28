"""Replay the research measurement, or refuse to trade.

``--measure`` walks the sample as successive manual sessions and prints the
result. Any other invocation prints a refusal and exits. It does not start a
session and it does not send orders.
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
    venue = BinanceExchange()
    if venue.allowed():
        raise RuntimeError("live path is not wired; the gate should be closed")
    print(
        "禁止实盘。这是私人研究，不会下单，这个入口也不会启动会话。"
        f"全样本测量会按配置一段一段手动启动会话，每段 {cfg.session_seconds} 秒、"
        f"每 {cfg.poll_seconds} 秒看一次，每段结束就返回。"
        "重放请运行 python -m btc_perp --measure。"
    )


if __name__ == "__main__":
    main()
