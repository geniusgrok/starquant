"""九个研究子命令共用的 click 选项。

放在这里而不是各自重复：一个选项的默认值改了，九条命令要一起改，否则两份报告会在
没人注意的地方量不同的东西。
"""

from __future__ import annotations

from typing import Any

import click

# The panel layer now lives in `starquant_cli/research_panel.py` (M6 step 1) and is re-exported here.
# Twenty-nine scripts under `scratchpad/` - the reproductions behind D-035's ladder bootstrap, P26,
# P29, P32, D-039's band sweep and the exit reachability tables - import `_load`, `_membership` and
# `_resolve_symbols` from THIS module, and a dozen tests import the others.  Moving the definitions
# without keeping the addresses would have made a move-only commit break the evidence base, so the
# addresses stay until the sink step gives those names a home outside `starquant_cli` entirely.

UNIVERSE_MODES = ("static", "pit")


def _common_options(function: Any) -> Any:
    for option in reversed(
        [
            click.option("--strategy", required=True, help="signal id (see `starquant research list`)"),
            click.option("--params", default="", help="JSON overriding the registry/default params"),
            # The search space a `mined_<hash>` id was drawn from.  Every grid is a bar COUNT, so an
            # id mined at another interval does not enumerate under the defaults and `_resolve_mined`
            # reports it gone - correct by its own contract, useless to an operator holding the
            # shortlist that just produced it.  Shared rather than per-command, because a mined id is
            # addressable wherever a hand-written one is; that is what `_entry` is for.
            click.option(
                "--grids", default="", help="JSON of enumerate_candidates grids, e.g. '{\"horizons\": [1, 3, 7]}'"
            ),
            click.option("--root", default=".starquant/data", show_default=True),
            click.option("--symbols", default="", help="comma-separated; default = selected universe or all stored"),
            click.option("--interval", default="1h", show_default=True),
            click.option("--from", "start", default=None, help="YYYY-MM-DD inclusive"),
            click.option("--to", "end", default=None, help="YYYY-MM-DD exclusive"),
            click.option("--profile", default="config/live.demo.yaml", show_default=True),
            click.option("--registry", "registry_path", default="config/alpha_registry.yaml", show_default=True),
            click.option("--costs", "costs_path", default="config/costs.yaml", show_default=True),
            click.option(
                "--execution", type=click.Choice(["open_to_close", "close_to_close"]), default="open_to_close"
            ),
            click.option("--funding/--no-funding", default=True, show_default=True),
            click.option("--out", default="reports/research", show_default=True),
            click.option(
                "--min-history",
                default=None,
                type=int,
                help="bars a symbol must have before it is tradable (default: profile portfolio.min_history_bars)",
            ),
            click.option(
                "--universe",
                "universe_mode",
                type=click.Choice(list(UNIVERSE_MODES)),
                default="static",
                show_default=True,
                help="static = universe.json/all stored; pit = point-in-time membership from `starquant data pool history`",
            ),
            click.option(
                "--min-tenure",
                default=0,
                show_default=True,
                help="pit only: refreshes of prior membership a symbol needs before it is tradable (established names)",
            ),
        ]
    ):
        function = option(function)
    return function


# CPCV's embargo is not walk-forward's purge read backwards; `cpcv_splits`' docstring has the argument
# and `docs/analysis/2026-09-13-full-repo-review.md` has the finding.  The knob is split out here so the
# boundary CAN be closed; the default stays `--purge` so that this commit changes no published number.
_embargo_option = click.option(
    "--embargo",
    default=None,
    type=int,
    help=(
        "bars blocked AFTER each CPCV test block (default: --purge, i.e. today's behaviour).  "
        "Closing the boundary wants the model's feature lookback, not a label horizon - warmup_bars "
        "is 1,442 under the shipped registry - and that is a pre-registered re-run, not a flag flip."
    ),
)
