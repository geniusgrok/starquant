"""Which look-aheads under the default tolerance the signal-layer causality tests catch, before and after `_bit_for_bit`.

Until 2026-09-23 three shuffled-future tests compared with `assert_frame_equal`'s default, rtol 1e-5 /
atol 1e-8: `test_signals_are_causal_and_bounded` (all 11 cases), `test_tsmom_is_causal` and
`test_garch_is_causal_under_a_shuffled_future`.  This plants one leak per case - 1e-9 of the next bar's
return, added to the output - runs the test once with the old comparison and once with `_bit_for_bit`,
and prints which went red.  The leak reaches one compared bar, the last before the cutoff, and moves it by
4e-11 to 8e-10 (the last column): far inside the default atol and far outside one ulp.  `_bit_for_bit`'s
docstring in `tests/alpha/test_causality.py` quotes the result.

No source file is edited.  Each leak wraps the function the test calls, in this process, so there is no
copy of the tree and no bytecode cache to go stale.  The control wraps nothing: if it goes red, the
harness is broken, not the code.

    .venv/bin/python scratchpad/causal_tests_bit_for_bit_planted_leaks.py
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import tests.alpha.test_causality as causality  # noqa: E402
import tests.alpha.test_construction_options_are_off_by_default as options  # noqa: E402
import tests.alpha.test_signal_suite as suite  # noqa: E402
from starquant_alpha.signals import SIGNALS  # noqa: E402
from tests.conftest import FIXTURES, load_august_panel  # noqa: E402

LEAK = 1e-9


def _next_return(close: pd.DataFrame) -> pd.DataFrame:
    return close.pct_change().shift(-1)


def _run(test: Callable[[], None], module: Any, comparison: Callable[..., None]) -> str:
    kept = module._bit_for_bit
    module._bit_for_bit = comparison
    try:
        test()
        return "pass"
    except AssertionError:
        return "RED"
    finally:
        module._bit_for_bit = kept


#: The largest difference the old comparison was handed, per case: what "inside the tolerance" meant here.
LET_THROUGH: list[float] = []


def _default(before: pd.DataFrame, after: pd.DataFrame) -> None:
    LET_THROUGH.append(float((after - before).abs().max().max()))
    pd.testing.assert_frame_equal(before, after)


def _both(test: Callable[[], None], module: Any) -> tuple[str, str]:
    return _run(test, module, _default), _run(test, module, causality._bit_for_bit)


def main() -> None:
    rows: list[tuple[str, str, str, float]] = []

    for signal_id, overrides, label in suite.CASES:
        spec = SIGNALS[signal_id]

        def test() -> None:
            suite.test_signals_are_causal_and_bounded(signal_id, overrides, label)  # noqa: B023

        control = _both(test, suite)
        original = spec.compute

        def leaky(panel: Any, params: Any, compute: Callable[..., pd.DataFrame] = original) -> pd.DataFrame:
            return (compute(panel, params) + LEAK * _next_return(panel.close)).clip(-1.0, 1.0)

        SIGNALS[signal_id] = replace(spec, compute=leaky)
        try:
            LET_THROUGH.clear()
            planted = _both(test, suite)
        finally:
            SIGNALS[signal_id] = spec
        rows.append((f"signal suite {signal_id}-{label}", f"control {control}", f"planted {planted}", LET_THROUGH[0]))

    panel = load_august_panel(FIXTURES / "august_2026")
    real_tsmom = causality.tsmom_scores
    control = _both(lambda: causality.test_tsmom_is_causal(panel), causality)
    causality.tsmom_scores = lambda close, params=None: real_tsmom(close, params) + LEAK * _next_return(close)
    try:
        LET_THROUGH.clear()
        planted = _both(lambda: causality.test_tsmom_is_causal(panel), causality)
    finally:
        causality.tsmom_scores = real_tsmom
    rows.append(("test_tsmom_is_causal", f"control {control}", f"planted {planted}", LET_THROUGH[0]))

    real_garch = options.garch_forecast_vol
    control = _both(options.test_garch_is_causal_under_a_shuffled_future, options)
    options.garch_forecast_vol = lambda close, **kwargs: real_garch(close, **kwargs) + LEAK * _next_return(close)
    try:
        LET_THROUGH.clear()
        planted = _both(options.test_garch_is_causal_under_a_shuffled_future, options)
    finally:
        options.garch_forecast_vol = real_garch
    rows.append(
        ("test_garch_is_causal_under_a_shuffled_future", f"control {control}", f"planted {planted}", LET_THROUGH[0])
    )

    print("(old default comparison, _bit_for_bit); the largest move the old comparison let through")
    for name, control_cell, planted_cell, let_through in rows:
        print(f"{name:<48} {control_cell:<26} {planted_cell:<26} {let_through:.2e}")


if __name__ == "__main__":
    main()
