"""The job that says THE LOOP IS DOWN, fixed in two places (2026-09-25 system review, B1 and B2).

B1.  The loop and `report daily` send every alert to `webhook_url` AND `webhook_url_2` (DL-L3: one URL
is a single point of silence), but `run_check.sh` and `run_governance_gate.sh` handed `WebhookAlerts`
the first URL alone.  A dead first channel therefore silenced exactly the page that matters most, and a
setup with only the second channel configured got no check pages at all.  The URL also rode on python's
argv, where every user on the machine can read it through `ps`.

B2.  `live status --check` calls a heartbeat stale after two bars (7,200s).  The job runs at :10 and a
healthy heartbeat is written about 30s after each close, so a loop that died right after writing one
was 4,170s stale at the first :10 and went unpaged until the second - two bars with no exit check.
"""

from __future__ import annotations

import json
import os
import re
import socketserver
import subprocess
import sys
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "deploy" / "run_check.sh"
GATE = ROOT / "deploy" / "run_governance_gate.sh"
HOUR = 3_600


class _Webhook(BaseHTTPRequestHandler):
    received: list[str]

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        type(self).received.append(json.loads(self.rfile.read(length) or b"{}").get("text", ""))
        self.send_response(200)
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        return


class _LocalServer(HTTPServer):
    def server_bind(self) -> None:
        """`HTTPServer.server_bind` calls `socket.getfqdn`, a reverse lookup measured at 35 s here."""
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = "127.0.0.1", int(self.server_address[1])


def _serve() -> Iterator[tuple[str, list[str]]]:
    handler = type("Webhook", (_Webhook,), {"received": []})
    server = _LocalServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/hook", handler.received
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def first() -> Iterator[tuple[str, list[str]]]:
    yield from _serve()


@pytest.fixture
def second() -> Iterator[tuple[str, list[str]]]:
    yield from _serve()


def _function(script: Path, name: str) -> str:
    found = re.search(rf"^{name}\(\) \{{\n.*?^\}}\n", script.read_text(encoding="utf-8"), flags=re.S | re.M)
    assert found, f"{script.name} no longer defines {name}() the way this test reads it"
    return found.group(0)


def _run(tmp_path: Path, program: list[str], **urls: str) -> tuple[subprocess.CompletedProcess[str], str]:
    """Run shell cut out of a deploy script, against a fake repo whose python logs its own argv."""
    repo, support = tmp_path / "repo", tmp_path / "support"
    (repo / ".venv" / "bin").mkdir(parents=True, exist_ok=True)
    support.mkdir()
    argv_log = tmp_path / "argv.log"
    python = repo / ".venv" / "bin" / "python"
    python.write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" >> "{argv_log}"\nexec "{sys.executable}" "$@"\n')
    python.chmod(0o755)
    env = {
        key: value for key, value in os.environ.items() if key.lower() not in {"http_proxy", "https_proxy", "all_proxy"}
    }
    env = {key: value for key, value in env.items() if not key.startswith("STARQUANT_ALERTS_WEBHOOK_URL")}
    env.update(REPO=str(repo), SUPPORT=str(support), PYTHONPATH=str(ROOT), NO_PROXY="127.0.0.1", no_proxy="127.0.0.1")
    env.update(urls)
    stamp = "stamp() { date -u +%Y-%m-%dT%H:%M:%SZ; }"
    result = subprocess.run(
        ["bash", "-c", "\n".join([stamp, *program])], env=env, capture_output=True, text=True, timeout=120, check=False
    )
    return result, argv_log.read_text(encoding="utf-8") if argv_log.exists() else ""


@pytest.mark.parametrize("script", [CHECK, GATE], ids=["check", "governance_gate"])
def test_both_channels_get_the_page_and_neither_url_is_on_a_command_line(
    tmp_path: Path, script: Path, first: tuple[str, list[str]], second: tuple[str, list[str]]
) -> None:
    (url, got_first), (url_2, got_second) = first, second
    call = 'notify "status" "心跳已过期"' if script == CHECK else 'notify "FAIL tsmom"'

    result, argv = _run(
        tmp_path,
        [_function(script, "notify"), call],
        STARQUANT_ALERTS_WEBHOOK_URL=url,
        STARQUANT_ALERTS_WEBHOOK_URL_2=url_2,
    )

    assert result.returncode == 0, result.stderr
    assert len(got_first) == 1 and got_second == got_first, "the same page, once on each channel"
    assert argv, "precondition: the fake python really was the one that ran"
    assert url not in argv and url_2 not in argv, "a URL on argv is readable by every user through `ps`"


def test_the_second_channel_alone_still_pages(tmp_path: Path, second: tuple[str, list[str]]) -> None:
    url_2, received = second

    result, _ = _run(
        tmp_path, [_function(CHECK, "notify"), 'notify "status" "心跳已过期"'], STARQUANT_ALERTS_WEBHOOK_URL_2=url_2
    )

    assert result.returncode == 0, result.stderr
    assert received == ["StarQuant巡检失败（status）：心跳已过期"]
    assert "did NOT deliver" not in result.stdout


def _threshold() -> int:
    found = re.search(r"^HEARTBEAT_MAX_AGE_SECONDS=(\d+)$", CHECK.read_text(encoding="utf-8"), flags=re.M)
    assert found, "run_check.sh no longer names its heartbeat threshold"
    return int(found.group(1))


def test_the_status_check_is_given_the_threshold_and_verify_is_not(tmp_path: Path) -> None:
    starquant = tmp_path / "repo" / ".venv" / "bin" / "starquant"
    starquant.parent.mkdir(parents=True)
    starquant.write_text('#!/bin/sh\necho "$*"\n')
    starquant.chmod(0o755)
    program = [
        f"HEARTBEAT_MAX_AGE_SECONDS={_threshold()}",
        _function(CHECK, "live_check"),
        "live_check status",
        "live_check verify",
    ]

    result, _ = _run(tmp_path, program)

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        f"live status --check --max-age-seconds {_threshold()}",
        "live verify --check",
    ]


def test_one_missed_bar_pages_at_the_first_check_and_a_healthy_loop_never_does() -> None:
    """The numbers from the 14 days of cycles on the Mac to 2026-09-25: close-to-heartbeat 10s to 50s."""
    check_minute = 10 * 60
    healthiest, slowest = 10, 50
    oldest_healthy = check_minute - healthiest
    one_missed_bar = HOUR + check_minute - slowest

    assert oldest_healthy < _threshold() < one_missed_bar < 2 * HOUR
