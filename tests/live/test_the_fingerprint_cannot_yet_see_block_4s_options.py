"""D-026 gap, recorded rather than assumed away: `vol_model` and `budget_mode` move no digest.

`construction_fingerprint` enumerates its keys by hand, so a `PortfolioParams` field it does not name
changes every weight in the book while the running record keeps saying the construction is unchanged.
That is exactly the silence D-026 was written to end - and the one it was itself caught leaving open
once, when `LiveConfig` did not carry `vol_target` and P13 could have doubled the risk budget without
moving the digest.

Block 4's two options (#35 GARCH divisor, #48 HRP budget) are built off by default in `starquant_alpha`,
so nothing live reads them today and the gap is harmless *while they are off*.  Naming them in the
fingerprint is a `starquant_live` change, which belongs to the Phase 4a batch that turns one of them on
(restart, and M-010's 30-day window back to zero) rather than to building them.

This test therefore asserts the gap is still there, in the shape `test_source_budget` uses for the line
budget: closing it makes this test fail, and the failure says what to delete.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from starquant_alpha.portfolio import PortfolioParams
from starquant_live.engine import construction_fingerprint
from tests.live.test_live_loop import _config


def test_switching_the_divisor_or_the_budget_does_not_move_the_construction_digest(tmp_path: Path) -> None:
    base = _config(tmp_path)
    digest = construction_fingerprint(base)["digest"]
    for option in ({"vol_model": "garch"}, {"budget_mode": "hrp"}, {"budget_mode": "inverse_variance"}):
        switched = replace(base, portfolio=replace(base.portfolio, **option))
        assert switched.portfolio != base.portfolio, "the option must actually differ"
        assert construction_fingerprint(switched)["digest"] == digest, (
            f"{option} now moves the digest - delete this test and keep the fingerprint change"
        )
    # The control: something the fingerprint DOES name still moves it, so a digest that stopped
    # responding to anything at all would not read as a pass here.
    louder = replace(base, portfolio=replace(base.portfolio, vol_target=base.portfolio.vol_target * 2))
    assert construction_fingerprint(louder)["digest"] != digest


def test_the_options_are_config_reachable_so_phase_4a_is_an_edit_and_not_a_patch() -> None:
    """The other half of the same contract: the gap above is the only thing missing.

    Adopting either option must not require touching code under time pressure, so the profile's
    `portfolio` block has to reach them through `from_mapping` - which is what `portfolio_params` calls.
    """
    from starquant_live.composition import portfolio_params

    params = portfolio_params({"portfolio": {"vol_target": 0.30, "vol_model": "garch", "budget_mode": "hrp"}})
    assert (params.vol_model, params.budget_mode, params.vol_target) == ("garch", "hrp", 0.30)
    assert portfolio_params({"portfolio": {}}) == PortfolioParams()
