"""feature store（#9.6）的每一种失败都落在「重算」一侧，而且碰不到实盘。

坏条目当未命中并被重写；同一个键的并发写者各自发布一个完整文件；容量到顶按最近最少使用淘汰，只删自己写的
名字；进程加载之后源码被改，store 就整个停用、照常现算；实盘建模的入口在环境变量打开时仍然是原来的
`AlphaModel`，其它包的源码里也不出现 store 的任何名字。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from starquant_alpha.model import AlphaModel
from starquant_alpha.panel import Panel
from starquant_alpha.registry import StrategyEntry
from starquant_alpha.signals import SIGNALS, get_signal
from starquant_cli import research_feature_store
from starquant_cli.research_feature_store import (
    ENV,
    FeatureStore,
    Uncacheable,
    feature_scores,
    identical,
    store_from_env,
    with_feature_store,
)
from starquant_cli.research_panel import _model
from starquant_live.config import build_model_from_profile
from starquant_shared.config import load_yaml
from tests.alpha.test_causality import _bit_for_bit
from tests.conftest import AUGUST_SYMBOLS, FIXTURES, load_august_panel

ROOT = Path(__file__).resolve().parents[2]
# JSON 原生类型：子进程收到的是 `json.loads` 之后的参数，而 `_canonical` 故意区分 tuple 与 list。
PARAMS = json.loads(json.dumps({**SIGNALS["tsmom"].default_params, "horizons": [24, 72, 168], "vol_window": 100}))


def _fixed_code() -> str:
    return "c" * 64


def test_a_corrupt_entry_is_a_miss_and_is_rewritten(august_panel: Panel, tmp_path: Path) -> None:
    direct = get_signal("tsmom").compute(august_panel, PARAMS)
    store = FeatureStore(tmp_path, code=_fixed_code)
    store.scores("tsmom", PARAMS, august_panel)
    other = {**PARAMS, "return_scale": 0.3}
    store.scores("tsmom", other, august_panel)
    path = store.path(store.key("tsmom", PARAMS, august_panel))
    good = path.read_bytes()
    damages = {
        "一个 payload 字节": good[:-100] + bytes([good[-100] ^ 0x01]) + good[-99:],
        "截断": good[: len(good) // 2],
        "magic": b"XXXXXXXX" + good[8:],
        "header 长度": good[:8] + (10**12).to_bytes(8, "little") + good[16:],
        "另一个键的完整条目": store.path(store.key("tsmom", other, august_panel)).read_bytes(),
        "空文件": b"",
    }
    for label, blob in damages.items():
        path.write_bytes(blob)
        fresh = FeatureStore(tmp_path, code=_fixed_code)
        _bit_for_bit(direct, fresh.scores("tsmom", PARAMS, august_panel))
        assert (fresh.stats.corrupt, fresh.stats.hits, fresh.stats.misses, fresh.stats.writes) == (1, 0, 1, 1), label
        again = FeatureStore(tmp_path, code=_fixed_code)
        _bit_for_bit(direct, again.scores("tsmom", PARAMS, august_panel))
        assert (again.stats.hits, again.stats.corrupt) == (1, 0), f"{label}：坏条目没有被重写"


def test_concurrent_threads_writing_one_key_leave_one_whole_entry(august_panel: Panel, tmp_path: Path) -> None:
    """八个写者、一个读者同时开始。读者只能读到「没有」或完整的那一帧，最后只剩一个文件、没有临时文件。"""
    store = FeatureStore(tmp_path, code=_fixed_code)
    key = store.key("tsmom", PARAMS, august_panel)
    frame = get_signal("tsmom").compute(august_panel, PARAMS)
    start = threading.Barrier(9)
    reads: list[object] = []
    errors: list[BaseException] = []
    readers: list[FeatureStore] = []

    def write() -> None:
        try:
            start.wait()
            for _ in range(5):
                writer = FeatureStore(tmp_path, code=_fixed_code)
                writer.write(key, frame)
                assert (writer.stats.writes, writer.stats.unstorable) == (1, 0)
        except BaseException as exc:
            errors.append(exc)

    def read() -> None:
        try:
            start.wait()
            for _ in range(40):
                reader = FeatureStore(tmp_path, code=_fixed_code)
                readers.append(reader)
                reads.append(reader.read(key))
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=write) for _ in range(8)] + [threading.Thread(target=read)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors, errors
    assert sum(reader.stats.corrupt for reader in readers) == 0
    assert all(item is None or (isinstance(item, type(frame)) and identical(frame, item)) for item in reads)
    final = store.read(key)
    assert final is not None and identical(frame, final)
    assert sorted(entry.name for entry in tmp_path.iterdir()) == [f"{key}.scores"]


_CHILD = """
import json, sys, time
from pathlib import Path
import pandas as pd
from starquant_alpha.panel import Panel
from starquant_alpha.signals import get_signal
from starquant_cli.research_feature_store import FeatureStore
store_dir, start, august, symbols, params = sys.argv[1], float(sys.argv[2]), Path(sys.argv[3]), sys.argv[4], sys.argv[5]
panel = Panel.from_frames({s: pd.read_parquet(august / s / "1h.parquet") for s in symbols.split(",")}, interval="1h")
params = json.loads(params)
store = FeatureStore(Path(store_dir))
key = store.key("tsmom", params, panel)
frame = get_signal("tsmom").compute(panel, params)
while time.time() < start:
    time.sleep(0.0005)
store.write(key, frame)
print(key, store.stats.writes, store.stats.unstorable)
"""


def test_writers_in_separate_processes_agree_on_the_key_and_publish_one_whole_entry(tmp_path: Path) -> None:
    """四个进程各自算键、各自现算，同一时刻写同一个键。键跨进程相同，盘上是一个完整的条目。"""
    store_dir, august = tmp_path / "store", FIXTURES / "august_2026"
    start = time.time() + 4.0
    args = [str(store_dir), str(start), str(august), ",".join(AUGUST_SYMBOLS), json.dumps(PARAMS)]
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    children = [
        subprocess.Popen(
            [sys.executable, "-c", _CHILD, *args], cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        for _ in range(4)
    ]
    outputs = [child.communicate(timeout=120) for child in children]
    assert all(child.returncode == 0 for child in children), [err.decode() for _out, err in outputs]
    lines = [out.decode().split() for out, _err in outputs]
    assert {line[0] for line in lines} == {lines[0][0]} and all(line[1:] == ["1", "0"] for line in lines)
    parent = FeatureStore(store_dir)
    panel = load_august_panel(august)
    key = parent.key("tsmom", PARAMS, panel)
    assert key == lines[0][0], "同一份代码、数据与参数，在两个进程里得到了两个键"
    stored = parent.read(key)
    assert stored is not None and identical(get_signal("tsmom").compute(panel, PARAMS), stored)
    assert sorted(entry.name for entry in store_dir.iterdir()) == [f"{key}.scores"]


def test_eviction_keeps_the_store_under_its_cap_and_deletes_only_its_own_names(
    august_panel: Panel, tmp_path: Path
) -> None:
    probe = FeatureStore(tmp_path, code=_fixed_code)
    probe.scores("tsmom", PARAMS, august_panel)
    size = probe.path(probe.key("tsmom", PARAMS, august_panel)).stat().st_size
    probe.path(probe.key("tsmom", PARAMS, august_panel)).unlink()
    store = FeatureStore(tmp_path, cap_bytes=int(size * 2.6), code=_fixed_code)
    variants = [{**PARAMS, "return_scale": scale} for scale in (0.21, 0.22, 0.23)]
    paths = [store.path(store.key("tsmom", params, august_panel)) for params in variants]
    stale, fresh = tmp_path / f".{'a' * 64}.1.{'b' * 32}.tmp", tmp_path / f".{'c' * 64}.2.{'d' * 32}.tmp"
    strangers = [tmp_path / "notes.txt", tmp_path / "abc.scores", stale, fresh]
    for stranger in strangers:
        stranger.write_bytes(b"not ours to judge")
    hours_ago = time.time() - 7_200
    os.utime(stale, (hours_ago, hours_ago))
    os.utime(strangers[1], (hours_ago - 100, hours_ago - 100))  # 最旧：不认名字的淘汰会先删它
    store.scores("tsmom", variants[0], august_panel)
    store.scores("tsmom", variants[1], august_panel)
    os.utime(paths[0], (hours_ago, hours_ago))
    os.utime(paths[1], (hours_ago + 10, hours_ago + 10))
    store.scores("tsmom", variants[0], august_panel)  # 一次命中：它成了最近用过的
    store.scores("tsmom", variants[2], august_panel)  # 第三份超了顶：淘汰最久没用的那份
    assert (paths[0].exists(), paths[1].exists(), paths[2].exists()) == (True, False, True)
    assert store.stats.evicted == 1
    assert [path.exists() for path in strangers] == [True, True, False, True], "只删自己写的名字，过期的临时文件除外"


def test_a_store_that_cannot_name_its_code_computes_and_writes_nothing(
    august_panel: Panel, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def refuse() -> str:
        raise Uncacheable("starquant_alpha/features.py changed after this process loaded its code")

    store = FeatureStore(tmp_path / "store", code=refuse)
    direct = get_signal("tsmom").compute(august_panel, PARAMS)
    for _ in range(2):
        _bit_for_bit(direct, store.scores("tsmom", PARAMS, august_panel))
    assert store.stats.bypassed == 2 and store.disabled is not None
    assert not (tmp_path / "store").exists()
    assert "feature store disabled for this process" in capsys.readouterr().err


def test_the_live_loop_cannot_reach_the_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """结构上：只有 `starquant_cli` 提到它。行为上：变量打开时，实盘建模入口给的仍是 `AlphaModel` 本身。"""
    names = ("research_feature_store", "with_feature_store", "StoredScoresModel", "feature_scores", ENV)
    packages = (
        "starquant_alpha",
        "starquant_data",
        "starquant_exchange",
        "starquant_governance",
        "starquant_live",
        "starquant_shared",
    )
    offenders = [
        str(path.relative_to(ROOT))
        for package in packages
        for path in sorted((ROOT / package).rglob("*.py"))
        if any(name in path.read_text(encoding="utf-8") for name in names)
    ]
    assert not offenders, offenders
    monkeypatch.chdir(ROOT)
    monkeypatch.setenv(ENV, str(tmp_path))
    model, _registry = build_model_from_profile(load_yaml("config/live.demo.yaml"))
    assert type(model) is AlphaModel
    assert not any(tmp_path.iterdir())


def test_research_is_off_until_the_variable_says_otherwise(
    august_panel: Panel, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile = load_yaml(str(ROOT / "config" / "live.demo.yaml"))
    entry = StrategyEntry(id="tsmom", params=PARAMS)
    plain = AlphaModel(entries=(entry,), portfolio=_model(entry, profile, "1h", 48).portfolio, interval="1h")
    for value in (None, "", "0", "off"):
        if value is None:
            monkeypatch.delenv(ENV, raising=False)
        else:
            monkeypatch.setenv(ENV, value)
        assert store_from_env() is None
        assert with_feature_store(plain) is plain
        assert type(_model(entry, profile, "1h", 48)) is AlphaModel
        _bit_for_bit(get_signal("tsmom").compute(august_panel, PARAMS), feature_scores("tsmom", PARAMS, august_panel))
    monkeypatch.setenv(ENV, "1")
    default = store_from_env()
    assert default is not None and default.root == ROOT / ".starquant" / "features"
    monkeypatch.setenv(ENV, str(tmp_path))
    chosen = store_from_env()
    assert chosen is not None and chosen.root == tmp_path.resolve()
    carried = with_feature_store(plain)
    assert carried is not plain and research_feature_store.StoredScoresModel is type(carried)
    assert {name: getattr(carried, name) for name in plain.__dataclass_fields__} == {
        name: getattr(plain, name) for name in plain.__dataclass_fields__
    }


def test_pandas_internals_that_moved_cost_a_recompute_not_the_run(
    august_panel: Panel, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """store 读 pandas 的私有 block 结构。哪天它变了，算键就会抛非 `Uncacheable` 的异常：照算，计数，说一句。"""

    def moved(frame: object) -> tuple[object, ...]:
        raise AttributeError("'DataFrame' object has no attribute '_mgr'")

    monkeypatch.setattr(research_feature_store, "_blocks", moved)
    store = FeatureStore(tmp_path, code=_fixed_code)
    _bit_for_bit(get_signal("tsmom").compute(august_panel, PARAMS), store.scores("tsmom", PARAMS, august_panel))
    assert (store.stats.uncacheable, store.stats.writes) == (1, 0)
    assert "feature store could not key tsmom: AttributeError" in capsys.readouterr().err
