"""G10's page goes out once a day (operator ruling 2026-09-23), and only a state file of its own makes it so.

`deploy/run_check.sh` runs every hour and pages every failing line through `notify`, which dedups on a
state file.  `WebhookAlerts._save_state` writes back only the rows its own window kept.  So a daily row
kept in the SHARED file lives only until the next hourly FAIL saves that file - and while any hourly
line is failing, that is every hour.  A longer window alone would have changed nothing.

Three layers: thirty hourly runs replayed against the real class (with the shared-file control that
shows why the file is separate), the script's wiring read as text, and the script's own `notify`
driven end to end against a local webhook.
"""

from __future__ import annotations

import asyncio
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

import httpx
import pytest

from starquant_live.alerts import HOURLY_CALLER_WINDOW_SECONDS, WebhookAlerts

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "deploy" / "run_check.sh"
DAILY_WINDOW = 86_340.0  # 24 h less a minute: strictly shorter than the daily cadence, as 3540 is hourly
HOUR = 3_600.0


def _replay(tmp_path: Path, *, membership_state: Path, membership_window: float, hours: int = 30) -> list[int]:
    """The hours at which the membership line was delivered, with `report` failing every hour as well.

    Each hour builds fresh instances, as the job's fresh process does, in the script's order: `report`
    first, then `membership`.
    """
    now = {"mono": 500_000.0, "wall": 1_789_516_800.0}
    transport = httpx.MockTransport(lambda request: httpx.Response(200))
    delivered = []
    for hour in range(hours):
        clock, wall_clock = (lambda: now["mono"]), (lambda: now["wall"])
        report = WebhookAlerts(
            "https://hooks.example/starquant",
            clock=clock,
            wall_clock=wall_clock,
            transport=transport,
            state_path=tmp_path / "alert-dedup.json",
        )
        asyncio.run(report.send("StarQuant巡检失败（report）：滑点带外", key="check-report"))
        membership = WebhookAlerts(
            "https://hooks.example/starquant",
            clock=clock,
            wall_clock=wall_clock,
            transport=transport,
            state_path=membership_state,
            dedup_window_seconds=membership_window,
        )
        if asyncio.run(membership.send("StarQuant巡检失败（membership）：落后 15 天", key="check-membership")):
            delivered.append(hour)
        now["mono"] += HOUR
        now["wall"] += HOUR
    return delivered


def test_with_a_state_file_of_its_own_the_page_goes_out_once_a_day(tmp_path: Path) -> None:
    delivered = _replay(tmp_path, membership_state=tmp_path / "alert-dedup-daily.json", membership_window=DAILY_WINDOW)

    assert delivered == [0, 24]


def test_in_the_shared_file_the_same_window_pages_every_hour(tmp_path: Path) -> None:
    """The control: why the file is separate.  `report`'s hourly save drops the daily row each time."""
    delivered = _replay(tmp_path, membership_state=tmp_path / "alert-dedup.json", membership_window=DAILY_WINDOW)

    assert delivered == list(range(30))


def test_the_script_passes_the_daily_window_to_this_line_only() -> None:
    script = SCRIPT.read_text(encoding="utf-8")
    calls = [line.strip() for line in script.splitlines() if line.strip().startswith("notify ")]
    daily = [line for line in calls if "86340" in line]

    assert daily == [
        'notify "membership" "$(echo "$output" | tail -n 3 | tr \'\\n\' \' \')" 86340 "$SUPPORT/alert-dedup-daily.json"'
    ]
    assert all(line.endswith("\\n' ' ')\"") for line in calls if line not in daily), "every other line stays hourly"
    assert float("86340") == DAILY_WINDOW and DAILY_WINDOW < 24 * HOUR and HOURLY_CALLER_WINDOW_SECONDS < HOUR
    assert "dedup_window_seconds=window" in script and '"${4:-$SUPPORT/alert-dedup.json}" "${3:-}"' in script


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


@pytest.fixture
def webhook() -> Iterator[tuple[str, list[str]]]:
    handler = type("Webhook", (_Webhook,), {"received": []})
    server = _LocalServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/hook", handler.received
    finally:
        server.shutdown()
        server.server_close()


def _run_notify(tmp_path: Path, url: str, calls: list[str], *, fresh: bool = True) -> subprocess.CompletedProcess[str]:
    """The script's own `notify`, cut out verbatim, run in bash with this checkout's python.

    `fresh=False` reuses the state directory of an earlier run: the next hourly process, same files.
    """
    found = re.search(r"^notify\(\) \{\n.*?^\}\n", SCRIPT.read_text(encoding="utf-8"), flags=re.S | re.M)
    assert found, "run_check.sh no longer defines notify() the way this test reads it"
    repo, support = tmp_path / "repo", tmp_path / "support"
    if fresh:
        (repo / ".venv" / "bin").mkdir(parents=True)
        python = repo / ".venv" / "bin" / "python"
        python.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n', encoding="utf-8")
        python.chmod(0o755)
        support.mkdir()
    env = {
        key: value for key, value in os.environ.items() if key.lower() not in {"http_proxy", "https_proxy", "all_proxy"}
    }
    env.update(
        REPO=str(repo),
        SUPPORT=str(support),
        STARQUANT_ALERTS_WEBHOOK_URL=url,
        PYTHONPATH=str(ROOT),
        NO_PROXY="127.0.0.1,localhost",
        no_proxy="127.0.0.1,localhost",
    )
    program = "\n".join(["stamp() { date -u +%Y-%m-%dT%H:%M:%SZ; }", found.group(0), *calls])
    return subprocess.run(["bash", "-c", program], env=env, capture_output=True, text=True, timeout=120, check=False)


def _age(state: Path, seconds: float) -> None:
    """Move every row back in time on both clocks, as if the job had last paged `seconds` ago."""
    rows = json.loads(state.read_text(encoding="utf-8"))
    aged = {key: {"at": row["at"] - seconds, "wall": row["wall"] - seconds} for key, row in rows.items()}
    state.write_text(json.dumps(aged), encoding="utf-8")


def test_the_scripts_notify_holds_the_daily_page_across_hours_and_an_hourly_save(
    tmp_path: Path, webhook: tuple[str, list[str]]
) -> None:
    """Two hours after a page, still inside the day: suppressed.  An hourly window would have re-sent it."""
    url, received = webhook
    daily = '"$SUPPORT/alert-dedup-daily.json"'
    page = f'notify "membership" "落后 15 天" 86340 {daily}'
    first = _run_notify(tmp_path, url, [page, 'notify "report" "滑点带外"'])
    assert first.returncode == 0, first.stderr
    _age(tmp_path / "support" / "alert-dedup-daily.json", 2 * HOUR)

    again = _run_notify(tmp_path, url, [page], fresh=False)

    assert again.returncode == 0, again.stderr
    assert received == ["StarQuant巡检失败（membership）：落后 15 天", "StarQuant巡检失败（report）：滑点带外"]
    assert "webhook did NOT deliver" in again.stdout, "the page two hours later is a duplicate inside the day"
    daily_rows = json.loads((tmp_path / "support" / "alert-dedup-daily.json").read_text(encoding="utf-8"))
    shared_rows = json.loads((tmp_path / "support" / "alert-dedup.json").read_text(encoding="utf-8"))
    assert list(daily_rows) == ["check-membership"] and list(shared_rows) == ["check-report"]


def test_a_line_without_the_arguments_is_the_hourly_page_it_always_was(
    tmp_path: Path, webhook: tuple[str, list[str]]
) -> None:
    url, received = webhook
    line = 'notify "report" "滑点带外"'
    result = _run_notify(tmp_path, url, [line, line])
    assert result.returncode == 0, result.stderr
    assert received == ["StarQuant巡检失败（report）：滑点带外"], "the second is a duplicate inside the hourly window"
    _age(tmp_path / "support" / "alert-dedup.json", 2 * HOUR)

    later = _run_notify(tmp_path, url, [line], fresh=False)

    assert later.returncode == 0, later.stderr
    assert received == ["StarQuant巡检失败（report）：滑点带外"] * 2, "two hours on, the hourly page goes out again"
    assert not (tmp_path / "support" / "alert-dedup-daily.json").exists()
