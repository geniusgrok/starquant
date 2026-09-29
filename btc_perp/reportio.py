"""Saved research reports: one file per run, and a pointer that moves only for a complete run.

Four different facts travel with every report and are never merged into one
"passed": the input data validated, the path ran to the end, execution is
closed (a replay has no real execution, so it is never closed), and the
economic line was met. The pointer file (for example
``reports/btc_account_causal.json``) is replaced only when the run is verified
and its data and path facts are true; anything else lands beside it as
``.unverified.json`` and replaces nothing.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import uuid
from pathlib import Path
from typing import Any

EXECUTION_NOTE = "回放里成交是模型假设，没有真实执行，所以 execution_closed 恒为 false"


def completion(
    *, data_validated: bool, path_complete: bool, economic_pass: bool, execution_closed: bool = False
) -> dict[str, Any]:
    return {
        "data_validated": bool(data_validated),
        "path_complete": bool(path_complete),
        "execution_closed": bool(execution_closed),
        "economic_pass": bool(economic_pass),
        "note": EXECUTION_NOTE,
    }


def _atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    scratch = path.with_suffix(f".tmp{os.getpid()}")
    try:
        scratch.write_text(text)
        os.replace(scratch, path)
    finally:
        scratch.unlink(missing_ok=True)


def publish(pointer: Path, report: dict[str, Any]) -> Path:
    """Save the run under its own id, then move the pointer only if the saved copy checks out."""
    run_id = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    report["run_id"] = run_id
    facts = report.get("completion")
    if not isinstance(facts, dict):
        facts = completion(data_validated=False, path_complete=False, economic_pass=False)
        report["completion"] = facts
    text = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    saved = pointer.parent / "runs" / f"{pointer.stem}-{run_id}.json"
    _atomic(saved, text)
    formal = (
        report.get("verified") is True and facts.get("data_validated") is True and facts.get("path_complete") is True
    )
    if formal:
        try:
            echoed = json.loads(saved.read_text())
        except (OSError, ValueError):
            echoed = {}
        formal = isinstance(echoed, dict) and echoed.get("run_id") == run_id
    target = pointer if formal else pointer.with_suffix(".unverified.json")
    _atomic(target, text)
    return target
