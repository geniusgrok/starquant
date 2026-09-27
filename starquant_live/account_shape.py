"""KILL-R19: refuse to trade an account whose risk model is not the validated one.

The engine makes two account-shape refusals at startup, in the same place and - as `engine.py` says of
the second - "the same shape as the first": hedge (dual-side) mode, and the margin mode this module
judges.  Both ask whether the account the loop is about to trade is the account the evidence describes.

Split out of ``health.py`` in 2026-09-15.  It had been sitting between a liquidation metric and a table
of construction digests, under a module name that suggested neither.
"""

from __future__ import annotations

from collections.abc import Sequence


def margin_mode_problems(
    *, multi_assets: bool, isolated_symbols: Sequence[str], expect_multi_assets: bool
) -> list[str]:
    """KILL-R19: refuse to trade an account whose risk model is not the validated one.

    Asserts only.  Changing an account's margin mode under an open book is an operator action with
    consequences the loop cannot evaluate, so this reports and stops; it never sets.
    """
    problems: list[str] = []
    for symbol in isolated_symbols:
        problems.append(
            f"{symbol} is on ISOLATED margin; the book is sized and validated for CROSSED, and isolated "
            "margin manufactures liquidations the strategy never asked for (report 7.3(a))"
        )
    if bool(multi_assets) != bool(expect_multi_assets):
        problems.append(
            f"multiAssetsMargin is {multi_assets} but the profile expects {expect_multi_assets}; equity that "
            "floats with collateral prices is a different book from the one the evidence describes"
        )
    return problems
