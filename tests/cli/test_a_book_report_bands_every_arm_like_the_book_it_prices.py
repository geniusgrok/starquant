"""A book report bands each arm the way the construction bands that book, and says which band it applied.

`research book` prices three books: the main book alone, the main book plus a fraction of the sleeve,
and the sleeve alone.  Once D2 and D3 were on in the profile (2026-09-17), the report banded them three
different ways.  `banded()` - written 2026-09-03, before either knob existed - passed neither to the two
single arms.  The combined arm went through `combine_books`, which passed D2 but not D3.  So D-018's
marginal, total minus main, carried a band difference as well as the sleeve.

On the registry book (tsmom + 1/3 flow, pit, data to 2026-09-22) that difference sat on a knife edge:
the fold win rate is 0.4 as the arms were banded and 0.6 once they are banded alike, the fourth fold's
delta moving from -0.019 to +0.001.  The verdict did not move - the delta is negative either way - but a
check that flips on the ruler is not reading the sleeve.

End to end, on the same principle as `test_a_book_report_measures_the_three_limits.py`: the failure was
in the wiring, never the arithmetic.  The single arms are held to the books `research backtest
--no-exits --no-guards` prices for the same strategies - one-book construction, every band knob, the same
bare-plus-band protocol.  The combined arm is held to the rule in
`tests/alpha/test_the_multi_book_band_is_the_one_book_band.py`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import yaml
from click.testing import CliRunner

from starquant_cli import main
from starquant_data.store import KlineStore
from starquant_shared.config import load_yaml

ROOT = Path(__file__).resolve().parents[2]
SYMBOLS = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT")

REGISTRY = """
version: 1
ensemble:
  method: mean
strategies:
  - id: tsmom
    enabled: true
    params:
      horizons: [5, 20, 50]
      crowding_window: 0
"""
SLEEVE_PARAMS = '{"entry_threshold": 0.05}'

#: The shipped band knobs written out, with the same two numbers moved as in the alpha test and for the
#: same reason: at `vol_target` 0.60 every August weight sits on `max_weight`, and at a band of 0.005 D3
#: has almost nothing to bite.  Written out rather than read from the profile, because what is under test
#: is that the knobs reach the arms, whatever the operator sets them to.
BAND_ON = {
    "vol_target": 0.10,
    "no_trade_band": 0.02,
    "no_trade_rel_band": 0.40,
    "flat_inside_band": True,
    "band_entry_multiple": 2.0,
}
BAND_OFF = {**BAND_ON, "flat_inside_band": False, "band_entry_multiple": 1.0}


def _profile(tmp_path: Path, name: str, knobs: dict[str, Any]) -> Path:
    payload = load_yaml(ROOT / "config" / "live.demo.yaml")
    payload.setdefault("portfolio", {}).update(knobs)
    path = tmp_path / f"{name}.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return path


def _run(args: list[str], out: Path, pattern: str) -> dict[str, Any]:
    """One command, its own `--out`: `_stamp()` has seconds resolution, so two runs could share a name."""
    result = CliRunner().invoke(main, [*args, "--out", str(out)])
    assert result.exit_code == 0, result.output
    (report,) = out.glob(pattern)
    return json.loads(report.read_text(encoding="utf-8"))


def _same(left: dict[str, Any], right: dict[str, Any]) -> bool:
    """Equal to the last bit: a float's repr round-trips exactly, and NaN == NaN, which `==` on dicts denies."""
    return json.dumps(left, sort_keys=True) == json.dumps(right, sort_keys=True)


def test_each_single_arm_is_the_one_book_construction_and_the_report_names_the_band(
    tmp_path: Path, august_dir: Path
) -> None:
    root = tmp_path / "data"
    store = KlineStore(root)
    for symbol in SYMBOLS:
        frame = pd.read_parquet(august_dir / symbol / "1h.parquet")
        frame["close_time"] = frame["open_time"] + 3_600_000 - 1
        store.append(symbol, "1h", frame)
    registry = tmp_path / "registry.yaml"
    registry.write_text(REGISTRY, encoding="utf-8")
    on, off = _profile(tmp_path, "on", BAND_ON), _profile(tmp_path, "off", BAND_OFF)
    common = [
        "--root", str(root), "--symbols", ",".join(SYMBOLS), "--registry", str(registry),
        "--no-funding", "--universe", "static", "--min-history", "0",
    ]  # fmt: skip
    backtest = ["research", "backtest", "--no-exits", "--no-guards", *common]

    book = _run(
        [
            "research", "book", "--main", "tsmom", "--sleeve", "breakout", "--sleeve-params", SLEEVE_PARAMS,
            *common, "--profile", str(on),
            "--folds", "3", "--min-train", "300", "--purge", "5", "--cpcv-groups", "4", "--sensitivity", "",
        ],
        tmp_path / "book",
        "book-*.json",
    )  # fmt: skip
    main_on = _run([*backtest, "--strategy", "tsmom", "--profile", str(on)], tmp_path / "main-on", "*.json")
    main_off = _run([*backtest, "--strategy", "tsmom", "--profile", str(off)], tmp_path / "main-off", "*.json")
    sleeve_on = _run(
        [*backtest, "--strategy", "breakout", "--params", SLEEVE_PARAMS, "--profile", str(on)],
        tmp_path / "sleeve-on",
        "*.json",
    )
    arms = book["universes"]["static"]

    # Not vacuous: D2/D3 move this main book, so an arm that dropped them could not match by coincidence.
    assert not _same(main_on["summary"], main_off["summary"]), "the knobs never bind on this main book"
    assert _same(arms["main_only"]["summary"], main_on["summary"])
    assert _same(arms["sleeve_standalone"]["full_sample"], sleeve_on["summary"])
    # And the artefact says so.  `combination` recorded the two arms of the band and neither knob, so a
    # report banded with D2/D3 and one banded without were indistinguishable on disk.
    assert book["combination"]["flat_inside_band"] is True
    assert book["combination"]["band_entry_multiple"] == 2.0
