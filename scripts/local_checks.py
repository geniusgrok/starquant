"""Run named existing offline execution cases and retain actual pytest results."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

CASES = {
    "partial_fill": "tests/test_forward.py::test_a_partial_fill_does_not_open_a_second_order",
    "lost_ack": "tests/test_forward.py::test_an_entry_that_did_fill_is_found_by_the_original_id",
    "restart_unknown": "tests/test_forward.py::test_restart_queries_the_saved_id_and_does_not_mint_another",
    "replacement": "tests/test_safety_contract.py::test_verified_new_stop_retires_old_stop",
    "replacement_failed": "tests/test_safety_contract.py::test_bad_new_stop_never_retires_healthy_old_stop",
    "disconnect": "tests/test_forward.py::test_unknown_snapshot_sends_nothing",
    "stopped_protection": "tests/test_forward.py::test_stop_cancels_risk_orders_and_keeps_protection",
}
ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.out.exists() or subprocess.check_output(
        ["git", "status", "--porcelain", "--", "btc_perp", "scripts", "tests"], cwd=ROOT
    ):
        parser.error("commit source and choose a new report")
    with tempfile.TemporaryDirectory() as directory:
        xml = Path(directory) / "results.xml"
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-m", "not network", *CASES.values(), f"--junitxml={xml}"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        tests = ET.parse(xml).findall(".//testcase") if xml.exists() else []
    rows = {}
    for name, test in CASES.items():
        function = test.split("::")[-1]
        found = [row for row in tests if row.attrib["name"].split("[")[0] == function]
        rows[name] = {
            "test": test,
            "tests_run": len(found),
            "passed": bool(found) and all(len(row) == 0 for row in found),
        }
    files = subprocess.check_output(
        ["git", "ls-files", "btc_perp", "scripts", "tests"], cwd=ROOT, text=True
    ).splitlines()
    hashes = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in files if name.endswith(".py")}
    report = {
        "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "source_sha256": hashes,
        "cases": rows,
        "log": result.stdout + result.stderr,
        "offline_passed": result.returncode == 0 and all(row["passed"] for row in rows.values()),
        "native_execution_verified": False,
        "DEMO_GO": "NO_GO",
        "SMALL_LIVE_GO": "NO_GO",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({name: row["passed"] for name, row in rows.items()}))
    return 0 if report["offline_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
