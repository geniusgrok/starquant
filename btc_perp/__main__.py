"""Research measurement, causal replay, and the forward account loop.

With no subcommand this process does not start a session and does not send an
order. Production entries stay closed unless the environment variable and
``config/limits.yaml`` are both set. Keys are read from the environment only.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import math
import os
import signal
import sys
import time
from pathlib import Path

from btc_perp.bars import bars_from_kline_rows, completed_hour_channels, hour_rows_from_klines
from btc_perp.binance_client import UrllibTransport, UsdMClient
from btc_perp.config import ROOT, AccountConfig, load_config
from btc_perp.gates import DEMO, PROD, load_limits, prod_orders_allowed
from btc_perp.model import Limits
from btc_perp.permissions import prod_permission_block, prod_uid_block
from btc_perp.runner import CycleReport, resolve_intent, run_cycle
from btc_perp.store import Store
from btc_perp.user_stream import UserStream

_EXAMPLES = """
examples:
  python -m btc_perp measure
  python -m btc_perp causal
  python -m btc_perp robustness
  python -m btc_perp generalization
  python -m btc_perp check --environment demo
  python -m btc_perp run --environment demo --max-notional-usdt 200 --once
  python -m btc_perp run --environment demo --max-notional-usdt 200 --dry-run --once
  python -m btc_perp stop --environment demo
  python -m btc_perp flatten --environment demo --once
  python -m btc_perp takeover --environment demo --once
  python -m btc_perp rearm --environment demo --yes
  python -m btc_perp resolve --environment demo --client-id en0123456789abcdef0123 --yes
  python -m btc_perp resume --environment demo
"""

CONTROL_COMMANDS = ("run", "stop", "flatten")


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

    robust = sub.add_parser(
        "robustness",
        help="止损更差成交、手续费和参数邻域下的稳健性",
        epilog="python -m btc_perp robustness",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    robust.add_argument("--no-write", action="store_true")

    general = sub.add_parser(
        "generalization",
        help="其他币种、早期 BTC、前进验证和自助法下的泛化检查（研究用，不改任何设置）",
        epilog="python -m btc_perp generalization",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    general.add_argument("--no-write", action="store_true")

    for name, help_text, example in (
        ("check", "只读核对账户、过滤器和保护", "python -m btc_perp check --environment demo"),
        ("run", "真实时钟前向循环", "python -m btc_perp run --environment demo --max-notional-usdt 200 --once"),
        ("stop", "撤销会加仓的挂单，保留实仓保护", "python -m btc_perp stop --environment demo"),
        ("flatten", "只减仓平掉实仓", "python -m btc_perp flatten --environment demo --once"),
        ("takeover", "按实仓接管并继续冻结加仓", "python -m btc_perp takeover --environment demo --once"),
        ("rearm", "空仓时把回撤基准重置为当前权益（需要 --yes）", "python -m btc_perp rearm --environment demo --yes"),
        (
            "resume",
            "只清除 stop/flatten 请求文件；不解除任何账户或资金冻结",
            "python -m btc_perp resume --environment demo",
        ),
        (
            "resolve",
            "确认交易所没有某张未决订单后放行它（需要 --client-id 和 --yes）",
            "python -m btc_perp resolve --environment demo --client-id en0123456789abcdef0123 --yes",
        ),
    ):
        cmd = sub.add_parser(name, help=help_text, epilog=example, formatter_class=argparse.RawDescriptionHelpFormatter)
        cmd.add_argument("--environment", required=True, choices=(DEMO, PROD))
        cmd.add_argument("--state-dir", default="")
        cmd.add_argument("--max-notional-usdt", type=_finite, default=0.0)
        cmd.add_argument("--fx", type=_finite, default=0.0)
        cmd.add_argument("--once", action="store_true")
        cmd.add_argument("--dry-run", action="store_true")
        cmd.add_argument("--poll-seconds", type=_finite, default=5.0)
        cmd.add_argument("--client-id", default="", help="只有 resolve 使用")
        cmd.add_argument("--yes", action="store_true", help="rearm 和 resolve 使用：确认这次操作")

    found = parser.parse_args(args)
    if found.command == "measure":
        from btc_perp.measure import run_official

        report = run_official(write_report=not found.no_write)
        if not report.get("verified"):
            print(f"verified=False reason={report.get('reason')}")
            return 2
        print(
            f"passed={report['passed']} cagr={report['cagr']:.3f} "
            f"end={report['end_cny']:,.0f} ratio={report['min_equity_over_peak']:.3f} "
            f"long={report['n_long']} short={report['n_short']} "
            f"meets_150={bool(report['cagr'] >= 1.5 and report['min_equity_over_peak'] > 0.5)}"
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
    if found.command == "robustness":
        from btc_perp.robustness import run_robustness

        result = run_robustness(write_report=not found.no_write)
        if not result.get("verified"):
            print(f"verified=False reason={result.get('reason')}")
            return 2
        summary = result["summary"]
        print(
            f"neighbour_runs={summary['neighbour_runs']} "
            f"failing={summary['neighbours_breaching_half_peak_or_locked']} "
            f"smallest_stop_extra_that_breaches={summary['smallest_stop_extra_that_breaches']}"
        )
        return 0
    if found.command == "generalization":
        from btc_perp.generalization import run_generalization

        outcome = run_generalization(write_report=not found.no_write)
        if not outcome.get("verified"):
            print(f"verified=False reason={outcome.get('reason')}")
            return 2
        info = outcome["summary"]
        print(
            f"baseline_positive_tapes={info['tapes_with_positive_cagr_baseline_zero_tune']}/{info['tapes']} "
            f"candidate_positive_tapes={info['tapes_with_positive_cagr_candidate']}/{info['tapes']}"
        )
        return 0
    if found.command is None:
        parser.print_help()
        return 2
    return _forward(found)


def _finite(text: str) -> float:
    try:
        value = float(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"{text!r} 不是数字") from exc
    if not math.isfinite(value) or value < 0:
        raise argparse.ArgumentTypeError(f"{text!r} 必须是有限的非负数")
    return value


def _request_file(state: Path, name: str, command: str, environment: str) -> None:
    """A control request belongs to one environment; another environment's runner ignores it."""
    state.mkdir(parents=True, exist_ok=True)
    body = {"command": command, "environment": environment, "ts_ms": int(time.time() * 1000)}
    (state / name).write_text(json.dumps(body) + "\n")


def _write_run_state(state: Path, **fields: object) -> None:
    """The last known lifecycle of this state directory, written atomically."""
    body = {"ts_ms": int(time.time() * 1000), "pid": os.getpid(), **fields}
    target = state / "run_state.json"
    scratch = state / "run_state.json.tmp"
    scratch.write_text(json.dumps(body, ensure_ascii=False) + "\n")
    scratch.replace(target)


def _config_digest(cfg: AccountConfig, limits: Limits, max_notional: float) -> str:
    payload = json.dumps(
        {"cfg": dataclasses.asdict(cfg), "limits": dataclasses.asdict(limits), "cap": max_notional},
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _fetch_minutes(client: UsdMClient, cursor_ms: int, now_ms: int) -> list[object]:
    """Completed and forming minutes from just after the stored cursor, in pages."""
    if cursor_ms <= 0 or (now_ms - cursor_ms) // 60_000 + 3 <= 5:
        return client.klines("1m", 5)
    rows: list[object] = []
    start = cursor_ms + 60_000
    for _page in range(30):
        page = client.klines("1m", 1000, start)
        if not page:
            break
        rows.extend(page)
        last = page[-1]
        last_open = int(last[0]) if isinstance(last, list) else 0
        if len(page) < 1000 or last_open + 60_000 >= now_ms:
            break
        start = last_open + 60_000
    return rows


class _Interrupted(Exception):
    pass


def _raise_interrupt(_signum: int, _frame: object) -> None:
    raise _Interrupted


def _forward(found: argparse.Namespace) -> int:
    environment = str(found.environment)
    command = str(found.command)
    if command == "rearm" and not found.yes:
        print(
            "rearm 会把回撤基准换成当前权益，等于接受此前的亏损作为新起点。\n"
            "只在空仓、没有活动订单、没有未决意图，并且你确认要继续交易时使用：\n"
            "python -m btc_perp rearm --environment demo --yes"
        )
        return 2
    if command == "resolve" and not (found.yes and found.client_id):
        print(
            "resolve 只在你已经核对账户、确认交易所没有这张订单之后使用：\n"
            "python -m btc_perp resolve --environment demo --client-id <编号> --yes"
        )
        return 2
    if command == "resume":
        return _resume(_state_dir(environment, str(found.state_dir)), environment)
    keys = _keys(environment)
    if keys is None:
        which = "STARQUANT_DEMO_API_KEY" if found.environment == DEMO else "STARQUANT_PROD_API_KEY"
        print(
            f"缺少 {which} 和对应的 SECRET。密钥只从环境变量读取，不会写进仓库。\n"
            f"python -m btc_perp {command} --environment {found.environment}"
        )
        return 2
    if command == "run" and found.max_notional_usdt <= 0:
        print("增仓需要名义上限。\npython -m btc_perp run --environment demo --max-notional-usdt 200 --once")
        return 2
    state = _state_dir(environment, str(found.state_dir))
    uid = os.environ.get("STARQUANT_ACCOUNT_UID", "").strip()
    transport = UrllibTransport()
    if environment == PROD:
        blocked = prod_uid_block(keys[0], keys[1], transport, uid)
        if blocked:
            print(blocked)
            return 2
    writes = command in CONTROL_COMMANDS and not found.dry_run
    if writes and command in {"stop", "flatten"}:
        _request_file(state, f"{command}.request", command, environment)
    try:
        store = Store(state, environment)
    except RuntimeError as exc:
        print(str(exc))
        if writes and command in {"stop", "flatten"}:
            print("已写入请求文件；正在运行的进程会在下一轮按它处理。")
        return 2
    try:
        store.bind_credential(keys[0], uid)
    except RuntimeError as exc:
        print(str(exc))
        store.close()
        return 2
    read_only = bool(found.dry_run or command in {"check", "takeover", "rearm", "resolve"})
    client = UsdMClient(environment, keys[0], keys[1], transport, read_only=read_only)
    cfg = load_config()
    limits = load_limits()
    if command == "resolve":
        return _resolve(store, client, str(found.client_id))
    digest = _config_digest(cfg, limits, float(found.max_notional_usdt))
    if command == "run" and not found.dry_run:
        previous = store.get_json("config_digest")
        if previous not in (None, digest) and store.open_intents():
            reason = "配置或名义上限和未完成订单创建时不同，先处理未完成订单（stop 或 resolve）再改配置"
            print(reason)
            _write_run_state(state, phase="not_started", reason=reason, wind_down="not_applicable")
            store.close()
            return 2
        store.put_json("config_digest", digest)
    if environment == PROD and writes:
        blocked = prod_permission_block(environment, keys[0], keys[1], client.transport)
        if blocked:
            print(blocked)
            _write_run_state(state, phase="not_started", reason=blocked, wind_down="unverified")
            store.close()
            return 2
    mode = command
    once = bool(found.once or command != "run")
    if command == "run":
        for name in ("stop.request", "flatten.request"):
            if (state / name).exists():
                print(f"存在 {name}，这一轮会按停机处理；确认后用 resume 清除")
    stream: UserStream | None = None
    if writes:
        stream = UserStream(client, environment)
        stream.start()
    previous_term = signal.signal(signal.SIGTERM, _raise_interrupt)
    if writes:
        _write_run_state(state, phase="running", command=command, wind_down="pending", config=digest)
    report: CycleReport | None = None
    wind: CycleReport | None = None
    interrupted = False
    failure = ""
    try:
        while True:
            now_ms = int(time.time() * 1000)
            report = _one_cycle(found, store, client, stream, cfg, limits, mode, now_ms)
            print(
                f"mode={report.mode} frozen={str(report.frozen).lower()} reason={report.reason} "
                f"position={report.position_qty} covered={str(report.covered).lower()} "
                f"sent={','.join(report.sent) if report.sent else '-'} "
                f"would={','.join(report.would_send) if report.would_send else '-'} "
                f"settled={str(report.settled).lower()} "
                f"remaining={'|'.join(report.remaining) if report.remaining else '-'}"
            )
            if once or (state / "stop.request").exists():
                break
            mode = "run"
            time.sleep(max(float(found.poll_seconds), 1.0))
    except (KeyboardInterrupt, _Interrupted):
        interrupted = True
    except BaseException as exc:
        failure = f"{type(exc).__name__}: {exc}"[:300]
        raise
    finally:
        signal.signal(signal.SIGTERM, previous_term)
        if command == "run" and not found.dry_run:
            wind = _wind_down(found, store, client, cfg, limits, report)
        if writes:
            _write_run_state(
                state,
                phase="stopped",
                command=command,
                interrupted=interrupted,
                failure=failure,
                wind_down=_wind_state(wind, report),
            )
        if stream is not None:
            stream.stop()
        store.close()
    final = wind or report
    if final is None or interrupted:
        return 2
    if command == "run" and wind is not None and not wind.settled:
        return 2
    if command in {"stop", "flatten", "rearm"}:
        return 0 if final.settled else 2
    return 2 if final.frozen else 0


def _resume(state: Path, environment: str) -> int:
    removed: list[str] = []
    for name in ("stop.request", "flatten.request"):
        path = state / name
        if not path.exists():
            continue
        try:
            body = json.loads(path.read_text() or "{}")
        except (OSError, ValueError):
            body = {}
        owner = body.get("environment") if isinstance(body, dict) else None
        if owner not in (None, environment):
            print(f"{name} 属于 {owner}，不会在 {environment} 下清除")
            continue
        path.unlink()
        removed.append(name)
    print("已清除：" + ", ".join(removed) if removed else "没有需要清除的请求文件")
    print("resume 不解除账户、资金或回撤冻结；这些看 run/check 的输出，回撤基准用 rearm")
    return 0


def _resolve(store: Store, client: UsdMClient, client_id: str) -> int:
    try:
        ok, message = resolve_intent(store, client, client_id)
    finally:
        store.close()
    print(message)
    return 0 if ok else 2


def _wind_state(wind: CycleReport | None, last: CycleReport | None) -> dict[str, object] | str:
    report = wind or last
    if report is None:
        return "unverified"
    return {
        "verified": bool(report.settled),
        "remaining": list(report.remaining),
        "covered": report.covered,
        "position": report.position_qty,
    }


def _one_cycle(
    found: argparse.Namespace,
    store: Store,
    client: UsdMClient,
    stream: UserStream | None,
    cfg: AccountConfig,
    limits: Limits,
    mode: str,
    now_ms: int,
) -> CycleReport:
    stream_expired = False
    if stream is not None:
        stream.keepalive(now_ms)
        stream.reconnect_if_due(now_ms)
        hints, stream_expired = stream.poll()
        for hint in hints:
            store.append_journal(
                {
                    "ts_ms": now_ms,
                    "kind": "stream",
                    "event": hint.kind,
                    "client_id": hint.client_id,
                    "status": hint.status,
                }
            )
    minute: list[object] = []
    hourly: list[object] = []
    if mode == "run":
        # Only new risk needs market series. Stop, flatten and the read-only modes never wait for them.
        try:
            minute = _fetch_minutes(client, store.load_book().cursor_ms, now_ms)
            hourly = client.klines("1h", max(cfg.entry_hours + 2, 100))
        except (OSError, RuntimeError, TimeoutError, ValueError) as exc:
            print(f"行情读取失败，本轮停止新增风险：{exc}"[:300])
    rows = hour_rows_from_klines(hourly, now_ms) if hourly else None
    if mode == "run" and hourly and rows is None:
        print("小时行情有缺口、重复或格式错误，本轮不产生新信号")
    channels = completed_hour_channels(hourly, now_ms, cfg.entry_hours, cfg.exit_hours) if rows is not None else None
    try:
        bars = bars_from_kline_rows(minute, now_ms)
    except ValueError as exc:
        print(f"分钟行情格式错误，本轮不产生新信号：{exc}"[:300])
        bars = ()
    return run_cycle(
        store,
        client,
        environment=str(found.environment),
        limits=limits,
        max_notional=float(found.max_notional_usdt) if found.max_notional_usdt > 0 else None,
        cfg=cfg,
        now_ms=now_ms,
        bars=bars,
        channels=channels,
        hour_rows=rows,
        fx=float(found.fx) if found.fx > 0 else None,
        mode=mode,
        prod_enabled=prod_orders_allowed(),
        dry_run=bool(found.dry_run),
        stream_expired=stream_expired,
    )


def _wind_down(
    found: argparse.Namespace,
    store: Store,
    client: UsdMClient,
    cfg: AccountConfig,
    limits: Limits,
    last: CycleReport | None,
) -> CycleReport | None:
    """Every way out of ``run``: cancel our unfilled entries, keep or restore protection, say what is left."""
    if last is not None and last.mode in {"stop", "flatten"} and last.settled:
        return last
    try:
        report = _one_cycle(found, store, client, None, cfg, limits, "stop", int(time.time() * 1000))
    except Exception as exc:
        print(f"收尾没有完成，交易所上只剩最后确认的状态，收尾未验证：{exc}"[:300])
        return None
    left = "|".join(report.remaining) if report.remaining else "-"
    print(
        f"收尾：settled={str(report.settled).lower()} covered={str(report.covered).lower()} "
        f"position={report.position_qty} remaining={left}"
    )
    return report


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
