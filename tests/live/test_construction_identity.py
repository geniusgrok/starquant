"""When the fingerprint's own definition grows, that is not the book changing (2026-09-07).

Restart #5 recorded a new construction digest while the book was byte-identical.  The cause was the P22
merge adding a 23rd field, `exits.unit_mode`, to the payload `construction_fingerprint` hashes: adding a
key changes the hash even when every value is unchanged.  Proved by recomputing both field sets against
the same live config - 22 fields reproduce `0dcd044d...` exactly, 23 fields reproduce `b441ea62...`
exactly.  `unit_mode` BELONGS in the fingerprint (it decides what the exit overlay does - KILL-R14's
7-of-18 unplaceable stops are that setting), so the field is right and the silence was the defect:
`evidence_window` dropped from three days to one bar with nothing saying why.

Two mechanisms, decided by the operator on 2026-09-07:

* **A version on the payload**, reported OUTSIDE the hash.  Outside matters: inside, adding the version
  would itself change today's digest, which is the very thing being fixed.  Outside, a reader comparing
  two rows can see whether the FIELD SET differed, and a bump is now the explicit signal that a digest
  change may be definitional rather than real.
* **An alias table**, in code rather than config, so declaring two digests to be the same book takes a
  commit that carries the proof.  History is never rewritten - the old rows keep the digest they were
  written with, and the equivalence lives in the reader.
"""

from __future__ import annotations

from starquant_live.construction import (
    CONSTRUCTION_ALIASES,
    CONSTRUCTION_PAYLOAD_VERSION,
    canonical_construction,
)

BEFORE = "0dcd044d0158c6aec263429eab9cdba9449dba0b55b07807dfd0e3d3a3a9b6e0"
AFTER = "b441ea62d02184bfb6292ec1033f20482bc9c7c0a2c6ebfcc14623241b967417"
AFTER_P23 = "c0e5c49c5a4acb1d0e5bb709873ce38b0674c10a027405d5269dbb724d734d1c"
AFTER_MIN_HISTORY = "dd32720d3faf5ab0e6a2934a76e9d26489095d7b5a7d19d537bcef44751a7cf6"
AFTER_P30 = "ab3cb75fb2f8d94813aa44c5b6d869c34bf82bcc78757bf1fcfa0bba4e16e1b3"


def test_the_restart_5_digest_resolves_to_the_book_it_actually_is() -> None:
    assert canonical_construction(AFTER) == BEFORE


def test_an_undeclared_digest_is_returned_unchanged() -> None:
    """Silence means "different book"; only a written declaration makes two digests one."""
    assert canonical_construction("f" * 64) == "f" * 64
    assert canonical_construction(BEFORE) == BEFORE


def test_no_alias_points_at_something_that_is_itself_aliased() -> None:
    """A chain would make the canonical form depend on resolution order, which is a silent wrong answer."""
    for target in CONSTRUCTION_ALIASES.values():
        assert target not in CONSTRUCTION_ALIASES


def test_a_missing_digest_does_not_become_the_string_none() -> None:
    assert canonical_construction(None) is None


def test_the_payload_version_is_reported_outside_the_hash() -> None:
    """Structural, not a pinned literal: the digest must equal the hash of everything BUT the version."""
    import hashlib
    import json

    from starquant_live.engine import construction_fingerprint
    from tests.live.helpers_construction import live_config_for_profile

    out = construction_fingerprint(live_config_for_profile())
    hashed = {k: v for k, v in out.items() if k not in ("digest", "payload_version")}
    expected = hashlib.sha256(json.dumps(hashed, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    assert out["payload_version"] == CONSTRUCTION_PAYLOAD_VERSION
    assert out["digest"] == expected, "payload_version leaked into the hashed payload"


# The field set, written down.  This is the part that makes the next addition LOUD: twice in one day a
# merge added fields (P22's `unit_mode`, P23's four `regime_*`), each time moving the digest while the
# book was byte-identical, and each time `evidence_window` read it as a construction change and reset
# M-010.  Nothing failed, so nobody knew.  Now adding or removing a key fails here, and the fix is to
# bump CONSTRUCTION_PAYLOAD_VERSION and decide - in writing - whether the book actually changed.
EXPECTED_FIELDS = {
    "portfolio": {
        "vol_target",
        "vol_halflife",
        "covariance_halflife",
        "min_asset_vol",
        "max_scalar",
        # v4 (2026-09-09): it decides WHICH SYMBOLS may be held, so it decides the book.
        "min_history_bars",
        "sleeve_max_gross",
    },
    "guards": {"max_gross", "max_weight", "daily_loss_pause", "stale_bars_max"},
    # v6: what the loop does when a symbol's bars do not arrive.  Not a portfolio parameter and not a
    # guard - it decides whether a position survives an empty REST answer - so it gets its own block
    # rather than being filed under one of theirs.
    "inputs": {"dropped_after"},
    "rebalance": {
        "no_trade_band",
        "no_trade_rel_band",
        "max_participation",
        "max_order_notional",
        "exempt_reductions",
        # v7, 2026-09-14.  Both SHIPPED False, both were asserted bit-identical off, and
        # CONSTRUCTION_ALIASES carries the declaration - the book did NOT change then.  Both ship True
        # from 2026-09-17; the v7 aliases stay, because they describe the digests the loop actually
        # wrote while the values were still False, and history is not rewritten.
        "exempt_crossings",
        "flat_inside_band",
        # v9, 2026-09-17 (D3).  The only field in this table whose arrival coincided with the book
        # changing, so it has deliberately NO alias - the note in `construction.py` says why.
        "band_entry_multiple",
    },
    "exits": {
        "stop_loss",
        "trailing_stop",
        "take_profit",
        "cooldown_bars",
        "vol_halflife",
        "unit_mode",
        "regime_window",
        "regime_er_cut",
        "regime_tp_scale",
        "regime_side",
        "stale_carry_bars",
        # v8, 2026-09-17 (EXP-AE3): ships 0.0, which is "arm from entry" - today's behaviour - and
        # CONSTRUCTION_ALIASES carries the recomputation showing the book did NOT change.
        "trailing_activate",
        # v10, 2026-09-17 (EXP-SL1): ships 0.0, which is "no price cap" - today's behaviour - and
        # CONSTRUCTION_ALIASES carries the recomputation showing the book did NOT change.
        "stop_loss_price_cap",
    },
    "throttle": {"enabled", "start", "stop", "floor"},
    "leverage": {"mode", "margin_cap", "max_leverage", "margin_buffer"},
}


def test_changing_the_hashed_field_set_fails_here_instead_of_silently_resetting_m010() -> None:
    from starquant_live.engine import construction_fingerprint
    from tests.live.helpers_construction import live_config_for_profile

    out = construction_fingerprint(live_config_for_profile())
    actual = {k: set(v) for k, v in out.items() if isinstance(v, dict) and k != "strategy_weights"}
    assert actual == EXPECTED_FIELDS, (
        "the construction fingerprint's field set moved.  That changes the digest even when every value "
        "is identical, and evidence_window reads a changed digest as a changed book - it reset M-010 "
        "twice on 2026-09-07 this way.  Bump CONSTRUCTION_PAYLOAD_VERSION, update EXPECTED_FIELDS, and "
        "say in the commit whether the BOOK changed; if it did not, add a CONSTRUCTION_ALIASES entry."
    )


def test_every_definitional_digest_so_far_resolves_to_the_one_book() -> None:
    """v1 22 fields, v2 +unit_mode, v3 +4 regime_*, v4 +min_history_bars, v5 +sleeve_max_gross.

    One book, measured five ways.  Every one of the four additions was a field the record needed and a
    value that had not moved; the alias is what keeps "the fingerprint learned to say something" from
    reading as "the book changed".
    """
    for digest in (BEFORE, AFTER, AFTER_P23, AFTER_MIN_HISTORY, AFTER_P30):
        assert canonical_construction(digest) == BEFORE


#: v7, what the armed loop has recorded since `vol_target` went to 0.60, and v8, what it will record
#: once `exits.trailing_activate` exists.  Both resolve to the FROZEN construction rather than to
#: `BEFORE`: 2026-09-13's target change is a real one, and the freeze is pinned to what came after it.
AFTER_V7 = "ccd7bb9764b5fe0cf170f4943fedeb67ca8ec39a790903ec649ef7705d1d82f2"
AFTER_TRAILING_ACTIVATE = "d995e0cce6af69ddd839cdba4f44c4e895e37167f9fbc1235892c2e4b2786cca"
FROZEN = "46b8d731530a2f2375f816a1de69e4c357e41a682816c4d947832617550d2a10"

#: v9, D1+D2+D3 (2026-09-17).  **Not an alias of `FROZEN` and not declared as one.**  Every digest above
#: this line is the same book measured with a longer ruler; this one is a different book, because the
#: same commit that added `band_entry_multiple` turned `exempt_crossings` and `flat_inside_band` on.
#: It is pinned here for the same reason the others are - so the next field-set change fails a test
#: instead of moving it silently - and NOT in `CONSTRUCTION_ALIASES`, so M-010's window restarts.
SHIPPED_D3 = "0c555e1c837e342a8af1edca0089b12461a9bdbe3b9a0f122142c63d6ba54bd7"

#: v10 (+ `exits.stop_loss_price_cap`), EXP-SL1.  Inert at 0.0, so unlike `SHIPPED_D3` it IS an
#: alias of the line above - declared before the loop ever writes it, same as v3-v8.
AFTER_PRICE_CAP = "b8f215ab706ca7c472028d109f96f9fbb911097a9a16bb4b6fb9dee9ec5b528a"


def test_the_definitional_digests_since_the_freeze_resolve_to_the_frozen_book() -> None:
    """The freeze test compares the CANONICAL digest, so a field set that grows must not trip it.

    Declared before either digest is ever written, which is the order every entry in the table uses:
    the claim is about values that are already known not to have moved.
    """
    for digest in (AFTER_V7, AFTER_TRAILING_ACTIVATE):
        assert canonical_construction(digest) == FROZEN


def test_the_shipped_construction_is_the_new_book_and_says_so() -> None:
    """D1+D2+D3 is a construction CHANGE, so the shipped digest must NOT resolve to the frozen one.

    This assertion is inverted from the one it replaces, and the inversion is the record: until
    2026-09-17 every digest this tree could compute was the frozen book seen through a longer field
    set, and the test said so by resolving to `FROZEN`.  Turning the three band knobs on ends that.
    Asserting the inequality rather than deleting the test is what keeps a future alias - which would
    quietly re-declare the two to be one book - from passing unnoticed.
    """
    from starquant_live.engine import construction_fingerprint
    from tests.live.helpers_construction import live_config_for_profile

    digest = construction_fingerprint(live_config_for_profile())["digest"]
    assert digest == AFTER_PRICE_CAP, digest
    assert canonical_construction(digest) == SHIPPED_D3, "v10 是惰性字段，必须解析回 D3 那本账"
    assert canonical_construction(digest) != FROZEN


# --- the readers.  A canonicaliser nothing calls leaves M-010 reset exactly as before ----------------


def _rows(digests, start_ms=1_788_000_000_000, step=3_600_000):
    return [
        {"bar_open_ms": start_ms + i * step, "construction": d, "equity": 10_000.0 + i} for i, d in enumerate(digests)
    ]


def test_the_evidence_window_reaches_back_through_a_declared_alias(tmp_path) -> None:
    """The whole point of the ruling: M-010's window continues across restart #5 instead of restarting."""
    import json

    from starquant_live.reports import evidence_window
    from starquant_live.state import StateStore

    store = StateStore(tmp_path / "live")
    with store.cycles_path.open("w", encoding="utf-8") as handle:
        for row in _rows([BEFORE] * 5 + [AFTER] * 2):
            handle.write(json.dumps(row) + "\n")
    out = evidence_window(store)
    assert out["bars"] == 7, "the window stopped at the alias boundary"
    assert out["changes_7d"] == 0, "a definitional change was counted as a construction change"


def test_a_genuinely_different_construction_still_cuts_the_window(tmp_path) -> None:
    """The alias must not become a blanket amnesty: an undeclared digest still ends the window."""
    import json

    from starquant_live.reports import evidence_window
    from starquant_live.state import StateStore

    store = StateStore(tmp_path / "live")
    with store.cycles_path.open("w", encoding="utf-8") as handle:
        for row in _rows(["a" * 64] * 5 + [AFTER] * 2):
            handle.write(json.dumps(row) + "\n")
    assert evidence_window(store)["bars"] == 2
    assert evidence_window(store)["changes_7d"] == 1


def test_realised_vol_does_not_refuse_over_a_definitional_change() -> None:
    """`realised_vol` gives up when the window spans two constructions - it must not see two here."""
    from starquant_live.risk_budget import RiskBudgetParams, realised_vol

    rows = _rows([BEFORE] * 300 + [AFTER] * 300)
    out = realised_vol(rows, RiskBudgetParams(min_vol_bars=10))
    assert out["enforced"] is True, out.get("why")
