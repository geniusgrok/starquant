"""DL-G9: "the evidence was produced under the construction the loop holds" becomes a string comparison.

The Phase 0 replay suspended KILL-AR-07 for all 48 archived reports, and the reason was not strictness:
`cycles.jsonl` records a construction digest, a digest does not invert, and the startup heartbeat that
does hold the payload is overwritten by the next start.  `construction_problems` could answer the
question, but only at startup with the live config in hand - so a governance replay reading last
month's report had nothing to compare.

The fix is one digest over the intersection of what both sides can describe.  Deliberately not
`construction_fingerprint`: that covers throttle, leverage and `strategy_weights`, which a backtest has
no opinion about, so a "matching digest" built from it would be a rule that always fails.

What this file holds is the part that would rot silently: the live blocks are built from a parsed
`LiveConfig` in the engine while the startup gate builds them from the raw profile mapping in
`starquant_live.config`, and two functions producing "the same" dict is exactly how a comparison starts
passing for the wrong reason.
"""

from __future__ import annotations

import yaml

from starquant_alpha.registry import CONSTRUCTION_KEYS, evidence_construction_digest
from starquant_live.config import live_overlay_blocks
from starquant_live.engine import evidence_construction, evidence_construction_of
from tests.live.helpers_construction import ROOT, live_config_for_profile


def _profile() -> dict:
    return yaml.safe_load((ROOT / "config" / "live.demo.yaml").read_text(encoding="utf-8"))


def test_the_two_builders_of_the_live_blocks_agree() -> None:
    """The engine reads a parsed config, the gate reads the raw profile; they must say the same thing."""
    from_engine = evidence_construction(live_config_for_profile())
    from_profile = live_overlay_blocks(_profile())
    assert from_engine["book_guards"] == from_profile["book_guards"]
    assert from_engine["exits"] == from_profile["exits"]


def test_the_portfolio_block_covers_exactly_what_the_gate_compares() -> None:
    """Neither more nor less: a key the gate ignores would make the digest stricter than the rule."""
    assert set(evidence_construction(live_config_for_profile())["portfolio"]) == set(CONSTRUCTION_KEYS)


def test_a_report_and_the_loop_produce_the_same_digest_from_the_same_construction() -> None:
    """The whole point.  A report writes this over its own blocks; the loop over its config."""
    blocks = evidence_construction(live_config_for_profile())
    as_a_report_would = evidence_construction_digest(blocks["portfolio"], blocks["book_guards"], blocks["exits"])
    assert evidence_construction_of(live_config_for_profile()) == as_a_report_would


def test_a_band_change_moves_the_digest() -> None:
    """If it did not, the whole mechanism would be decoration: P10 cell B is the case it exists for."""
    blocks = evidence_construction(live_config_for_profile())
    widened = {**blocks["portfolio"], "no_trade_rel_band": 0.99}
    assert evidence_construction_digest(widened, blocks["book_guards"], blocks["exits"]) != evidence_construction_of(
        live_config_for_profile()
    )


def test_no_exit_layer_is_a_statement_not_an_absence() -> None:
    """`None` says "this ran no such layer"; an empty mapping would say "it ran one with nothing in it"."""
    portfolio = dict.fromkeys(CONSTRUCTION_KEYS, 1.0)
    assert evidence_construction_digest(portfolio, {}, None) != evidence_construction_digest(portfolio, {}, {})
