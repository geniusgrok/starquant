"""Every command added on 2026-09-09/10, driven the way the operator drives it.

`governance canary` shipped broken on its first real run - `load_jsonl` takes text and it was handed a
Path - and nothing caught it, because a command added to make a module reachable and then never
exercised is the same defect one level out from the one it was added to fix.  The module had tests.
The command had none.

So this file drives each command through `CliRunner` on real files, and asserts on what an operator
would read off the terminal.  It is deliberately shallow: the arithmetic belongs to the modules'
own tests, and duplicating it here would make both harder to change.  What it holds is that the
command RUNS, reads the files it says it reads, and exits the way its `--check` promises.
"""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from starquant_cli.governance_cmd import canary_cmd, divergence_cmd, gate_cmd, review_cmd, verdicts_cmd
from starquant_cli.live_cmd import live_soak
from starquant_governance.verdicts import ALLOW
from starquant_governance.verdicts import read as read_verdicts
from starquant_governance.verdicts import record as record_verdict

REGISTRY = {
    "version": 1,
    "ensemble": {"method": "mean", "turnover_penalty": 0.0},
    "strategies": [{"id": "tsmom", "enabled": True, "weight": 1.0, "evidence": {"report": "r.json"}}],
}
SELECTION = {
    "oos_selection": {
        "alpha": 0.05,
        "gate": "max_sharpe_quantile",
        "n_trials": 183,
        "variance": 2.1972757178172574e-05,
        "oos_sharpe_annual": 1.8087,
        "threshold_annual": 1.5136,
    },
    "ledger": {"ledger_trials": 86},
}


def _checkout(tmp_path: Path) -> Path:
    """A checkout shaped the way `gate_cmd` reads one, ledger included.

    The ledger goes wherever `resolve_ledger_path` says, not where this fixture would like: the suite
    redirects it through `STARQUANT_TRIALS_LEDGER` (KILL-Q5 - the ledger's address must not be a flag a
    test can point somewhere convenient), and writing beside the registry instead produced an empty
    bucket and an UNREADABLE verdict.  Which is the guard working: fewer rows than the report recorded
    is impossible on an append-only ledger, so it refused rather than deciding on a truncated record.
    """
    import yaml

    from starquant_alpha.validation.ledger import resolve_ledger_path

    (tmp_path / "governance").mkdir()
    (tmp_path / "registry.yaml").write_text(yaml.safe_dump(REGISTRY), encoding="utf-8")
    (tmp_path / "r.json").write_text(json.dumps(SELECTION), encoding="utf-8")
    ledger = resolve_ledger_path(root=tmp_path)
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text(
        "\n".join(
            json.dumps(
                {
                    "strategy": "tsmom",
                    "param_key": f"i={i}",
                    "sharpe_annual": 0.1,
                    "bars_per_year": 8760.0,
                    "recorded_at": "2026-09-09T00:00:00+00:00",
                    "range_start": "2021-07-01 01:00:00+00:00",
                    "range_end": "2026-09-01 01:00:00+00:00",
                    "symbols": 15,
                    "run_id": f"fixture-{i}",
                }
            )
            for i in range(86)
        )
        + "\n",
        encoding="utf-8",
    )
    return tmp_path


def test_governance_gate_reads_the_registry_and_the_ledger(tmp_path: Path) -> None:
    root = _checkout(tmp_path)
    result = CliRunner().invoke(gate_cmd, ["--registry", str(root / "registry.yaml"), "--root", str(root), "--check"])
    assert result.exit_code == 0, result.output + str(result.exception)
    assert "PASS" in result.output and "tsmom" in result.output
    assert "1 strategies: 1 pass, 0 fail, 0 unreadable" in result.output


def test_governance_gate_records_its_ruling_for_m_g05(tmp_path: Path) -> None:
    """The gate's own verdict has to reach the ledger, or M-G05's sample has a hole where this gate is."""
    root = _checkout(tmp_path)
    CliRunner().invoke(gate_cmd, ["--registry", str(root / "registry.yaml"), "--root", str(root)])
    rows = read_verdicts(root / "governance" / "verdicts.jsonl")
    assert [(r.kind, r.subject, r.ruling) for r in rows] == [("family_gate", "tsmom", ALLOW)]
    assert rows[0].pending


def test_governance_verdicts_review_and_divergence_are_one_loop(tmp_path: Path) -> None:
    """The three commands are useless apart: record, review, count.  Driven as the loop they are."""
    root = _checkout(tmp_path)
    ledger = root / "governance" / "verdicts.jsonl"
    verdict = record_verdict(ledger, kind="admission", subject="cand.yaml", ruling=ALLOW)

    listed = CliRunner().invoke(verdicts_cmd, ["--root", str(root), "--pending"])
    assert listed.exit_code == 0 and verdict.id in listed.output and "1 verdicts, 1 awaiting review" in listed.output

    reviewed = CliRunner().invoke(
        review_cmd, [verdict.id, "--disagree", "--why", "R3 should have caught the sum", "--root", str(root)]
    )
    assert reviewed.exit_code == 0 and "disagree" in reviewed.output

    counted = CliRunner().invoke(divergence_cmd, ["--root", str(root)])
    assert counted.exit_code == 0
    assert "below quorum" in counted.output, "one review is not a divergence rate"
    assert "0 pending review" in counted.output


def test_a_review_that_says_nothing_is_refused_at_the_command(tmp_path: Path) -> None:
    root = _checkout(tmp_path)
    verdict = record_verdict(root / "governance" / "verdicts.jsonl", kind="admission", subject="c", ruling=ALLOW)
    result = CliRunner().invoke(review_cmd, [verdict.id, "--agree", "--why", "  ", "--root", str(root)])
    assert result.exit_code != 0 and "say why" in result.output


def test_live_soak_scores_a_record_and_gates_on_the_no_decision_reading(tmp_path: Path) -> None:
    state = tmp_path / "paper"
    state.mkdir()
    rows = [
        {"at": f"2026-09-{1 + h // 24:02d}T{h % 24:02d}:00:00+00:00", "orders": [], "risk_ladder": {}}
        for h in range(24 * 8)
    ]
    rows[10]["phase"] = "ERROR"  # harmless: it decided nothing
    (state / "cycles.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

    result = CliRunner().invoke(live_soak, ["--state-dir", str(state), "--root", str(tmp_path), "--check"])
    assert result.exit_code == 0, result.output + str(result.exception)
    assert "§5 L3 字面   FAIL" in result.output, "one ERROR phase fails the literal reading"
    assert "§5 no-decision PASS" in result.output, "and passes the one --check gates on"

    rows[10]["orders"] = [{"symbol": "BTCUSDT"}]
    (state / "cycles.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    deciding = CliRunner().invoke(live_soak, ["--state-dir", str(state), "--root", str(tmp_path), "--check"])
    assert deciding.exit_code == 1, "an ERROR cycle that DECIDED something is what the gate is for"


def test_live_soak_refuses_a_state_dir_with_no_record(tmp_path: Path) -> None:
    result = CliRunner().invoke(live_soak, ["--state-dir", str(tmp_path / "nope")])
    assert result.exit_code != 0 and "no soak record" in result.output


def test_governance_canary_still_refuses_an_absent_soak(tmp_path: Path) -> None:
    """Kept here beside its siblings: this is the command that shipped broken, and it stays driven."""
    result = CliRunner().invoke(canary_cmd, ["--shadow-dir", str(tmp_path / "none"), "--state-dir", str(tmp_path)])
    assert result.exit_code != 0 and "no shadow record" in result.output
