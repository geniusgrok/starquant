"""Operator ruling 2026-09-08: the Lark channel is read in Chinese, so it is written in Chinese.

A translation is a state, not an act - it holds until the next alert is added, and the next alert is
always written in the language of the code around it, which is English.  So this ratchets the ruling
the way `test_source_budget` ratchets the line budget: every alert body that is *visible in the
source* has to carry at least one CJK character.

Visible means an f-string or a literal handed straight to ``send``.  A message built somewhere else
and passed by name (``send(breach)``) is out of reach here and is covered where it is built -
``liquidation_alert`` in `test_liquidation_wiring`, the guard lines in `test_plan_gaps`, the daily
findings in `test_alert_routing`.  A test that can only see half the call sites still closes the half
that a new alert is written into.
"""

from __future__ import annotations

import ast
import json
import re
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import yaml
from click.testing import CliRunner

from starquant_cli import main
from starquant_shared.config import load_yaml

ROOT = Path(__file__).resolve().parents[2]
SOURCES = ("starquant_live", "starquant_cli")


def _has_cjk(text: str) -> bool:
    return any("一" <= ch <= "鿿" for ch in text)


def _english_words(lines: Sequence[str]) -> set[str]:
    """Words that read as prose: >=4 ASCII letters, in a token carrying no digit.

    The digit rule is what keeps a hex digest or a `+4.0s` from being read as English; anything left
    is a word a human wrote.
    """
    words: set[str] = set()
    for line in lines:
        for token in re.split(r"[^0-9A-Za-z_.]+", line):
            if not token or any(ch.isdigit() for ch in token):
                continue
            words.update(word for word in re.findall(r"[A-Za-z]{4,}", token))
    return words


def _literal_text(node: ast.expr) -> str | None:
    """The prose of a directly-written message, or None when the source cannot see one."""
    if isinstance(node, ast.Constant):
        return node.value if isinstance(node.value, str) else None
    if isinstance(node, ast.JoinedStr):
        return "".join(part.value for part in node.values if isinstance(part, ast.Constant))
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _literal_text(node.left), _literal_text(node.right)
        return None if left is None and right is None else (left or "") + (right or "")
    return None


def _english_alerts() -> list[str]:
    offenders: list[str] = []
    for package in SOURCES:
        for path in sorted((ROOT / package).rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not node.args:
                    continue
                func = node.func
                if not isinstance(func, ast.Attribute) or func.attr != "send":
                    continue
                text = _literal_text(node.args[0])
                if text and text.strip() and not _has_cjk(text):
                    offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}: {text[:80]}")
    return offenders


def test_every_alert_written_in_the_source_is_chinese() -> None:
    offenders = _english_alerts()
    assert not offenders, "these alert bodies would reach the operator's channel in English:\n" + "\n".join(offenders)


def test_the_check_job_sends_chinese_too() -> None:
    """`run_check.sh` is the path that says THE LOOP IS DOWN, and it builds its own message in shell."""
    script = (ROOT / "deploy/run_check.sh").read_text(encoding="utf-8")
    sent = [line for line in script.splitlines() if "alert-dedup.json" in line]

    assert len(sent) == 1, sent
    assert _has_cjk(sent[0]), sent[0]


def test_the_check_output_the_job_pastes_is_chinese(tmp_path: Path) -> None:
    """The hourly alert's BODY is `tail -n 3` of this command, so every prose line here is alert text.

    Found the hard way: `restarts_note()` said "no failure recorded" three functions away from any
    `send`, and it lands in the middle of the line the job pastes.  The AST check above cannot see it,
    so this one reads the rendered output instead - the JSON dump excepted, which is machine data.
    """
    profile = tmp_path / "profile.yaml"
    payload = load_yaml(ROOT / "config/live.demo.yaml")
    payload["paths"] = {"state_dir": str(tmp_path / "live"), "reports_dir": str(tmp_path / "reports")}
    profile.write_text(yaml.safe_dump(payload), encoding="utf-8")
    # One completed cycle, so the cycle line renders its measured form rather than "none in the
    # window" - `restarts_note()` only appears on that branch, and it is the line that was missed.
    live = tmp_path / "live"
    live.mkdir(parents=True)
    (live / "cycles.jsonl").write_text(
        json.dumps({"at": datetime.now(UTC).isoformat(), "phase": "OK", "dry_run": False}) + "\n", encoding="utf-8"
    )

    output = CliRunner().invoke(main, ["live", "status", "--profile", str(profile), "--check"]).output
    after_json = output.rsplit("\n}\n", 1)[-1]  # the state dump is data; everything after it is prose
    prose = [line for line in after_json.splitlines() if line.strip()]

    assert prose, output
    assert all(_has_cjk(line) for line in prose), [line for line in prose if not _has_cjk(line)]
    # "has some Chinese" is too weak: `restarts_note()` hid an English clause at the end of a line
    # that was otherwise Chinese.  So every English WORD has to be a machine token someone chose to
    # keep - extend the set in the commit that introduces one, the way the line budget is raised.
    assert _english_words(prose) <= {"Error", "registry", "digest"}, _english_words(prose)
