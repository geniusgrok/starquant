"""The pre-registration template's numbered items are load-bearing, so deleting one must fail.

Each item in `docs/PREREGISTRATION.md` was added because something went wrong without it, and each
one costs the person writing a pre-registration something to fill in.  That is exactly the shape of
a rule that gets quietly dropped: the next author is in a hurry, the item is prose in a Markdown
file, and nothing notices.  Item 5 (the power reading, added 2026-09-18 by Q-SY1) had no guard at
all until this file existed.

**What this guards and what it does not.**  It guards the template against deletion.  It does NOT
make anyone fill the items in - a pre-registration that skips item 8 still runs, because nothing
reads the template at validate time.  The honest description is "a convention with a tripwire", and
saying so here matters: the analysis that added item 8 was itself criticised (K-LD10) for calling a
read location a prevention.  Turning this into a real mechanism means `research validate` refusing
to run without the line, the way it already refuses without `--grid`/`--charge` (PR #40).  That is a
CLI change against a package with no source-budget headroom, and it is deliberately not done here.

The count is asserted separately from the titles so that ADDING an item fails too: a tenth item is
fine, but the heading that announces "必写的九项" has to move with it, or the document starts lying
about itself.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

TEMPLATE = Path(__file__).resolve().parents[2] / "docs" / "PREREGISTRATION.md"

# Substrings, not full headings: each item's title carries a dated provenance note that is expected
# to grow ("← 2026-09-18 新增（M-SY01, Q-SY1 ...）"), and pinning the whole line would turn every
# annotation into a failure.  What must not change is which questions the template asks.
REQUIRED_ITEMS: tuple[tuple[int, str], ...] = (
    (1, "假设"),
    (2, "「新信息」还是「新网格」"),
    (3, "协议"),
    (4, "计费与桶"),
    (5, "功效读数"),
    (6, "判定规则"),
    (7, "预期"),
    (8, "本次服务四个目标里的哪一个"),
    (9, "实盘失效方式"),
)

# The four objectives the operator selected on 2026-09-18.  Item 8 is only meaningful if the
# template still says what the labels mean.
REQUIRED_OBJECTIVES = ("G-A", "G-B", "G-C", "G-D")

COUNT_IN_WORDS = {7: "七", 8: "八", 9: "九", 10: "十"}


@pytest.fixture(scope="module")
def template() -> str:
    if not TEMPLATE.exists():  # pragma: no cover - the file is tracked
        pytest.skip(f"{TEMPLATE} is not in this checkout")
    return TEMPLATE.read_text(encoding="utf-8")


def test_every_numbered_item_is_still_in_the_template(template: str) -> None:
    missing = [
        f"{number}. {title}"
        for number, title in REQUIRED_ITEMS
        if not re.search(rf"^### {number}\. .*{re.escape(title)}", template, re.MULTILINE)
    ]
    assert not missing, (
        f"the pre-registration template lost {missing}. Each item was added because something went "
        "wrong without it; removing one is a governance change, not an edit."
    )


def test_the_template_says_how_many_items_it_has_and_is_right(template: str) -> None:
    """A heading that says 「必写的九项」 over eight items is worse than no heading."""
    headings = re.findall(r"^### (\d+)\. ", template, re.MULTILINE)
    actual = len({int(n) for n in headings})
    expected_word = COUNT_IN_WORDS.get(actual)
    assert expected_word is not None, f"{actual} items: add it to COUNT_IN_WORDS"
    assert f"必写的{expected_word}项" in template, (
        f"the template has {actual} numbered items but does not announce 必写的{expected_word}项. "
        "Adding an item means moving that heading too."
    )


def test_item_eight_still_defines_the_four_objectives(template: str) -> None:
    """The labels are only useful while the template says what they mean."""
    item_eight = template.split("### 8. ", 1)
    assert len(item_eight) == 2, "item 8 is gone; see the previous test"
    body = item_eight[1].split("\n## ", 1)[0].split("\n### ", 1)[0]  # item 8 ends where item 9 begins
    missing = [objective for objective in REQUIRED_OBJECTIVES if objective not in body]
    assert not missing, f"item 8 no longer defines {missing}; a label with no definition is not a label"


def test_item_five_still_carries_the_command_that_produces_the_power_reading(template: str) -> None:
    """Item 5's whole point is that the number is computed, not recalled (the four-times-asked question)."""
    assert "research power" in template, (
        "item 5 lost the command. A power reading nobody can reproduce is the word this item replaced."
    )
