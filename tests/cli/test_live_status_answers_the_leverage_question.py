"""D-038, one command further: `live status` prints `leverage_set` and nothing to read it against.

D-038 diagnosed this for the daily report and built M-015 for it, and the report renders it well.  The
question still came back a fifth time (2026-09-14), because the command an operator actually reaches for
is `live status` - and it dumps `state.to_dict()`, in which the only per-symbol number is the uniform 5x,
with no counterpart beside it.  Same defect, different command.

These tests pin the two halves the line must carry.  The reading can refuse (a cycle written before
`asset_vol` was recorded, a day with no cycles, too few holdings); the sentence about the venue leverage
cannot, because that is the number the operator came here to look at.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import yaml
from click.testing import CliRunner

from starquant_cli import main
from starquant_live.state import LiveState, StateStore
from starquant_shared.config import load_yaml

ROOT = Path(__file__).resolve().parents[2]
BASE = 1_788_000_000_000
DAY = datetime.fromtimestamp(BASE / 1000, tz=UTC).strftime("%Y-%m-%d")

# The two ends of the live book on 2026-09-13 plus enough names to clear the three-holding floor.
VOLS = {"BTCUSDT": 0.306, "ETHUSDT": 0.561, "SOLUSDT": 0.536, "CYSUSDT": 2.426, "AKEUSDT": 3.226}


def _profile(tmp_path: Path) -> Path:
    payload = load_yaml(ROOT / "config/live.demo.yaml")
    payload["paths"] = {"state_dir": str(tmp_path / "live"), "reports_dir": str(tmp_path / "reports")}
    path = tmp_path / "profile.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return path


def _store(tmp_path: Path, targets: dict[str, float], vols: dict[str, float] | None) -> None:
    store = StateStore(tmp_path / "live")
    record: dict[str, object] = {"as_of_ms": BASE, "equity": 10_791.73, "targets": targets}
    if vols is not None:
        record["asset_vol"] = vols
    store.append_cycle(record)
    store.save(LiveState(leverage_set=dict.fromkeys(targets, 5)))
    store.heartbeat({"phase": "OK"})


def _status(tmp_path: Path) -> str:
    result = CliRunner().invoke(main, ["live", "status", "--profile", str(_profile(tmp_path))])
    assert result.exit_code == 0, result.output
    return result.output


def test_the_uniform_leverage_is_printed_with_the_reading_that_explains_it(tmp_path: Path) -> None:
    """Stage 1 sizing: `|w|` proportional to `1/sigma`, so the risk contributions come out flat."""
    _store(tmp_path, {symbol: 0.30 / vol for symbol, vol in VOLS.items()}, VOLS)

    output = _status(tmp_path)

    assert '"leverage_set"' in output, "the fact that prompts the question is still shown"
    assert "M-015" in output and "D-037" in output
    assert "吸收" in output, "the line says how much of the market's dispersion sizing takes back out"
    # The same ruler the daily report uses, `1 - compression`, rather than a second one invented here:
    # risk_spread is 1.0 under pure stage 1, so compression is 1/vol_spread = 0.306/3.226 and the line
    # reads 91%.  Asserting the number keeps it tied to VOLS above instead of to a phrase.
    assert "91%" in output


def test_deleting_stage_one_changes_the_line_rather_than_leaving_it_decorative(tmp_path: Path) -> None:
    """The falsifier at this layer: size every symbol alike and the same line must report 0% absorbed."""
    _store(tmp_path, dict.fromkeys(VOLS, 0.05), VOLS)

    output = _status(tmp_path)

    assert "吸收" in output and "0%" in output
    # The instrument's own verdict, not a softened one.  "当前告警" rather than "ALERT" because this
    # line is `live status` prose, which is the hourly alert's body and Chinese by the 2026-09-08 ruling
    # (`test_alerts_are_chinese`); "告警" alone would also match the threshold clause on a healthy line.
    assert "当前告警" in output


def test_a_refusal_still_states_what_the_venue_leverage_does_here(tmp_path: Path) -> None:
    """A cycle written before `asset_vol` was recorded has no reading - and still has the answer."""
    _store(tmp_path, dict.fromkeys(VOLS, 0.05), None)

    output = _status(tmp_path)

    assert "读不出" in output, "a missing reading says why rather than going quiet"
    assert "D-037" in output, "the half that answers the operator is carried on every path"
    assert "1 个取值" in output


def test_the_json_dump_is_still_machine_readable(tmp_path: Path) -> None:
    """The line is echoed beside the dump, not spliced into it: `live status | jq` must keep working."""
    _store(tmp_path, {symbol: 0.30 / vol for symbol, vol in VOLS.items()}, VOLS)

    output = _status(tmp_path)

    payload = json.loads(output[output.index("{") : output.rindex("}") + 1])
    assert set(payload) == {"heartbeat", "state"}
    assert payload["state"]["leverage_set"] == dict.fromkeys(VOLS, 5)
