"""The hourly check was FAILing every hour.  Was the operator being told?

`WebhookAlerts` deduplicates on `time.monotonic()` and persists those values to a JSON file so that
the hourly check job - a fresh process every hour - can suppress a standing problem down to one line
per hour (KILL-R7's fix).  But `time.monotonic()` is only comparable INSIDE one boot: its epoch is
the machine's last boot.  A value written before a reboot is a number from a different frame, and
after a reboot it can be LARGER than the current uptime.

`_suppressed` computes `clock() - last < window`.  With a stored value from a longer-running previous
boot that difference is NEGATIVE, so it is always below the window: the key is suppressed for as long
as it takes uptime to catch up, and nothing inside the boot clears it.

This asks the real class, on the real state file, rather than re-deriving the arithmetic.  Measured
2026-09-14 before the fix, on a machine booted 2026-09-10 12:47:

    check-verify  stored 630465.2  uptime 374798.0  clock-last = -255667  ->  suppressed
                  from_a_previous_boot: true        silent for another 71.0 hours

Rows written after the fix carry a wall reading beside the monotonic one, and this reports both, so
the same command answers the same question before and after.  Read-only: it constructs the object
with no webhook url and never calls `send`.

    python scratchpad/alert_dedup_clock.py
"""

from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from starquant_live.alerts import WebhookAlerts

STATE = Path.home() / "Library/Application Support/starquant/alert-dedup.json"


def uptime_seconds() -> float:
    """The epoch `time.monotonic()` counts from on macOS: seconds since kern.boottime."""
    out = subprocess.run(["sysctl", "-n", "kern.boottime"], capture_output=True, text=True).stdout
    match = re.search(r"sec\s*=\s*(\d+)", out)
    if match is None:
        raise SystemExit("could not read kern.boottime")
    return time.time() - int(match.group(1))


def reading(row: Any, now: float, wall_now: float) -> dict[str, Any]:
    """What the file says about one key, in whichever of the two row shapes it is written in."""
    if isinstance(row, dict):  # after the fix: a monotonic reading and the wall time it was taken at
        at, wall = float(row.get("at", 0.0)), float(row.get("wall", 0.0))
        return {
            "shape": "at+wall",
            "stored_monotonic": round(at, 1),
            "monotonic_age": round(now - at, 1),
            "wall_age": round(wall_now - wall, 1),
            "from_a_previous_boot": at > now,
        }
    return {  # before the fix: a bare monotonic value with no frame attached
        "shape": "bare",
        "stored_monotonic": round(float(row), 1),
        "monotonic_age": round(now - float(row), 1),
        "wall_age": None,
        "from_a_previous_boot": float(row) > now,
    }


def main() -> None:
    now, wall_now = uptime_seconds(), time.time()
    alerts = WebhookAlerts("", state_path=STATE)  # no url: `send` would return False before any I/O
    stored = json.loads(STATE.read_text(encoding="utf-8"))

    rows = []
    for key in sorted(k for k in stored if k.startswith("check-")):
        row = reading(stored[key], now, wall_now)
        row["key"] = key
        # The real predicate, with the real clock.  `_suppressed` reads `_last_sent`, which is what
        # `_load_state` decided to trust - so this answers "would this key be silenced right now?"
        row["suppressed_right_now"] = alerts._suppressed(key)
        if row["from_a_previous_boot"]:
            row["silent_for_another_hours"] = round((row["stored_monotonic"] - now) / 3600, 1)
        rows.append(row)

    print(
        json.dumps(
            {
                "boot": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(wall_now - now)),
                "uptime_days": round(now / 86400, 2),
                "window_seconds": alerts._window,
                "keys": rows,
            },
            indent=1,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
