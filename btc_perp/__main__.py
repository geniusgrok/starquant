"""Start one finite session, or replay the full account measurement."""

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
        "Live orders are off. One session would poll every "
        f"{cfg.poll_seconds}s for {cfg.session_seconds}s and then exit. "
        "Run `python -m btc_perp --measure` to replay 2020-01-01 through 2026-09-20."
    )


if __name__ == "__main__":
    main()
