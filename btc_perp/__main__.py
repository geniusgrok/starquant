"""Research measurement, causal replay, and the forward account loop.

With no subcommand this process does not start a session and does not send an
order. Production entries stay closed unless the environment variable and
``config/limits.yaml`` are both set. Keys are read from the environment only.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from btc_perp.bars import bars_from_kline_rows, completed_hour_channels
from btc_perp.binance_client import UrllibTransport, UsdMClient
from btc_perp.config import ROOT, load_config
from btc_perp.gates import DEMO, PROD, load_limits, prod_orders_allowed
from btc_perp.runner import run_cycle
from btc_perp.store import Store

_EXAMPLES = """
examples:
  python -m btc_perp measure
  python -m btc_perp causal
  python -m btc_perp check --environment demo
  python -m btc_perp run --environment demo --max-notional-usdt 200 --once
  python -m btc_perp run --environment demo --max-notional-usdt 200 --dry-run --once
  python -m btc_perp stop --environment demo
  python -m btc_perp flatten --environment demo --once
  python -m btc_perp takeover --environment demo --once
"""


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print(
            "这个入口不会下单，也不会启动会话。生产增仓默认关闭。\n"
            "历史同根收盘测量：python -m btc_perp measure\n"
            "收盘后下一根开盘的经济对照：python -m btc_perp causal\n"
            "只读核对：python -m btc_perp check --environment demo\n"
            "Demo 前向一轮：python -m btc_perp run --environment demo --max-notional-usdt 200 --once"
        )
        return 0
    if args[0] == "--measure":
        args = ["measure", *args[1:]]
    parser = argparse.ArgumentParser(
        prog="btc_perp", epilog=_EXAMPLES, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command")

    measure = sub.add_parser(
        "measure",
        help="同根收盘的历史测量",
        epilog="python -m btc_perp measure",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    measure.add_argument("--no-write", action="store_true")

    causal = sub.add_parser(
        "causal",
        help="收盘后下一根开盘成交的经济对照",
        epilog="python -m btc_perp causal",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    causal.add_argument("--no-write", action="store_true")

    for name, help_text, example in (
        ("check", "只读核对账户、过滤器和保护", "python -m btc_perp check --environment demo"),
        ("run", "真实时钟前向循环", "python -m btc_perp run --environment demo --max-notional-usdt 200 --once"),
        ("stop", "撤销会加仓的挂单，保留实仓保护", "python -m btc_perp stop --environment demo"),
        ("flatten", "只减仓平掉实仓", "python -m btc_perp flatten --environment demo --once"),
        ("takeover", "按实仓接管并继续冻结加仓", "python -m btc_perp takeover --environment demo --once"),
    ):
        cmd = sub.add_parser(name, help=help_text, epilog=example, formatter_class=argparse.RawDescriptionHelpFormatter)
        cmd.add_argument("--environment", required=True, choices=(DEMO, PROD))
        cmd.add_argument("--state-dir", default="")
        cmd.add_argument("--max-notional-usdt", type=float, default=0.0)
        cmd.add_argument("--fx", type=float, default=0.0)
        cmd.add_argument("--once", action="store_true")
        cmd.add_argument("--dry-run", action="store_true")
        cmd.add_argument("--poll-seconds", type=float, default=5.0)

    found = parser.parse_args(args)
    if found.command == "measure":
        from btc_perp.measure import run_official

        report = run_official(write_report=not found.no_write)
        print(
            f"passed={report['passed']} cagr={report['cagr']:.3f} "
            f"end={report['end_cny']:,.0f} ratio={report['min_equity_over_peak']:.3f} "
            f"long={report['n_long']} short={report['n_short']}"
        )
        return 0
    if found.command == "causal":
        from btc_perp.causal import run_causal

        report = run_causal(write_report=not found.no_write)
        print(
            f"verified={report.get('verified')} meets_150={report.get('meets_150')} "
            f"meets_100={report.get('meets_100')} end={report.get('end_cny')} cagr={report.get('cagr')}"
        )
        return 0 if report.get("verified") else 2
    if found.command is None:
        parser.print_help()
        return 2
    return _forward(found)


def _forward(found: argparse.Namespace) -> int:
    keys = _keys(str(found.environment))
    if keys is None:
        which = "STARQUANT_DEMO_API_KEY" if found.environment == DEMO else "STARQUANT_PROD_API_KEY"
        print(
            f"缺少 {which} 和对应的 SECRET。密钥只从环境变量读取，不会写进仓库。\n"
            f"python -m btc_perp {found.command} --environment {found.environment}"
        )
        return 2
    if found.command == "run" and found.max_notional_usdt <= 0:
        print("增仓需要名义上限。\npython -m btc_perp run --environment demo --max-notional-usdt 200 --once")
        return 2
    state = _state_dir(str(found.environment), str(found.state_dir))
    if found.command == "stop":
        state.mkdir(parents=True, exist_ok=True)
        (state / "stop.request").write_text("stop\n")
    if found.command == "flatten":
        state.mkdir(parents=True, exist_ok=True)
        (state / "flatten.request").write_text("flatten\n")
    try:
        store = Store(state, str(found.environment))
    except RuntimeError as exc:
        print(str(exc))
        return 2
    client = UsdMClient(str(found.environment), keys[0], keys[1], UrllibTransport())
    cfg = load_config()
    limits = load_limits()
    mode = {"check": "check", "run": "run", "stop": "stop", "flatten": "flatten", "takeover": "takeover"}[
        str(found.command)
    ]
    once = bool(found.once or found.command != "run")
    report = None
    try:
        while True:
            now_ms = int(time.time() * 1000)
            try:
                minute = client.klines("1m", 5)
                hourly = client.klines("1h", max(cfg.entry_hours + 2, 100))
            except (OSError, RuntimeError, TimeoutError, ValueError) as exc:
                print(f"行情读取失败，本轮停止新增风险：{exc}"[:300])
                return 2
            channels = completed_hour_channels(hourly, now_ms, cfg.entry_hours, cfg.exit_hours)
            hour_rows: list[tuple[int, float, float]] = []
            if isinstance(hourly, list):
                for row in hourly:
                    if isinstance(row, list) and len(row) >= 7 and int(row[6]) <= now_ms:
                        hour_rows.append((int(row[0]), float(row[2]), float(row[3])))
            report = run_cycle(
                store,
                client,
                environment=str(found.environment),
                limits=limits,
                max_notional=float(found.max_notional_usdt) if found.max_notional_usdt > 0 else None,
                cfg=cfg,
                now_ms=now_ms,
                bars=bars_from_kline_rows(minute, now_ms),
                channels=channels,
                hour_rows=tuple(hour_rows),
                fx=float(found.fx) if found.fx > 0 else None,
                mode=mode,
                prod_enabled=prod_orders_allowed(),
                dry_run=bool(found.dry_run),
            )
            print(
                f"mode={report.mode} frozen={str(report.frozen).lower()} reason={report.reason} "
                f"position={report.position_qty} covered={str(report.covered).lower()} "
                f"sent={','.join(report.sent) if report.sent else '-'} "
                f"would={','.join(report.would_send) if report.would_send else '-'}"
            )
            if once or (state / "stop.request").exists():
                break
            mode = "run"
            time.sleep(max(float(found.poll_seconds), 1.0))
    finally:
        store.close()
    if report is None:
        return 2
    return 2 if report.frozen else 0


def _keys(environment: str) -> tuple[str, str] | None:
    if environment == DEMO:
        key = os.environ.get("STARQUANT_DEMO_API_KEY", "")
        secret = os.environ.get("STARQUANT_DEMO_API_SECRET", "")
    elif environment == PROD:
        key = os.environ.get("STARQUANT_PROD_API_KEY", "")
        secret = os.environ.get("STARQUANT_PROD_API_SECRET", "")
    else:
        return None
    if not key or not secret:
        return None
    return key, secret


def _state_dir(environment: str, explicit: str) -> Path:
    if explicit:
        return Path(explicit)
    override = os.environ.get("STARQUANT_STATE_DIR", "")
    if override:
        return Path(override) / environment
    return ROOT / "state" / environment


if __name__ == "__main__":
    raise SystemExit(main())
