"""CPCV's embargo is its own boundary, and splitting it out changed nothing today.

The 2026-09-13 review's orange CPCV entry: `--purge` was doing double duty as the embargo, at 50 bars
against a 720-bar feature lookback, so roughly 670 bars of every training group that sits AFTER a test
block were computed from a window covering that block.  `cpcv_evaluate` selects on those bars, which
makes D-020's `fraction_negative <= 0.10` easier to pass than it should be.

Two things are held here, and the second is the one that matters for this commit:

1. `purge` and `embargo` block DIFFERENT sides, by the amount each names.  There was no test for
   `purge != embargo` at all - the one in `tests/alpha/test_validation.py` passes 5 and 3 and then
   only ever checks the 5 - so nothing would have noticed if the embargo argument were ignored.
2. Leaving `--embargo` off reproduces today's splits and today's CPCV block bit for bit.  Adopting a
   real embargo moves a hard gate and is the operator's pre-registered re-run, not this change.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from click.testing import CliRunner

from starquant_alpha.validation.cpcv import cpcv_splits
from starquant_alpha.validation.verdict import decide
from starquant_cli import main, research_validate_cmd
from starquant_cli.research_cmd import _embargo_bars, research_book, research_validate
from starquant_data.store import KlineStore
from starquant_governance.assemble import newest

SYMBOLS = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT")


def _store_from_fixtures(august_dir: Path, root: Path) -> None:
    store = KlineStore(root)
    for symbol in SYMBOLS:
        frame = pd.read_parquet(august_dir / symbol / "1h.parquet")
        frame["close_time"] = frame["open_time"] + 3_600_000 - 1
        store.append(symbol, "1h", frame)


def _split_with(splits: list, groups: tuple[int, ...]):  # type: ignore[type-arg]
    return next(split for split in splits if split.test_groups == groups)


def test_purge_and_embargo_block_their_own_side_by_their_own_amount() -> None:
    # 600 bars / 6 groups = boundaries every 100.  Test groups (1, 3) -> [100, 200) and [300, 400).
    splits = cpcv_splits(600, n_groups=6, n_test_groups=2, purge=7, embargo=31)
    split = _split_with(splits, (1, 3))
    train = {int(i) for i in split.train_index}
    assert {int(i) for i in split.test_index} == set(range(100, 200)) | set(range(300, 400))
    # before each test block: exactly `purge` bars, and the bar just outside is still training
    assert not (train & set(range(93, 100))) and not (train & set(range(293, 300)))
    assert 92 in train and 292 in train
    # after each test block: exactly `embargo` bars, and the bar just outside is still training
    assert not (train & set(range(200, 231))) and not (train & set(range(400, 431)))
    assert 231 in train and 431 in train
    # 600 - 200 test - 2x7 purged - 2x31 embargoed
    assert len(train) == 600 - 200 - 14 - 62

    # and they are genuinely independent: embargo 0 leaves the "after" side entirely in training
    open_after = _split_with(cpcv_splits(600, n_groups=6, n_test_groups=2, purge=7, embargo=0), (1, 3))
    after = {int(i) for i in open_after.train_index}
    assert set(range(200, 231)) <= after and not (after & set(range(93, 100)))


def test_leaving_embargo_off_reproduces_todays_splits_bit_for_bit() -> None:
    """`--embargo` unset == `--purge`, which is what every archived report was produced under."""
    for purge in (0, 5, 50, 720):
        assert _embargo_bars(purge, None) == purge
        today = cpcv_splits(5_000, n_groups=6, n_test_groups=2, purge=purge, embargo=purge)
        default = cpcv_splits(5_000, n_groups=6, n_test_groups=2, purge=purge, embargo=_embargo_bars(purge, None))
        assert len(default) == len(today) == 15
        for new, old in zip(default, today, strict=True):
            assert new.test_groups == old.test_groups
            assert np.array_equal(new.train_index, old.train_index)
            assert np.array_equal(new.test_index, old.test_index)
    # an explicit value is the only thing that moves it
    assert _embargo_bars(50, 720) == 720 and _embargo_bars(50, 0) == 0


def test_the_flag_defaults_to_none_and_purge_keeps_its_50() -> None:
    """Adopting a new default is a pre-registered re-run; this commit is not allowed to do it."""
    for command in (research_validate, research_book):
        options = {param.name: param for param in command.params}
        assert options["embargo"].default is None, command.name
        assert options["purge"].default == 50, command.name


def test_validate_records_the_embargo_it_used_and_still_reads_a_report_without_one(
    tmp_path: Path, august_dir: Path, isolated_trials_ledger: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "data"
    _store_from_fixtures(august_dir, root)
    runner = CliRunner()
    # What reached `cpcv_splits`, not what the report claims reached it - a flag that is recorded but
    # never passed on would satisfy every other assertion below.
    seen: list[tuple[int, int]] = []

    def recording(n_bars: int, **kwargs: int) -> list:  # type: ignore[type-arg]
        seen.append((kwargs["purge"], kwargs["embargo"]))
        return cpcv_splits(n_bars, **kwargs)

    # M6 之后这个名字读在哪就打在哪：`research_cmd` 只是它的历史地址，打在再导出上不会影响真正的调用点。
    monkeypatch.setattr(research_validate_cmd, "cpcv_splits", recording)

    def run(out: Path, *extra: str) -> dict:
        result = runner.invoke(
            main,
            [
                "research", "validate",
                "--strategy", "tsmom",
                "--root", str(root),
                "--symbols", ",".join(SYMBOLS),
                "--out", str(out),
                "--no-funding",
                "--params", '{"horizons": [5, 20, 50], "crowding_window": 0}',
                "--grid", '{"vol_window": [100, 200]}',
                "--folds", "3",
                "--min-train", "300",
                "--purge", "5",
                "--cpcv-groups", "4",
                "--min-history", "0",
                *extra,
            ],
        )  # fmt: skip
        assert result.exit_code == 0, result.output
        return json.loads(next(out.glob("tsmom-validation-*.json")).read_text(encoding="utf-8"))

    # D-024: the fold vector is reproducible from the report, which now includes the CPCV embargo.
    default_run = run(tmp_path / "default")
    assert default_run["purge"] == 5 and default_run["embargo"] == 5

    # ...and with the flag set to what the fallback picks, the CPCV block is identical.  This is the
    # whole claim of the change: the boundary became nameable, it did not move.
    explicit = run(tmp_path / "explicit", "--embargo", "5")
    assert explicit["cpcv"] == default_run["cpcv"]
    assert explicit["verdict"] == default_run["verdict"] and explicit["embargo"] == 5

    widened = run(tmp_path / "widened", "--embargo", "120")
    assert widened["embargo"] == 120 and widened["purge"] == 5
    # the flag reaches the splitter, and only the "after" side moves with it
    assert seen == [(5, 5), (5, 5), (5, 120)]

    # Every report written before today lacks the key.  Readers must treat that as "embargo == purge",
    # which is what those runs were - never as a missing field to raise on.
    archived = {key: value for key, value in default_run.items() if key != "embargo"}
    assert "embargo" not in archived
    assert decide(archived) == (default_run["verdict"], default_run["reasons"])
    assert newest({"tsmom-validation-x.json": archived}, "validation", "strategy") == {"tsmom": archived}
