"""The miner's summary printed how many candidates failed and not one word of why.

That is what let the DL-D4 gap survive two full rounds on 2026-09-09.  Each failed row carried its own
reason - `error: "ExprError: long/short ratio needs panel.metrics[...], which this panel does not
carry"` - and the summary said `90 candidate(s) could not be evaluated; see the report`.  90 of 658 is
a perfectly plausible number for a search rejecting malformed combinations, which this search does
legitimately, so nothing looked wrong.  A whole family that could not run read as a family that ran and
lost, and the person who wrote "only the count reaches the report" was the same person who then read
only the count.

The property is not "the miner works".  It is that a refusal count is never printed alone.
"""

from __future__ import annotations

import inspect

from starquant_cli import research_cmd


def _code_after(marker: str, width: int = 1200) -> str:
    """The block's CODE, with comments stripped.

    The first version of this test asserted that the forbidden phrase was absent from the raw source,
    and went red on the comment that quotes the phrase in order to explain it.  A source assertion that
    cannot tell code from prose is not asserting about behaviour.
    """
    source = inspect.getsource(getattr(research_cmd.research_mine, "callback", research_cmd.research_mine))
    block = source[source.index(marker) : source.index(marker) + width]
    return "\n".join(line for line in block.splitlines() if not line.lstrip().startswith("#"))


def test_the_miner_prints_the_distinct_reasons_not_just_how_many() -> None:
    block = _code_after("if failed:")
    assert "reason" in block, "the failure summary no longer mentions reasons at all"
    assert 'row.get("error"' in block, (
        "the per-row `error` field is what carries the truth; a summary that does not read it is the "
        "2026-09-09 failure exactly"
    )
    assert "see the report" not in block, (
        "'see the report' is the phrase that hid a whole family for two rounds - the reasons are one "
        "dict away and belong on screen"
    )


def test_the_reasons_are_grouped_so_ninety_identical_ones_are_one_line() -> None:
    """Ungrouped, 90 copies of one sentence scroll the useful lines off the top - which hides it again."""
    block = _code_after("if failed:")
    assert "sorted(" in block and "-kv[1]" in block, "the reasons are not grouped and ordered by count"
