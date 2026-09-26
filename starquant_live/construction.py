"""D-026: when the construction fingerprint's DEFINITION changes, and what that must not reset.

`construction_fingerprint` answers "is this the same book?".  Two things here keep that answer honest
across changes to the question: a version for the field set being hashed, reported outside the hash so
bumping it cannot move the digest it explains, and the aliases an operator has declared to mean the
same book.

Split out of ``health.py`` in 2026-09-15.  The table lived there for one reason - `engine.py` would
have imported it circularly - which is a module chosen by an import graph rather than by a concept, and
it is why answering "did the construction change?" meant bouncing between five modules.  A module of
its own has no cycle to dodge: nothing here imports the engine.
"""

from __future__ import annotations

# The field set `construction_fingerprint` hashes.  Bumped whenever a key is added or removed, and
# reported OUTSIDE the hash so that bumping it does not itself move the digest - inside, the version
# would change the very number it exists to explain.
#   1: the original 22 fields
#   2: + `exits.unit_mode` (P22).  The field is right - it decides what the exit overlay does, and
#      KILL-R14's 7-of-18 unplaceable stops are that setting - but adding it moved the digest while the
#      book was byte-identical, and `evidence_window` read that as a construction change.
#   3: + the four `exits.regime_*` (P23), the same day and the same way.  Inert at the shipped config:
#      `regime_window` defaults to 0 and `regime_tp_scale()` returns None at <= 0, and the profile sets
#      none of the four - so again the values are unchanged and only the shape moved.  Twice in one day
#      is why `test_construction_identity` now pins the field set: the next one fails a test instead.
#   8: + `exits.trailing_activate` (EXP-AE3, 2026-09-17).  The activation threshold the operator's
#      "移动止盈" needs and the repository did not have: `trailing_stop` alone measures the retracement
#      from an `extreme` initialised to the ENTRY price, so it fires while a position is still losing.
#      Ships at 0.0, which arms from entry - today's behaviour exactly - and `_armed` returns True
#      before reading the excursion at all, so the two engines stay bit-identical and only the shape of
#      what is hashed moved.
#   4: + `portfolio.min_history_bars` (2026-09-09).  Inert at the shipped config for the same reason
#      the two above were: the value is 720 before and after, and only the shape of what is hashed
#      moved.  It belongs in the digest because `AlphaModel.eligible` uses it to decide WHICH SYMBOLS
#      may be held at all, so changing it changes the book - found while asking whether the
#      new-listing strategy (#27) could be implemented, which it cannot without lowering this.
#   9: + `rebalance.band_entry_multiple` (D3, 2026-09-17).  **The first bump in this list with no
#      alias, and the only one whose commit also changed values.**  Every entry above says the same
#      sentence - the field arrived inert, so the digest moved while the book did not - and each one
#      earned an alias by it.  This commit turns `exempt_crossings` and `flat_inside_band` on in the
#      same breath, so that sentence is false here: the book changed, the digest is supposed to move,
#      and M-010's window is supposed to restart.  A bump still belongs, because a reader comparing two
#      rows across it needs to know the FIELD SET differs as well as the values.
#  10: + `exits.stop_loss_price_cap` (EXP-SL1, 2026-09-17).  **Back to the v3-v8 shape, and the contrast
#      with v9 one line up is the point.**  The field arrives at 0.0, `_stop_threshold` returns
#      `stop_loss` untouched before any arithmetic runs, and the two exit engines were re-checked
#      against each other with the cap both off and on - so the book is byte-identical and the alias
#      below says so.  Turning the cap ON later is a separate decision, gated by K-EX14 until the
#      current window matures; it would be a real construction change with no alias, exactly like v9.
CONSTRUCTION_PAYLOAD_VERSION = 10

# Digests the operator has declared to be the SAME BOOK as an earlier one.  In code rather than config
# because the declaration is a claim about evidence: it takes a commit, and the commit carries the proof.
#
# 2026-09-07, restart #5.  Recomputing both field sets against the one live config reproduced both
# digests exactly - 22 fields -> 0dcd044d..., 23 fields -> b441ea62... - so no construction VALUE
# changed, only the shape of what was hashed.  Operator ruled the pre-15:00Z rows are the same
# construction, so M-010's window continues across the boundary instead of restarting.
#
# History is not rewritten: the old rows keep the digest they were written with.  The equivalence lives
# here, in the reader, where it can be read and argued with.
CONSTRUCTION_ALIASES: dict[str, str] = {
    # v2 (+ unit_mode), recorded by the running loop from restart #5.
    "b441ea62d02184bfb6292ec1033f20482bc9c7c0a2c6ebfcc14623241b967417": (
        "0dcd044d0158c6aec263429eab9cdba9449dba0b55b07807dfd0e3d3a3a9b6e0"
    ),
    # v3 (+ the four regime_*), what the next restart will record.  Declared before it is ever written,
    # which is the right order: the claim is about values that are already known to be unchanged.
    "c0e5c49c5a4acb1d0e5bb709873ce38b0674c10a027405d5269dbb724d734d1c": (
        "0dcd044d0158c6aec263429eab9cdba9449dba0b55b07807dfd0e3d3a3a9b6e0"
    ),
    # v4 (+ portfolio.min_history_bars), 2026-09-09.  Declared before it is ever written, same as v3,
    # and on the same proof: recomputed against the shipped config the value is 720 on both sides of
    # the change, so only the shape of what is hashed moved.  Without this alias the next restart would
    # reset M-010's 30-day window - which has been running unbroken since 2026-09-04T15:02Z - for a
    # book that is byte-identical.
    "dd32720d3faf5ab0e6a2934a76e9d26489095d7b5a7d19d537bcef44751a7cf6": (
        "0dcd044d0158c6aec263429eab9cdba9449dba0b55b07807dfd0e3d3a3a9b6e0"
    ),
    # v5 (+ portfolio.sleeve_max_gross), 2026-09-12 (P30).  Declared before it is ever written, on the
    # same proof as v3 and v4: recomputed against the shipped profile the value is 0.0 on both sides of
    # the change - the profile does not name the key and 0.0 is off - so only the shape of what is
    # hashed moved.  `cap_gross(x, 0.0)` returns `x` and the main book is passed 0.0 regardless, which a
    # test asserts on the two-book path rather than leaving to this comment.  Without the alias the next
    # restart would reset M-010's window for a book that is byte-identical.
    "ab3cb75fb2f8d94813aa44c5b6d869c34bf82bcc78757bf1fcfa0bba4e16e1b3": (
        "0dcd044d0158c6aec263429eab9cdba9449dba0b55b07807dfd0e3d3a3a9b6e0"
    ),
    # v6 (+ rebalance.exempt_reductions, + exits.stale_carry_bars, + inputs.dropped_after), 2026-09-13.  Declared before it is ever written, on the same
    # proof as v3, v4 and v5: the shipped profile does not name the key and False is off, so recomputed
    # against it the value is False on both sides of the change and only the shape of what is hashed
    # moved.  What `False` means is the literal previous expression - the participation cap exempts a
    # full close and nothing else - which the rebalancer and the backtest replay both assert rather
    # than leaving to this comment.  `stale_carry_bars` rides the same version and the same proof by a
    # different route: it is inert on the LIVE path, because `ExitOverlay.apply` skips a symbol whose
    # close is missing before `exit_step` is reached, so the live construction is unchanged whatever
    # the value reads.  `dropped_after` is the third, and it is the one that had to be MADE true: the
    # rule it names - hold a symbol whose bars did not arrive, rather than flattening and re-opening
    # it next cycle - shipped at 3, which is a different book.  It ships at 1 instead, which is the
    # behaviour it was written to make visible, so the proof reads the same way as the other two and
    # raising it stays a priced decision rather than a side effect of deploying a fix.  Without the
    # alias the next restart would reset M-010's 30-day window, unbroken since 2026-09-04T15:02Z,
    # for a book that is byte-identical.
    "18b8b20fb6273b90070cff33a06dff62da98de5e7eebdfef51990ac372c55b85": (
        "0dcd044d0158c6aec263429eab9cdba9449dba0b55b07807dfd0e3d3a3a9b6e0"
    ),
    # v7 (+ rebalance.exempt_crossings, + rebalance.flat_inside_band), 2026-09-14.  The first alias
    # whose target is NOT `0dcd044d...`: vol_target went 0.30 -> 0.60 on 2026-09-13 (72034790), which
    # is a real construction change, and `46b8d731...` is what the armed loop has recorded since.
    #
    # Declared before either key is ever written, on the same proof as v3-v6: the shipped profile
    # names neither and False is off for both, so recomputed against it the values are False on both
    # sides and only the shape of what is hashed moved.  Both Falses are the literal previous
    # expression and both are asserted rather than argued here -
    # `test_the_shipped_default_is_todays_live_book_not_the_backtests` pins that the band still
    # swallows a close to zero, and `test_the_shipped_default_still_creates_the_stub` replays the
    # 2026-09-14T10:00Z fill that left -11.19 USDT of ENAUSDT standing.
    #
    # This alias carries more weight than its predecessors: since 2026-09-14 the construction is
    # frozen to 2026-10-13T19:00Z, so without it the next restart would not merely reset M-010's
    # window, it would break an operator ruling.  Which is also the reason both knobs ship off:
    # turning either ON is a construction change and belongs to the operator, after the freeze.
    "ccd7bb9764b5fe0cf170f4943fedeb67ca8ec39a790903ec649ef7705d1d82f2": (
        "46b8d731530a2f2375f816a1de69e4c357e41a682816c4d947832617550d2a10"
    ),
    # v8 (+ exits.trailing_activate), 2026-09-17, on the same proof as v3-v7 and recomputed in the
    # commit that adds it: drop the one new key from the v8 payload and the hash comes back
    # `ccd7bb97...` exactly - which this table already declares to be `46b8d731...`.  The shipped
    # profile names no such key, 0.0 arms the trailing stop from entry (what the overlay has always
    # done), and `_armed` short-circuits on `<= 0` before reading anything, so both engines are
    # bit-identical across the addition and only the shape of what is hashed moved.
    #
    # It carries the same weight v7 does and for the same reason: the construction is frozen to
    # 2026-10-13T19:00Z, so without this entry the next restart would not merely reset M-010's window,
    # it would break an operator ruling and turn `test_the_construction_is_frozen_until_the_holdout_matures`
    # red for a book that has not moved.  Which is also why the knob ships at 0: turning it on is a
    # construction change, it belongs to the operator, and EXP-AE3 is the evidence it would need.
    "d995e0cce6af69ddd839cdba4f44c4e895e37167f9fbc1235892c2e4b2786cca": (
        "46b8d731530a2f2375f816a1de69e4c357e41a682816c4d947832617550d2a10"
    ),
    # v10 (+ exits.stop_loss_price_cap), EXP-SL1, 2026-09-17.  The second alias whose target is not
    # `0dcd044d...` and the first whose target is `0c555e1c...`: D3 (PR #53) turned the three band
    # knobs on that same day, which is a real construction change, and `0c555e1c...` is what the armed
    # loop has recorded since 16:07:34Z.
    #
    # Declared before it is ever written, on the same proof as v3-v8 and explicitly NOT on v9's: the
    # shipped profile does not name the key, 0.0 is off, and `_stop_threshold` returns `stop_loss`
    # untouched before touching `entry_price` at all - so recomputed against the shipped profile the
    # value is unchanged on both sides and only the shape of what is hashed moved.  The vectorised
    # engine takes the same short circuit, and `test_the_vectorised_exit_engine_is_the_same_machine`
    # now carries three cap settings (off, binding, never-binding) so the agreement is checked with
    # the branch live rather than only around it.
    #
    # The knob ships at 0 for the reason `trailing_activate` does: turning it on IS a construction
    # change, it belongs to the operator, and K-EX14 holds it until the window that started at
    # 16:07:34Z matures on 2026-10-17.  What it would buy and cost is measured in `docs/RESEARCH_LOG.md`
    # the same day - at c=0.9 it moves 48 symbol-bars of one symbol in 5.7 years, and the long stop it
    # makes reachable still needs a 90% fall to fire.
    "b8f215ab706ca7c472028d109f96f9fbb911097a9a16bb4b6fb9dee9ec5b528a": (
        "0c555e1c837e342a8af1edca0089b12461a9bdbe3b9a0f122142c63d6ba54bd7"
    ),
}


def canonical_construction(digest: str | None) -> str | None:
    """The digest a row's construction should be COMPARED as.

    One hop only, never a chain: a chain would make the answer depend on resolution order, and a test
    holds every alias target out of the table's own keys so the single hop is always enough.
    """
    if digest is None:
        return None
    return CONSTRUCTION_ALIASES.get(str(digest), str(digest))
