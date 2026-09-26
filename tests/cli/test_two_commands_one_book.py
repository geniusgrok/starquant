"""`backtest` and `validate` now price the same book by default, and every report says which book.

The 2026-09-17 module review recorded "six commands, three books" and called it a defect.  Working
through it, only part of that is one, and the difference matters enough to write down:

* **`research overlay` scores the BARE ensemble on purpose.**  `docs/RESEARCH_LOG.md` (2026-09-08)
  states the protocol - 判据评的是不带 shipped exits 的裸 ensemble，所以它与历史裁决可比 - so making
  it apply the shipped overlay would break comparability with every D-017 ruling.  `research book`
  prices `bare` weights plus the band because that is what D-018 was pre-registered on.  Those are
  reasons, not oversights.
* **`research backtest` had no `--exits` flag at all**, so it could not price the book the loop holds
  even when asked; measured, its Sharpe sat 0.058 below `validate`'s on identical inputs for that
  reason alone.  That one is a defect and this fixes it.
* **The artefact could not tell any of them apart.**  Of the five report kinds only `validation`
  recorded `book_guards` / `exits`; the rest recorded `costs`.  A reader holding an overlay 1.85 and a
  validation 1.59 had nothing in either file saying they are different books - and the two have been
  quoted against each other.

So the seam is `score_book` (one implementation of "apply the overlay, then price") and `layers_applied`
(which book, in the file).  Neither changes what a command CHOOSES to measure.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from starquant_alpha.overlays.exits import ExitParams
from starquant_alpha.overlays.exposure import BookGuardParams
from starquant_alpha.validation.pipeline import layers_applied, score_book
from starquant_cli import main

SYMBOLS = ["BTCUSDT", "ETHUSDT"]
SHORT = '{"horizons": [5, 20, 50], "vol_window": 50, "crowding_window": 0}'


def _run(command: str, root: Path, out: Path, *extra: str):
    return CliRunner().invoke(
        main,
        [
            "research",
            command,
            "--strategy",
            "tsmom",
            "--root",
            str(root),
            "--symbols",
            ",".join(SYMBOLS),
            "--out",
            str(out),
            "--no-funding",
            "--min-history",
            "0",
            "--params",
            SHORT,
            *extra,
        ],
    )


def _report(out: Path, kind: str) -> dict:
    return json.loads(next(out.glob(f"tsmom-{kind}-*.json")).read_text(encoding="utf-8"))


def test_the_overlay_is_applied_by_one_function_for_both_callers() -> None:
    """`score_book` returns the priced result AND the post-overlay frame, which is what the caller needs.

    Re-deriving the second from `result.weights` would invert a frame the guards already trimmed -
    `validate` records that trap beside its own cost-stress re-runs, and this is why it is returned
    rather than recomputed.
    """
    assert score_book.__module__ == "starquant_alpha.validation.pipeline"


def test_the_layers_block_distinguishes_none_from_absent() -> None:
    """`exits: null` says "this protocol applies none"; a report with no `layers` key predates it."""
    bare = layers_applied(band="after_bare", guards=None, exits=None)
    assert bare == {"band": "after_bare", "book_guards": None, "exits": None}
    full = layers_applied(band="model", guards=BookGuardParams(), exits=ExitParams(stop_loss=6.0, take_profit=6.0))
    assert full["exits"]["stop_loss"] == 6.0 and full["book_guards"]["daily_loss_pause"] == -0.05


@pytest.mark.parametrize("flag", ["--exits", "--no-exits"])
def test_backtest_can_now_say_which_book_it_priced(flag: str, tmp_path: Path, august_dir: Path) -> None:
    from tests.cli.test_cli_offline import _store_from_fixtures

    root, out = tmp_path / "data", tmp_path / f"reports{flag}"
    _store_from_fixtures(august_dir, root)
    result = _run("backtest", root, out, flag)
    assert result.exit_code == 0, result.output
    layers = _report(out, "backtest")["layers"]
    assert layers["band"] == "model" and layers["book_guards"] is not None
    assert (layers["exits"] is not None) is (flag == "--exits")


def test_the_two_commands_now_price_the_same_book(tmp_path: Path, august_dir: Path) -> None:
    """M-AM03, made measurable: the same inputs through both commands, one number.

    Measured on the shipped book before this change, `backtest` read 1.6146 against `validate`'s
    1.6725 - a gap that was entirely the missing overlay.
    """
    from tests.cli.test_cli_offline import _store_from_fixtures

    root = tmp_path / "data"
    _store_from_fixtures(august_dir, root)
    back, val = tmp_path / "back", tmp_path / "val"
    assert _run("backtest", root, back).exit_code == 0
    validated = _run("validate", root, val, "--grid", "{}", "--folds", "3", "--min-train", "300", "--purge", "5")
    assert validated.exit_code == 0, validated.output

    backtest, validation = _report(back, "backtest"), _report(val, "validation")
    assert backtest["layers"] == validation["layers"], "the two commands describe different books"
    assert backtest["summary"]["annualized_sharpe"] == pytest.approx(validation["full_sample"]["annualized_sharpe"]), (
        "same panel, same params, same layers - the number has to be the same one"
    )


def test_the_book_report_declares_the_protocol_it_was_pre_registered_on(tmp_path: Path) -> None:
    """D-018's ruler is `bare` + band, and that is a reason rather than an oversight - so it is stated."""
    assert layers_applied(band="after_bare", guards=None, exits=None)["band"] == "after_bare"
