"""``starquant research ...``：九个子命令的注册处，以及它们的名字对外的那个地址。

拆成九个模块之后这里只剩两件事，两件都不能省：

**一、导入即注册。** 九个命令靠 `@research.command(...)` 在**导入时**挂到 click group 上，而
`starquant_cli/__init__.py` 导入的是本模块。所以本模块必须导入那九个模块，否则 `starquant research --help`
会少命令——这条由 `tests/cli/test_each_research_command_has_its_own_module.py` 守着。

**二、地址不变。** `scratchpad/` 下 29 个复现脚本与二十余处测试写的是
`from starquant_cli.research_cmd import _load, _membership, _resolve_symbols, ...`。D-035 的档位自助、
P26、P29、P32、D-039 的带宽扫描、退出可达性表——这个仓库的证据基础就架在这些地址上。搬家不能让
它们断，所以下面把每个名字按原地址再导出，并由测试断言新旧地址指向**同一个对象**。

不能建 `starquant_cli/research/` 包：`research` 已经是 `starquant_cli/__init__.py` 里的 click group，
建包会遮住它。所以这些是平级模块。
"""

from __future__ import annotations

# 这三个不是本模块自己的东西，是它此前顺带提供的地址，而确实有人在用：
# `scratchpad/u3_attrib.py` 取 `cost_model` / `portfolio_params`，
# `tests/cli/test_research_mine_asks_r1_before_it_spends.py` 取 click group `research`。
# 搬家不改别人的 import 行，所以它们照旧从这里能取到。
from starquant_cli import research  # noqa: F401  (re-exported at its historical address; see the module docstring)
from starquant_cli.research_backtest_cmd import (
    research_backtest,
)
from starquant_cli.research_book_cmd import (
    research_book,
)
from starquant_cli.research_book_eval import (  # noqa: F401  (re-exported at its historical address; see the module docstring)
    BOOK_RULE,
    _book_guards,
    _book_limits,
    _combine_books,
    _embargo_bars,
    _evaluate_book,
    _exit_params,
    _fold_metrics,
    _netting,
    _overlaid,
    _overlay_metrics,
    _running_book_nets,
    _standalone_block,
    _stressed_oos_gate,
)
from starquant_cli.research_correlate_cmd import (
    research_correlate,
)
from starquant_cli.research_decompose_cmd import (
    research_decompose,
)
from starquant_cli.research_diagnose_cmd import (
    research_diagnose,
)
from starquant_cli.research_forward_cmd import (  # noqa: F401  (re-exported at its historical address; see the module docstring)
    forward_add,
    forward_retire,
    forward_status,
    research_forward,
)
from starquant_cli.research_grids import (  # noqa: F401  (re-exported at its historical address; see the module docstring)
    DEFAULT_EXIT_GRID,
    DEFAULT_GRIDS,
    DEFAULT_THROTTLE_GRID,
    _grid,
    _grid_of,
    _selected_key,
)
from starquant_cli.research_ledger_io import (  # noqa: F401  (re-exported at its historical address; see the module docstring)
    _charge_signal_search,
    _construction_digest,
    _incumbent_grid,
    _overlay_digest,
    _preregistration,
    _prior_search,
    _record_trial,
    _record_trials,
    _refuse_an_undeclared_charge,
    _reproduction_of,
    _search_space_version,
    _short_digest,
    _symbol_set_hash,
    _trial_signature,
)
from starquant_cli.research_list_cmd import (
    research_list,
)
from starquant_cli.research_mine_cmd import (
    research_mine,
)
from starquant_cli.research_options import (  # noqa: F401  (re-exported at its historical address; see the module docstring)
    UNIVERSE_MODES,
    _common_options,
    _embargo_option,
)
from starquant_cli.research_overlay_cmd import (
    research_overlay,
)
from starquant_cli.research_panel import (  # noqa: F401  (re-exported at its historical address; see the module docstring)
    _entry,
    _funding_consumers,
    _funding_facts,
    _load,
    _membership,
    _membership_table,
    _model,
    _require_funding,
    _resolve_mined,
    _resolve_symbols,
    _wants_metrics,
    _wants_spot,
)
from starquant_cli.research_power_cmd import (
    research_power,
)
from starquant_cli.research_report import (  # noqa: F401  (re-exported at its historical address; see the module docstring)
    _MARGIN_BUFFER_NOTE,
    COST_SHARE_LIMIT,
    _caliber_note,
    _cost_flag,
    _durable,
    _echo_summary,
    _embargo_note,
    _fmt,
    _fmt_pct,
    _full_sample_tail_note,
    _grid_table,
    _pbo_note,
    _stamp,
    _write,
)
from starquant_cli.research_validate_cmd import (
    research_validate,
)
from starquant_live.composition import (  # noqa: F401  (re-exported at its historical address; see the module docstring)
    cost_model,
    portfolio_params,
)

__all__ = [
    "research_backtest",
    "research_book",
    "research_correlate",
    "research_decompose",
    "research_diagnose",
    "research_forward",
    "research_list",
    "research_mine",
    "research_overlay",
    "research_power",
    "research_validate",
]
