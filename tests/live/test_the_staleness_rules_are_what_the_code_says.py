"""`staleness.RULES` is a claim about five other modules, so it gets a test rather than trust.

The prose it replaces had already gone stale once: `exits.py` still said `stale_carry_bars` was "not
yet in `construction_fingerprint`" after v6 put it there.  A table of settings that nothing checks
becomes wrong the same way, just more legibly, so each row is joined to the code it names.

The divergence itself is pinned too - not to bless it, but so that closing it is a decision somebody
takes rather than something that drifts shut and nobody notices.
"""

from __future__ import annotations

from starquant_alpha.overlays.exits import ExitParams
from starquant_alpha.overlays.exposure import BookGuardParams
from starquant_live.engine import LiveConfig
from starquant_live.guards import GuardParams
from starquant_live.staleness import RULES, Rule, rules_binding


def _rule(name: str) -> Rule:
    (found,) = [rule for rule in RULES if rule.name == name]
    return found


def test_every_named_setting_exists_where_the_table_says_it_does() -> None:
    """A row naming a setting that has been renamed or deleted is the stale comment, one layer up."""
    owners = {
        "starquant_alpha.overlays.exits": ExitParams,
        "starquant_live.engine": LiveConfig,
        "starquant_live.guards": GuardParams,
        "starquant_live.exits": None,  # the rule there is a branch, not a setting
    }
    for rule in RULES:
        assert rule.module in owners, f"{rule.name} names an unknown module {rule.module}"
        owner = owners[rule.module]
        if owner is None or rule.setting == "(none)":
            continue
        assert rule.setting in owner.__dataclass_fields__, (
            f"{rule.name} names {rule.module}.{rule.setting}, which does not exist"
        )


def test_the_two_halves_still_disagree_and_the_table_says_so() -> None:
    """The finding, as an executable statement.

    If this ever fails, the divergence closed - which is good, and which must be accompanied by the
    priced decision `construction.py`'s v6 note reserves, not discovered afterwards in a diff.

    2026-09-17: the intersection is now EMPTY, and that is a correction rather than a change.  This
    line read `== {"skip the whole cycle"}` because the table claimed that rule bound on both sides;
    it never did (`_replay_book_guards` has no staleness branch), so the assertion was pinning the
    wrong entry rather than catching it.  Not one of these five rules has both halves - which sharpens
    the module's own finding instead of softening it.
    """
    research = {rule.name for rule in rules_binding("research")}
    live = {rule.name for rule in rules_binding("live")}

    assert "carry through gaps" in research and "carry through gaps" not in live
    assert "hold, then flatten" in live and "hold, then flatten" not in research
    assert not research & live, "no staleness rule runs on both sides; a new one doing so is news"


def test_the_shipped_numbers_are_the_ones_the_table_was_written_against() -> None:
    """The values the operator chose, pinned where a reader of the table can see them."""
    assert ExitParams().stale_carry_bars == 2
    assert GuardParams().stale_bars_max == 2
    assert LiveConfig.__dataclass_fields__["dropped_after"].default == 1


def test_dropped_after_at_one_means_the_live_hold_is_zero_cycles() -> None:
    """Why the live half never carries, stated as arithmetic rather than left to be re-derived.

    `_hold_dropped` holds while `streak < dropped_after` and the streak starts at 1, so at 1 the
    condition is `1 < 1` and nothing is ever held.  That is the visible behaviour the operator picked;
    the test exists so raising the number reads as the book change it is.
    """
    dropped_after = LiveConfig.__dataclass_fields__["dropped_after"].default
    first_cycle_streak = 1

    assert not (first_cycle_streak < dropped_after)


def test_every_rule_says_which_side_it_binds_on() -> None:
    for rule in RULES:
        assert rule.binds in {"research", "live", "both"}, f"{rule.name} has no side"
        assert rule.note.strip(), f"{rule.name} has no note, so the table is a list of names"


def test_a_rule_that_claims_a_research_half_has_one() -> None:
    """The check the spelling test above cannot make: is the claimed side true?

    `skip the whole cycle` read `binds="both"` until 2026-09-17 on the strength of D-036 sharing the
    BOOK guards with the backtest replay.  It was never one of them - `_replay_book_guards` replays
    the caps and the daily-loss pause, and `BookGuardParams` is that shared definition - so the table
    asserted a research half that does not exist, and passed, because the only test on `binds` asked
    whether the word was one of three strings.

    Research runs `starquant_alpha`, so a rule binding there has to be a setting `starquant_alpha` can read.
    That is a weaker statement than "the replay honours it" and it is checkable without importing the
    replay's internals, which is what makes it a test rather than a second copy of the table.
    """
    alpha_side = set(ExitParams.__dataclass_fields__) | set(BookGuardParams.__dataclass_fields__)

    for rule in RULES:
        if rule.binds not in {"research", "both"}:
            continue
        assert rule.setting in alpha_side, (
            f"{rule.name!r} claims to bind on the research side, but {rule.setting!r} is not a field "
            f"of any starquant_alpha parameter object - so nothing in a backtest can read it"
        )

    # ...and the correction itself, pinned so it cannot quietly revert.
    assert _rule("skip the whole cycle").binds == "live"
    assert "stale_bars_max" not in set(BookGuardParams.__dataclass_fields__)
