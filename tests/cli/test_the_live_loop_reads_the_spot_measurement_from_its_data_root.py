"""DL-D5 / RISK-G3: the loop is authorised by the ingest that produced its data, or by nothing at all.

`LiveEngine.spot_verification` was `None` in the constructor and nothing ever set it, so the gate
`spot_refusal` guards could not be opened by any measurement, correct or not.  Handing it in from
`live_cmd` is the whole of the wiring, and this is the test that drives it - the 2026-09-09 lesson is
that a module made reachable and then never called is the same defect one level up.

Two properties, and the second is the one that keeps this honest: the verification comes from the DATA
ROOT the loop was pointed at, so a run against a root nobody ingested refuses even when another root on
the same machine has a perfectly good measurement in it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from click.testing import CliRunner

import starquant_cli.live_cmd as live_cmd
from starquant_cli import main
from starquant_data.alignment import PASS, SPOT_COLUMNS, Rival, Verification, write_spot_verification
from tests.live.fakes import UNREACHABLE, paper_venue_from

ROOT = Path(__file__).resolve().parents[2]
PROFILE = str(ROOT / "config/live.demo.yaml")

# The shape `verify_spot_contract` returns on a real month, written by hand here because what is under
# test is the wiring rather than the measurement - `tests/data/test_the_spot_stamp_measurement_is_taken
# _and_recorded.py` owns the measurement, including that these counts cannot be forged past the reader.
MEASURED = Verification(
    PASS,
    "744/744 at the declared offset, 0/743 at -3600000 ms, 0/744 at 3600000 ms",
    744,
    744,
    (Rival(-3_600_000, 0, 743), Rival(3_600_000, 0, 744)),
    SPOT_COLUMNS,
    (),
)


def _run_paper_loop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, data_root: Path) -> dict[str, Any]:
    """One zero-cycle paper start against `data_root`, returning what `LiveEngine` was constructed with."""
    profile = yaml.safe_load(Path(PROFILE).read_text(encoding="utf-8"))
    profile["market_data"]["rest_url"] = UNREACHABLE  # the venue is a dead port; nothing may reach out
    profile["paths"] = {"state_dir": str(tmp_path / "live"), "reports_dir": str(tmp_path / "reports")}
    profile_path = tmp_path / "profile.yaml"
    profile_path.write_text(yaml.safe_dump(profile), encoding="utf-8")
    monkeypatch.setattr(live_cmd, "_paper_venue", paper_venue_from())

    captured: dict[str, Any] = {}
    built = live_cmd.LiveEngine

    def _capture(*args: Any, **kwargs: Any) -> Any:
        captured.update(kwargs)
        return built(*args, **kwargs)

    monkeypatch.setattr(live_cmd, "LiveEngine", _capture)
    result = CliRunner().invoke(
        main,
        [
            "live",
            "run",
            "--profile",
            str(profile_path),
            "--paper",
            "--cycles",
            "0",
            "--symbols",
            "BTCUSDT",
            "--data-root",
            str(data_root),
        ],
    )
    assert result.exit_code == 0, result.output
    assert captured, "the loop never got as far as building an engine"
    return captured


def test_a_root_nobody_measured_starts_the_loop_with_no_verification_at_all(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`None` is the honest value, and it is a refusal: `admits_live_signal` says "no verification on
    record", which is what a root whose `starquant data spot` has never run actually looks like."""
    captured = _run_paper_loop(tmp_path, monkeypatch, tmp_path / "unmeasured")

    assert captured["spot_verification"] is None


def test_the_measurement_written_beside_the_data_is_the_one_the_loop_starts_with(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """And it arrives re-derived from its own counts, not copied - the file lives in a directory an
    operator can edit, and `LiveEngine.__init__` says no edit may open this gate."""
    measured = tmp_path / "measured"
    write_spot_verification(measured, MEASURED, {"symbol": "BTCUSDT", "sample": "2026-08"})

    captured = _run_paper_loop(tmp_path, monkeypatch, measured)

    verification = captured["spot_verification"]
    assert verification is not None and verification.verdict == PASS
    assert verification.compared == 744 and verification.compared_columns == SPOT_COLUMNS
    assert "symbol=BTCUSDT" in verification.reason

    # The other root on the same machine still refuses, which is the point of reading from the root.
    assert _run_paper_loop(tmp_path, monkeypatch, tmp_path / "elsewhere")["spot_verification"] is None
