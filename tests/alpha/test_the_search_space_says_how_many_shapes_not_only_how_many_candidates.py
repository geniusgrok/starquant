"""676 candidates are 61 shapes, and nothing could say the latter.

The same failure `distinct_hypotheses` closes one floor down, asked of the search space instead of the
ledger: every count beside it counts candidates, so no artefact could say how much of a 676-wide space
is one mechanism written with different constants.

What this is NOT is the thing operator ruling 2026-09-14 (Q4) refused.  That ruling turns on a ranked
shortlist - "free to look" is a multiple-testing hole with a flag on it, "free to count" is not.  A
shape histogram names no candidate, carries no Sharpe and ranks nothing, which is the side of that
line `effective_trials` already sits on.

Every expression below is taken from the enumerator by its own text rather than rebuilt here: a
fixture assembled by hand tests the constructor this file guessed at, not the space that ships.
"""

from __future__ import annotations

import re

from starquant_alpha.mining.expr import Expr
from starquant_alpha.mining.search import enumerate_candidates, structural_families, structural_key

#: The space is deterministic and data-free, so one enumeration serves every test in this file.
SPACE = {str(candidate.expr): candidate.expr for candidate in enumerate_candidates().candidates}


def _shape_of(text: str) -> str:
    expression: Expr = SPACE[text]  # KeyError here means the space moved, which is the news
    return structural_key(expression)


def test_the_real_search_space_folds_to_far_fewer_shapes() -> None:
    families = structural_families(list(enumerate_candidates().candidates))

    assert len(SPACE) == 676, "the space moved; re-measure the shapes in the same commit"
    assert len(families) == 61, "2026-09-20 measured 61 shapes over 676 candidates"
    assert sum(families.values()) == 676, "every candidate belongs to exactly one shape"


def test_only_the_magnitudes_fold() -> None:
    """Two windows of one mechanism are one shape.  This is the whole point of the key."""
    assert _shape_of("squash(rangepos(24), 0.5)") == _shape_of("squash(rangepos(168), 1)")


def test_direction_survives_the_fold() -> None:
    """A claim and its negation are two mechanisms, and the shape separates them without help.

    `(-1 * X)` carries a `mul` node that `X` does not, so the key drops the minus with every other
    number and the two still fall apart.  Measured 2026-09-20 with a System One model over the real
    expressions: a reversed pair scored 1.75/2 toward "different hypothesis" once the levels said a
    reversed sign belongs there.
    """
    assert _shape_of("cs_rank(lsr(72))") != _shape_of("cs_rank((-1 * lsr(72)))")


def test_no_two_candidates_differ_only_in_a_sign() -> None:
    """The premise that lets `structural_key` drop the minus along with the magnitudes.

    It holds by measurement, not by construction: today no two candidates are the same text apart from
    one constant's sign, so folding `-2` and `2` together cannot merge two mechanisms.  If this goes
    red the premise has expired - the space grew a pair like `2 * X` against `-2 * X` - and the key has
    to keep the sign before the histogram means anything again.
    """
    unsigned: dict[str, list[str]] = {}
    for text in SPACE:
        unsigned.setdefault(re.sub(r"-(\d)", r"\1", text), []).append(text)

    collisions = {key: texts for key, texts in unsigned.items() if len(texts) > 1}

    assert not collisions, f"these differ only in a sign, so the key must stop dropping it: {collisions}"


def test_skew_and_kurt_are_not_one_shape() -> None:
    """Why the key is built on `describe()` and not on `signature()`.

    `signature` files `moment`'s `order` beside its `window`, so a magnitude-dropping fold over it
    collapses the third moment into the fourth.  Measured first, then the layer was chosen.
    """
    assert _shape_of("squash(skew(ret(1), 336), 0.5)") != _shape_of("squash(kurt(ret(1), 168), 2)")


def test_an_empty_space_has_no_shapes() -> None:
    assert structural_families([]) == {}


def test_a_commutative_product_is_one_shape_in_either_order() -> None:
    """The defect the first version of this key had, and the reason it reads the tree.

    `canonical()` sorts a `mul`'s operands, but it sorts on the constants, so once the constants are
    gone the order is arbitrary and the same mechanism appears twice.  Measured 2026-09-20: a regex
    over the `describe()` text counted 85 shapes where the tree counts 61, and all 24 of the
    difference were one product written both ways.
    """
    assert _shape_of("squash(((funding(72) / vol(48)) * (ret(72) / vol(48))), 1)") == _shape_of(
        "squash(((ret(168) / vol(48)) * (funding(24) / vol(48))), 1)"
    )


def test_a_shape_keeps_no_magnitude_that_could_name_a_candidate() -> None:
    """Q4's line, asserted rather than described: a shape that kept its windows is a candidate.

    Stated over the magnitude fields by name rather than over digits, because `moment.order` survives
    on purpose - 3 and 4 are skewness and kurtosis, not two window lengths.
    """
    shapes = "".join(structural_families(list(enumerate_candidates().candidates)))

    for field in ("days", "horizon", "scale", "weight", "window"):
        assert not re.search(rf'"{field}":(?!"N")', shapes), f"{field} kept a magnitude"
