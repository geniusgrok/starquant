"""研究命令的网格：默认网格、枚举成格子、以及按预登记规则选中的那一格。

`DEFAULT_GRIDS` 是名额脚枪的所在——不显式传 `--grid` 时 `validate` 就按它计费（tsmom 16 格）。
把它和枚举/选格放在一起，是为了让「这次要花多少笔」只有一个地方能回答。
"""

from __future__ import annotations

import itertools
import json
from collections.abc import Mapping
from typing import Any

import click

# The panel layer now lives in `starquant_cli/research_panel.py` (M6 step 1) and is re-exported here.
# Twenty-nine scripts under `scratchpad/` - the reproductions behind D-035's ladder bootstrap, P26,
# P29, P32, D-039's band sweep and the exit reachability tables - import `_load`, `_membership` and
# `_resolve_symbols` from THIS module, and a dozen tests import the others.  Moving the definitions
# without keeping the addresses would have made a move-only commit break the evidence base, so the
# addresses stay until the sink step gives those names a home outside `starquant_cli` entirely.

DEFAULT_GRIDS: dict[str, dict[str, list[Any]]] = {
    "tsmom": {
        "horizons": [[5, 20, 50], [24, 72, 168], [168, 336, 720], [336, 720, 1440]],
        "entry_threshold": [0.20, 0.30],
        "return_scale": [0.20, 0.30],
        "vol_window": [400],
    },
    # Prior-driven small grids: every extra trial costs DSR power; do not widen these to "find" a pass.
    "xsmom": {"skip_bars": [24, 48], "z_scale": [1.0, 1.5], "entry_threshold": [0.20, 0.30]},
    "carry": {"window_bars": [72, 168], "entry_threshold": [0.20, 0.30]},
    "meanrev": {"window": [24, 48, 96], "z_entry": [1.5, 2.0, 2.5], "trend_gate_z": [1.5, 2.0, 3.0]},
    "breakout": {"window": [24, 48, 96], "distance_scale": [1.0, 2.0, 3.0]},
    "flow": {"window": [24, 72, 168, 336], "scale": [0.03, 0.05, 0.10], "entry_threshold": [0.20, 0.30]},
    "residual": {"horizons": [[24, 72, 168], [168, 336, 720]], "scale": [0.05, 0.10], "beta_window": [336, 720]},
}
# D-017 pre-registered overlay grids: evaluated once on the registry ensemble, never widened after seeing results.
DEFAULT_EXIT_GRID: dict[str, list[Any]] = {
    "stop_loss": [0.0, 2.5, 4.0],
    "trailing_stop": [0.0, 4.0],
    "take_profit": [0.0, 6.0],
}
DEFAULT_THROTTLE_GRID: dict[str, list[Any]] = {"start": [0.05], "stop": [0.20], "floor": [0.25]}


def _grid(strategy: str, grid_json: str, base: dict[str, Any]) -> list[dict[str, Any]]:
    grid = json.loads(grid_json) if grid_json else DEFAULT_GRIDS.get(strategy, {})
    if not grid:
        return [dict(base)]
    keys = sorted(grid)
    combos: list[dict[str, Any]] = []
    for values in itertools.product(*(grid[key] for key in keys)):
        combos.append({**base, **dict(zip(keys, values, strict=True))})
    return combos


def _selected_key(select_json: str, params_by_key: Mapping[str, Mapping[str, Any]], prereg: str) -> str | None:
    """The one grid cell a pre-registered rule named, or ``None`` when the run names none.

    Round 7's副产品 1, made addressable.  `best_params` is the full-sample argmax and is what the
    registry's startup gate compares against, so a candidate chosen by a rule that is not "highest
    full-sample Sharpe" - H-001's was "OOS >= baseline - 0.05 AND drawdown improves AND turnover
    falls" - could not be reported by the run that evaluated it.  The workaround was a second,
    single-configuration report.

    `--prereg` is required rather than encouraged, and that is the whole safeguard: naming a cell
    after seeing the grid is the selection D-028 exists to deflate, while naming one from a commit
    that predates the run is the pre-registration DL-K3 asks for - and `_preregistration` records the
    commit's own timestamp, so the ordering stays checkable from the artefact afterwards.

    Exactly one match, never the first of several: a selector that silently picked one of two cells
    would be choosing, which is the thing being pre-registered away.
    """
    if not select_json:
        return None
    if not prereg.strip():
        raise click.ClickException(
            "--select names the cell a pre-registered rule chose, so it needs --prereg <commit> to say "
            "WHICH rule and when it was written.  Without that it is just a different way of picking a "
            "winner after seeing the grid, which is the selection D-028 deflates."
        )
    wanted = json.loads(select_json)
    matches = [key for key, combo in params_by_key.items() if all(combo.get(k) == v for k, v in wanted.items())]
    if len(matches) != 1:
        raise click.ClickException(
            f"--select {select_json} matches {len(matches)} of this run's {len(params_by_key)} cells; it "
            "has to match exactly one, because picking one of several here would be the choice the "
            "pre-registration is supposed to have already made."
        )
    return matches[0]


def _grid_of(grid: Mapping[str, list[Any]]) -> list[dict[str, Any]]:
    keys = sorted(grid)
    return [dict(zip(keys, values, strict=True)) for values in itertools.product(*(grid[key] for key in keys))]
