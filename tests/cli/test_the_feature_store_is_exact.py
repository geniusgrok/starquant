"""feature store（#9.6）读出来的必须就是现算的那一帧，连 block 结构与内存序都一样。

逐位用 `tests/alpha/test_causality.py` 的 `_bit_for_bit`：逐列 uint64 视图，不用 `assert_frame_equal` 的默认容差。
但对 feature store 来说逐位还不够：`starquant_cli/research_feature_store.py` 的 docstring 记着，值相同、只有内存
序不同的权重，会让 `ewma_portfolio_vol` 在真实面板的 50,225 根里有 6,467 根末位不同。所以这里再加一道
`identical`：block 数、每个 block 的 placement、C/F 序、逐字节都要相同。

真实数据用 `tests/fixtures/august_2026`（四个币的 1h 归档，只有 OHLCV）。线上配置那一条用合成面板，因为
registry 的 tsmom 要资金费、flow 要主动买入额，而 fixture 里两样都没有。
"""

from __future__ import annotations

import dataclasses
import json
import os
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
from click.testing import CliRunner

from starquant_alpha.model import AlphaModel
from starquant_alpha.panel import Panel
from starquant_alpha.portfolio import PortfolioParams
from starquant_alpha.registry import StrategyEntry
from starquant_alpha.signals import SIGNALS, get_signal
from starquant_alpha.signals.base import SignalSpec
from starquant_alpha.validation.pipeline import score_book
from starquant_cli import main, research_feature_store
from starquant_cli.research_book_eval import _book_guards, _exit_params
from starquant_cli.research_feature_store import (
    ENV,
    FeatureStore,
    StoredScoresModel,
    Uncacheable,
    code_digest,
    identical,
    store_from_env,
)
from starquant_cli.research_panel import _entry, _model
from starquant_live.composition import cost_model
from starquant_shared.config import load_yaml
from tests.alpha.test_causality import _bit_for_bit
from tests.cli.test_cli_offline import SYMBOLS, _store_from_fixtures

ROOT = Path(__file__).resolve().parents[2]
SHORT_TSMOM = {"horizons": [24, 72, 168], "vol_window": 100, "crowding_window": 0}
#: 两次「关」之间本来就会变的键。2026-09-25 实测只有生成时刻这一个；其余每个键都拿来比。
VOLATILE = {"generated_at"}


def _fixed_code() -> str:
    return "c" * 64


def _stored(model: AlphaModel, store: FeatureStore) -> StoredScoresModel:
    return StoredScoresModel(**{f.name: getattr(model, f.name) for f in dataclasses.fields(AlphaModel)}, store=store)


def _same_blocks(left: pd.DataFrame, right: pd.DataFrame) -> bool:
    """测试自己的尺子，不借被测模块的 `identical`：block 数、dtype、placement、C/F 标志、逐字节。"""
    ours, theirs = left._mgr.blocks, right._mgr.blocks
    if len(ours) != len(theirs):
        return False
    for a, b in zip(ours, theirs, strict=True):
        if a.dtype != b.dtype or not np.array_equal(a.mgr_locs.as_array, b.mgr_locs.as_array):
            return False
        flags = (a.values.flags.c_contiguous, a.values.flags.f_contiguous)
        if flags != (b.values.flags.c_contiguous, b.values.flags.f_contiguous):
            return False
        if a.values.tobytes(order="A") != b.values.tobytes(order="A"):
            return False
    return True


def _same_evaluation(left: tuple[Any, ...], right: tuple[Any, ...]) -> None:
    for a, b in zip(left[:2], right[:2], strict=True):
        _bit_for_bit(a, b)
    assert left[2].keys() == right[2].keys()
    for name in left[2]:
        _bit_for_bit(left[2][name], right[2][name])


@pytest.mark.parametrize(
    ("strategy", "params"),
    [("tsmom", SHORT_TSMOM), ("meanrev", {}), ("breakout", {}), ("residual", {}), ("chanlun", {})],
)
def test_a_hit_is_the_frame_the_signal_computed(
    august_panel: Panel, tmp_path: Path, strategy: str, params: dict[str, Any]
) -> None:
    """真实归档上五个 signal：一个 block 的、两个的、四个的。不命中返回的、命中读出的、直算的，三者相同。"""
    merged = {**SIGNALS[strategy].default_params, **params}
    model = AlphaModel(
        entries=(StrategyEntry(id=strategy, params=merged),),
        portfolio=PortfolioParams(no_trade_band=0.005),
        interval="1h",
        min_history_bars=48,
    )
    scored = august_panel.with_reference(model.eligible(august_panel))
    direct = get_signal(strategy).compute(scored, merged)
    store = FeatureStore(tmp_path, code=_fixed_code)
    miss = store.scores(strategy, merged, scored)
    hit = store.scores(strategy, merged, scored)
    assert (store.stats.misses, store.stats.writes, store.stats.hits, store.stats.unstorable) == (1, 1, 1, 0)
    _bit_for_bit(direct, miss)
    _bit_for_bit(direct, hit)
    assert identical(direct, hit) and _same_blocks(direct, hit), "逐位相同但 block 或内存序不同：下游的 BLAS 路径会变"
    # 整条 evaluate：关、开（冷）、开（热）三条路。
    cold = FeatureStore(tmp_path / "cold", code=_fixed_code)
    runs = [model.evaluate(august_panel), *(_stored(model, cold).evaluate(august_panel) for _ in range(2))]
    assert (cold.stats.misses, cold.stats.hits) == (1, 1)
    _same_evaluation(runs[0], runs[1])
    _same_evaluation(runs[0], runs[2])


def _full_panel() -> tuple[Panel, pd.DataFrame]:
    """六个币、1,600 根，字段齐全，带资金费。registry 的 tsmom 要 721 根预热，所以要这么长。"""
    index = pd.date_range("2024-01-01", periods=1_600, freq="h", tz="UTC")
    rng = np.random.default_rng(20260925)
    frames: dict[str, pd.DataFrame] = {}
    funding: dict[str, pd.Series] = {}
    settle = index[index.hour % 8 == 0] + pd.Timedelta(milliseconds=7)  # 币安的结算戳落在整点后几毫秒
    for n, symbol in enumerate(("AAAUSDT", "BBBUSDT", "CCCUSDT", "DDDUSDT", "EEEUSDT", "FFFUSDT")):
        drift = (n - 2.5) * 4e-4  # 有的涨有的跌，两种方向的信号都有机会出现
        close = 50.0 * np.exp(np.cumsum(rng.normal(drift, 0.012, len(index))))
        quote = rng.uniform(1e6, 5e6, len(index))
        frames[symbol] = pd.DataFrame(
            {
                "open": np.r_[close[0], close[:-1]],
                "high": close * 1.004,
                "low": close * 0.996,
                "close": close,
                "volume": quote / close,
                "quote_volume": quote,
                "trades": rng.integers(1_000, 5_000, len(index)).astype(float),
                "taker_buy_base": quote / close * rng.uniform(0.3, 0.7, len(index)),
                "taker_buy_quote": quote * rng.uniform(0.3, 0.7, len(index)),
            },
            index=index,
        )
        funding[symbol] = pd.Series(rng.normal(1e-4, 3e-4, len(settle)), index=settle)
    panel = Panel.from_frames(frames, interval="1h", funding=funding)
    membership = pd.DataFrame(True, index=panel.index, columns=panel.close.columns)
    membership.loc[membership.index[1_100:1_300], "CCCUSDT"] = False  # 离开 universe 一段，reference 就不是全真
    return panel, membership


def test_the_shipped_configuration_prices_the_same_book_with_the_store_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """registry 的 tsmom（带 crowding）、flow sleeve 与 carry，线上 profile 的组合、护栏与 exits，走研究侧的 `_model`。

    关、开（冷）、开（热）三条路的 evaluate 与 `score_book` 的净收益逐位相同。flow 在这块面板上是 6 个 block。
    """
    panel, membership = _full_panel()
    profile = load_yaml(str(ROOT / "config" / "live.demo.yaml"))
    cost = cost_model(load_yaml(str(ROOT / "config" / "costs.yaml")), use_funding=True)
    guards, exits = _book_guards(profile, True), _exit_params(profile, True, "1h")
    for strategy in ("tsmom", "flow", "carry"):
        entry = _entry(strategy, str(ROOT / "config" / "alpha_registry.yaml"), "")
        off = _model(entry, profile, "1h", None)
        monkeypatch.setenv(ENV, str(tmp_path))
        on = _model(entry, profile, "1h", None)
        monkeypatch.delenv(ENV)
        assert type(off) is AlphaModel and isinstance(on, StoredScoresModel)
        runs = [off.evaluate(panel, membership), on.evaluate(panel, membership), on.evaluate(panel, membership)]
        assert float(runs[0][0].abs().sum().sum()) > 0, f"{strategy} 在这块面板上没有仓位，测试就是空的"
        _same_evaluation(runs[0], runs[1])
        _same_evaluation(runs[0], runs[2])
        nets = [score_book(panel, run[0], cost, guards=guards, exits=exits)[0].portfolio_net for run in runs]
        _bit_for_bit(nets[0], nets[1])
        _bit_for_bit(nets[0], nets[2])
    assert on.store is not None and (on.store.stats.misses, on.store.stats.hits) == (3, 3)


def _momentum_on_the_panels_own_axes(panel: Panel, params: dict[str, Any]) -> pd.DataFrame:
    """把面板自己的索引与列对象原样交回去的 signal。命中时 store 交回的是另一个相等的对象。

    `copy=False` 让 pandas 直接拿行优先的数组当 block 的转置，于是 block 在自己的朝向上是 F 序；默认的
    `copy=True` 给的是 C 序。两种都要按原样重建。
    """
    move = np.log(panel.close / panel.close.shift(int(params["horizon"]))).to_numpy()
    values = np.ascontiguousarray(np.tanh(move / 0.05))
    return pd.DataFrame(values, index=panel.close.index, columns=panel.close.columns, copy=not params["f_block"])


@pytest.mark.parametrize("f_block", [False, True])
def test_a_signal_that_hands_back_the_panels_own_index_prices_the_same(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, f_block: bool
) -> None:
    """pandas 在一些地方按 `is` 走捷径。直算交回面板的索引对象，命中交回一个相等的新对象：下游照样逐位相同。"""
    params = {"horizon": 24, "f_block": f_block}
    spec = SignalSpec("mined_feature_store_axes", _momentum_on_the_panels_own_axes, params)
    monkeypatch.setitem(SIGNALS, spec.id, spec)
    panel, membership = _full_panel()
    profile = load_yaml(str(ROOT / "config" / "live.demo.yaml"))
    model = _model(StrategyEntry(id=spec.id, params=params), profile, "1h", None)
    direct = spec.compute(panel.with_reference(model.eligible(panel, membership)), params)
    assert direct.index is panel.close.index
    (block,) = research_feature_store._blocks(direct)
    assert (block.values.flags.f_contiguous, block.values.flags.c_contiguous) == (f_block, not f_block)
    store = FeatureStore(tmp_path, code=_fixed_code)
    runs = [model.evaluate(panel, membership), *(_stored(model, store).evaluate(panel, membership) for _ in range(2))]
    assert (store.stats.misses, store.stats.hits) == (1, 1)
    hit = store.read(store.key(spec.id, params, panel.with_reference(model.eligible(panel, membership))))
    assert hit is not None and identical(direct, hit) and _same_blocks(direct, hit), "读回的 block 与直算的不同"
    assert float(runs[0][0].abs().sum().sum()) > 0
    _same_evaluation(runs[0], runs[1])
    _same_evaluation(runs[0], runs[2])
    cost = cost_model(load_yaml(str(ROOT / "config" / "costs.yaml")), use_funding=True)
    exits = _exit_params(profile, True, "1h")
    nets = [score_book(panel, run[0], cost, exits=exits)[0].portfolio_net for run in runs]
    _bit_for_bit(nets[0], nets[1])
    _bit_for_bit(nets[0], nets[2])


def test_a_changed_code_digest_is_a_miss(august_panel: Panel, tmp_path: Path) -> None:
    """代码摘要一变，同一份数据、同一组参数也读不到旧条目。"""
    params = {**SIGNALS["tsmom"].default_params, **SHORT_TSMOM}
    FeatureStore(tmp_path, code=lambda: "a" * 64).scores("tsmom", params, august_panel)
    other = FeatureStore(tmp_path, code=lambda: "b" * 64)
    other.scores("tsmom", params, august_panel)
    assert (other.stats.hits, other.stats.misses) == (0, 1)
    again = FeatureStore(tmp_path, code=lambda: "a" * 64)
    again.scores("tsmom", params, august_panel)
    assert (again.stats.hits, again.stats.misses) == (1, 0)


def test_the_code_digest_reads_the_source_and_refuses_code_newer_than_the_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """改一个字节摘要就变；进程加载之后才被改过的源文件，让摘要拒绝出数（store 随之停用）。"""
    source = tmp_path / "starquant_alpha" / "m.py"
    source.parent.mkdir()
    source.write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr(research_feature_store, "_sources", lambda: (tmp_path, [source]))
    later = time.time_ns() + 60 * 10**9
    first = code_digest(later)
    source.write_text("x = 2\n", encoding="utf-8")  # 等长，只差一个字节
    assert code_digest(later) != first
    os.utime(source, ns=(later, later + 1))
    with pytest.raises(Uncacheable, match="changed after this process loaded its code"):
        code_digest(later)


def test_the_code_digest_covers_every_alpha_module_and_the_store_itself() -> None:
    root, files = research_feature_store._sources()
    names = {path.relative_to(root).as_posix() for path in files}
    alpha = {path.relative_to(root).as_posix() for path in (root / "starquant_alpha").rglob("*.py")}
    assert alpha and alpha <= names
    assert {
        "starquant_alpha/features.py",
        "starquant_alpha/signals/tsmom.py",
        "starquant_cli/research_feature_store.py",
    } <= names


def test_a_changed_input_is_a_miss(august_panel: Panel) -> None:
    """一个 ulp、零的符号位、reference 的一格、只改内存序、只改索引对象的共用关系：键都要变。"""
    store = FeatureStore(Path("never-written"), code=_fixed_code)
    params = {**SIGNALS["tsmom"].default_params, **SHORT_TSMOM}

    def key(panel: Panel) -> str:
        return store.key("tsmom", params, panel)

    base = august_panel.close.copy()
    baseline = key(dataclasses.replace(august_panel, close=base))
    assert key(dataclasses.replace(august_panel, close=base.copy())) == baseline, "同一份输入必须得到同一个键"
    nudged = base.copy()
    nudged.iloc[400, 1] = np.nextafter(nudged.iloc[400, 1], np.inf)
    assert key(dataclasses.replace(august_panel, close=nudged)) != baseline
    zero, negative = base.copy(), base.copy()
    zero.iloc[3, 0], negative.iloc[3, 0] = 0.0, -0.0
    assert key(dataclasses.replace(august_panel, close=zero)) != key(dataclasses.replace(august_panel, close=negative))
    reference = pd.DataFrame(True, index=august_panel.index, columns=august_panel.close.columns)
    trimmed = reference.copy()
    trimmed.iloc[500, 2] = False
    assert key(august_panel.with_reference(reference)) != key(august_panel.with_reference(trimmed))
    values = base.to_numpy()
    flipped = np.ascontiguousarray(values) if values.flags.f_contiguous else np.asfortranarray(values)
    relaid = pd.DataFrame(flipped, index=base.index, columns=base.columns, copy=False)
    assert research_feature_store._blocks(relaid)[0].values.flags.f_contiguous != (
        research_feature_store._blocks(base)[0].values.flags.f_contiguous
    )
    _bit_for_bit(base, relaid)  # 数值逐位相同……
    assert key(dataclasses.replace(august_panel, close=relaid)) != baseline  # ……布局不同，键就不同
    shared = dataclasses.replace(august_panel, open=august_panel.open.set_axis(august_panel.close.index, axis=0))
    separate = dataclasses.replace(
        august_panel, open=august_panel.open.set_axis(august_panel.close.index.copy(), axis=0)
    )
    assert key(shared) != key(separate)
    assert store.key("tsmom", {**params, "return_scale": 0.2000000000000001}, august_panel) != key(august_panel)


def test_what_cannot_be_keyed_exactly_is_computed_every_time(august_panel: Panel, tmp_path: Path) -> None:
    """numpy 标量参数没有精确的 JSON 形式：不猜，照算，不写盘。"""
    params = {**SIGNALS["tsmom"].default_params, **SHORT_TSMOM, "vol_window": np.int64(100)}
    store = FeatureStore(tmp_path, code=_fixed_code)
    out = store.scores("tsmom", params, august_panel)
    assert (store.stats.uncacheable, store.stats.writes) == (1, 0)
    assert not any(tmp_path.iterdir())
    _bit_for_bit(out, get_signal("tsmom").compute(august_panel, params))


def test_an_output_that_would_not_read_back_identical_is_never_stored(
    august_panel: Panel, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """行索引不是时间的帧，存储格式表达不了：照样返回现算的那一帧，只是不落盘。"""
    spec = SignalSpec("mined_feature_store_probe", lambda panel, params: panel.close.reset_index(drop=True), {})
    monkeypatch.setitem(SIGNALS, spec.id, spec)
    store = FeatureStore(tmp_path, code=_fixed_code)
    out = store.scores(spec.id, {}, august_panel)
    assert (store.stats.unstorable, store.stats.writes) == (1, 0)
    assert not list(tmp_path.glob("*"))
    _bit_for_bit(out, august_panel.close.reset_index(drop=True))


def test_a_validate_report_reads_the_same_with_the_store_off_cold_and_warm(
    tmp_path: Path, august_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """真跑一条研究命令：fixture 数据上的 `research validate`，关、关、开冷、开热四次，每次一本空 ledger。

    两次「关」之间本来就不同的键不比（`VOLATILE` 写明是哪几个）；其余每个键，开冷与开热都要与「关」逐字相同。
    比的是 JSON 文本，所以 NaN 也按字面比。
    """
    root = tmp_path / "data"
    _store_from_fixtures(august_dir, root)
    args = [
        *("research", "validate", "--strategy", "tsmom", "--root", str(root), "--symbols", ",".join(SYMBOLS)),
        *("--no-funding", "--params", '{"horizons": [5, 20, 50], "crowding_window": 0}'),
        *("--grid", '{"vol_window": [100, 200]}', "--folds", "3", "--min-train", "300", "--purge", "5"),
        *("--cpcv-groups", "4", "--min-history", "0"),
    ]
    payloads: list[dict[str, Any]] = []
    for n, where in enumerate((None, None, "store", "store")):
        monkeypatch.setenv("STARQUANT_TRIALS_LEDGER", str(tmp_path / f"ledger-{n}.jsonl"))
        if where is None:
            monkeypatch.delenv(ENV, raising=False)
        else:
            monkeypatch.setenv(ENV, str(tmp_path / where))
        out = tmp_path / f"reports-{n}"
        result = CliRunner().invoke(main, [*args, "--out", str(out)])
        assert result.exit_code == 0, result.output
        payloads.append(json.loads(next(out.glob("tsmom-validation-*.json")).read_text(encoding="utf-8")))
    volatile = {key for key in payloads[0] if payloads[0][key] != payloads[1].get(key)}
    assert volatile <= VOLATILE, f"两次「关」之间出现了新的不稳定键：{volatile - VOLATILE}"

    def stable(payload: dict[str, Any]) -> str:
        return json.dumps({k: v for k, v in payload.items() if k not in VOLATILE}, sort_keys=True)

    assert stable(payloads[2]) == stable(payloads[0])
    assert stable(payloads[3]) == stable(payloads[0])
    store = store_from_env()
    assert store is not None and store.stats.hits >= 2 and store.stats.writes >= 2
