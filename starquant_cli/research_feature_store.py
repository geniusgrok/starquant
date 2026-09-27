"""Research's feature store (#9.6): a content-addressed, read-through disk cache of signal scores.

**Which layer, measured before it was built** (2026-09-25, the point-in-time panel, 212 symbols x 50,225
bars; `scratchpad/feature_store_where_research_time_goes_20260925.py`).  One `validate`-shaped run - the
16 tsmom grid cells plus the flow sleeve, 17 evaluations, 110.2 s - spends 5.5 s (5.0%) inside
`starquant_alpha.features`, 14.0 s (12.7%) in the signal layer that calls it, and most of the rest in
recursions over the WEIGHTS: `ewma_portfolio_vol` 41.9 s, the exit overlay 22.2 s, the backtest 9.8 s,
the band 6.4 s.  Those are not features and cannot be keyed without the weights.  One primitive costs
10-110 ms and a checked read of an 85 MB frame about 30 ms, so a store at the primitive level would
mostly trade one cost for another.  A signal's `compute(panel, params)` is the last step that depends
only on data, parameters and code, and it is where the time is: chanlun 32.7 s, meanrev 2.8 s, tsmom
0.55 s per call.  So the unit here is one signal's score frame.

**Key.**  sha256 over the format version, the signal id, the params (strict JSON: builtin types only, floats
by `float.hex`), the panel's digest and the code digest.  The panel digest covers every `Panel` field:
values, index, columns, dtypes, block structure, memory order, and which fields share an index object.  The
code digest covers every `starquant_alpha/**/*.py`, this file, and the python, numpy, pandas and machine
versions.  Change any of them and the key moves, so an old entry is never read again.

**Exact means the block layout too.**  Frames whose values are equal to the bit can still differ in their
blocks, and that changes results downstream.  Measured: the same weights in C and in F order move
`ewma_portfolio_vol` on 6,467 of 50,225 bars (by up to 2.2e-16), because `w[t] @ cov` takes a different BLAS
path for a strided row.  meanrev returns 212 blocks, tsmom one.  So an entry stores every block with its
placement and order and is rebuilt with `pandas.api.internals.create_dataframe_from_blocks`.  Before an
entry is published, the writer reads it back and compares index, columns, blocks and bits with the frame it
computed.  A frame that does not survive that is computed every time and never stored.

**Live cannot reach it.**  `starquant_live` may not import `starquant_cli` (`test_import_rules`), and the live
loop builds its model through `composition.build_model`, never through `with_feature_store`.  The process that
runs the loop does import this module, because `starquant_cli/__init__.py` registers every command group, but
importing it only defines names.  Research turns it on with `STARQUANT_FEATURE_STORE`: unset, empty or `0` is
off; `1` means `<checkout>/.starquant/features` (ignored by git); anything else is a directory.  Off,
`with_feature_store` returns the model it was given.

**Disk.**  One entry per signal evaluation, 85 MB each on the panel above.  After each write the store evicts
the least recently used entries (a hit touches its entry) until it is under 80% of `cap_bytes` (default
8 GiB), and it removes its own temporary files once they are an hour old.  It deletes only names it writes
itself.  Deleting the whole directory is always safe: it holds nothing that cannot be recomputed.

**Failure is a miss.**  An entry that fails its magic, header, length, key or payload sha256 is ignored and
recomputed, and the rewrite replaces it.  Writers use unique temporary names, fsync, then `os.replace`.  So
two writers of one key each publish a whole file, and a reader sees one of them.

**Code that changed under a running process.**  The code digest is read from disk, so it must describe the
code this process loaded.  Before hashing, every `starquant_alpha` module is imported, so none can arrive later.
A source file modified after this module was imported disables the store for the process: it computes and
reports why.  One window is left open.  A file imported before this module and edited within the same few
milliseconds would go unseen.
"""

from __future__ import annotations

import contextlib
import dataclasses
import hashlib
import importlib
import json
import os
import pkgutil
import platform
import re
import sys
import time
import uuid
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import click
import numpy as np
import pandas as pd

import starquant_alpha
from starquant_alpha.model import AlphaModel
from starquant_alpha.panel import Panel
from starquant_alpha.signals import get_signal

ENV = "STARQUANT_FEATURE_STORE"
FORMAT = 1
MAGIC = b"BDFSTOR1"
DEFAULT_CAP_BYTES = 8 * 1024**3
LOW_WATER = 0.8
STALE_TMP_SECONDS = 3600
_ENTRY = re.compile(r"^[0-9a-f]{64}\.scores$")
_TMP = re.compile(r"^\.[0-9a-f]{64}\.\d+\.[0-9a-f]{32}\.tmp$")
_STARTED_NS = time.time_ns()


class Uncacheable(Exception):
    """This input or output has no exact key or no exact stored form, so it is computed and not stored."""


@dataclass
class StoreStats:
    hits: int = 0
    misses: int = 0
    writes: int = 0
    uncacheable: int = 0  # no key: the params or the panel fall outside what can be hashed exactly
    unstorable: int = 0  # computed, but its stored form would not read back identical
    corrupt: int = 0  # entries that failed verification and were treated as misses
    evicted: int = 0
    bypassed: int = 0  # calls made while the store was disabled for this process
    bytes_read: int = 0
    bytes_written: int = 0


def _blocks(frame: pd.DataFrame) -> tuple[Any, ...]:
    """pandas' blocks.  Private and absent from the stubs; any drift raises, and a raise is a miss."""
    return tuple(frame._mgr.blocks)


def _order(values: np.ndarray) -> str:
    return "C" if values.flags.c_contiguous else "F" if values.flags.f_contiguous else "N"


def _c_view(values: np.ndarray, order: str) -> np.ndarray:
    """The block's own memory as a flat C array, without copying (only for C or F blocks)."""
    return (values if order == "C" else values.T).reshape(-1)


def _numeric_blocks(frame: pd.DataFrame) -> list[tuple[np.ndarray, np.ndarray, str]]:
    if type(frame) is not pd.DataFrame or frame.attrs or not frame.flags.allows_duplicate_labels:
        raise Uncacheable("not a plain DataFrame")
    out = []
    for block in _blocks(frame):
        values = block.values
        if not isinstance(values, np.ndarray) or values.ndim != 2 or values.dtype.kind not in "biuf":
            raise Uncacheable("a block that is not a 2-D numpy array of numbers")
        order = _order(values)
        if order == "N":
            raise Uncacheable("a block that is neither C nor F contiguous")
        out.append((values, np.ascontiguousarray(block.mgr_locs.as_array, dtype="<i8"), order))
    return out


def _stamps(index: pd.DatetimeIndex) -> np.ndarray:
    """Epoch integers in the index's own unit; `.values` of a tz-aware index is already UTC."""
    return np.ascontiguousarray(index.values.view("<i8"))


def _name(value: object) -> str | None:
    if value is None or isinstance(value, str):
        return value
    raise Uncacheable("an axis name that is not a string")


def _axis(index: pd.Index) -> dict[str, Any]:
    if isinstance(index, pd.DatetimeIndex):
        return {
            "kind": "datetime",
            "dtype": str(index.dtype),
            "unit": index.unit,
            "tz": None if index.tz is None else str(index.tz),
            "name": _name(index.name),
            "freq": index.freqstr,
            "length": len(index),
        }
    if isinstance(index, pd.MultiIndex) or not all(isinstance(label, str) for label in index):
        raise Uncacheable("an axis that is neither datetimes nor string labels")
    return {"kind": "labels", "dtype": str(index.dtype), "name": _name(index.name), "labels": list(index)}


def _frame_digest(frame: pd.DataFrame) -> str:
    digest = hashlib.sha256()
    axes = {"index": _axis(frame.index), "columns": _axis(frame.columns)}
    digest.update(json.dumps(axes, separators=(",", ":")).encode())
    if isinstance(frame.index, pd.DatetimeIndex):
        digest.update(_stamps(frame.index).tobytes())
    for values, placement, order in _numeric_blocks(frame):
        digest.update(json.dumps([values.dtype.str, list(values.shape), order]).encode())
        digest.update(placement.tobytes())
        digest.update(memoryview(_c_view(values, order)).cast("B"))
    return digest.hexdigest()


def _ordinals(objects: list[object]) -> list[int]:
    """Which slots hold the same object.  pandas takes fast paths on `is`, so sharing is an input too."""
    seen: dict[int, int] = {}
    return [seen.setdefault(id(item), len(seen)) for item in objects]


def panel_digest(panel: Panel) -> str:
    """Every field of the panel, in declaration order, so a field added later is covered without an edit."""
    if type(panel) is not Panel:
        raise Uncacheable("not a plain Panel")
    fields: list[list[Any]] = []
    frames: list[pd.DataFrame] = []
    for item in dataclasses.fields(panel):
        value = getattr(panel, item.name)
        if value is None or isinstance(value, str):
            fields.append([item.name, value])
        elif isinstance(value, pd.DataFrame):
            fields.append([item.name, "frame", len(frames)])
            frames.append(value)
        elif isinstance(value, dict) and all(
            isinstance(k, str) and isinstance(v, pd.DataFrame) for k, v in value.items()
        ):
            fields.append([item.name, "frames", [[name, len(frames) + n] for n, name in enumerate(value)]])
            frames.extend(value.values())
        else:
            raise Uncacheable(f"panel field {item.name} holds a {type(value).__name__}")
    identity = [_ordinals(list(frames)), _ordinals([f.index for f in frames]), _ordinals([f.columns for f in frames])]
    with ThreadPoolExecutor(max_workers=max(1, min(len(frames), 8))) as pool:
        digests = list(pool.map(_frame_digest, frames))  # hashlib drops the GIL on large buffers
    return hashlib.sha256(json.dumps([fields, identity, digests]).encode()).hexdigest()


def _canonical(value: object) -> object:
    """Params as strict JSON.  Builtin types only: a numpy scalar is refused rather than guessed at."""
    if value is None or isinstance(value, bool | str) or type(value) is int:
        return value
    if type(value) is float:
        return {"float": value.hex()}
    if type(value) is list:
        return [_canonical(item) for item in value]
    if type(value) is tuple:
        return {"tuple": [_canonical(item) for item in value]}
    if type(value) is dict and all(isinstance(key, str) for key in value):
        return {"dict": [[key, _canonical(item)] for key, item in value.items()]}
    raise Uncacheable(f"a parameter of type {type(value).__name__}")


def _sources() -> tuple[Path, list[Path]]:
    package = Path(starquant_alpha.__file__).resolve().parent
    return package.parent, [*sorted(package.rglob("*.py")), Path(__file__).resolve()]


def code_digest(started_ns: int = _STARTED_NS) -> str:
    """The code a score was computed by: `starquant_alpha`, this module, and the interpreter and libraries."""
    for module in pkgutil.walk_packages(starquant_alpha.__path__, "starquant_alpha."):
        importlib.import_module(module.name)  # loaded now, so nothing arrives after the files are read
    digest = hashlib.sha256()
    for part in (FORMAT, platform.python_version(), np.__version__, pd.__version__, platform.machine(), sys.byteorder):
        digest.update(f"{part}\0".encode())
    root, files = _sources()
    for path in files:
        if "__pycache__" in path.parts:
            continue
        if path.stat().st_mtime_ns > started_ns:
            raise Uncacheable(f"{path.relative_to(root)} changed after this process loaded its code")
        data = path.read_bytes()
        digest.update(f"{path.relative_to(root).as_posix()}\0{len(data)}\0".encode() + data)
    return digest.hexdigest()


def encode(key: str, frame: pd.DataFrame) -> list[bytes]:
    """The entry as a list of chunks: magic, header length, header, then the payload it checksums."""
    if not isinstance(frame.index, pd.DatetimeIndex):
        raise Uncacheable("rows that are not datetimes")
    blocks = _numeric_blocks(frame)
    payload = [_stamps(frame.index).tobytes()]
    meta = []
    for values, placement, order in blocks:
        meta.append({"dtype": values.dtype.str, "shape": list(values.shape), "order": order, "placed": len(placement)})
        payload += [placement.tobytes(), values.tobytes(order="F" if order == "F" else "C")]
    checksum = hashlib.sha256()
    for chunk in payload:
        checksum.update(chunk)
    header = {
        "format": FORMAT,
        "key": key,
        "payload_bytes": sum(len(chunk) for chunk in payload),
        "payload_sha256": checksum.hexdigest(),
        "index": _axis(frame.index),
        "columns": _axis(frame.columns),
        "blocks": meta,
    }
    head = json.dumps(header, separators=(",", ":")).encode()
    return [MAGIC, len(head).to_bytes(8, "little"), head, *payload]


def decode(blob: bytes, key: str) -> pd.DataFrame:
    """An entry back into the frame it was written from.  Raises `ValueError` on anything unexpected."""
    if blob[:8] != MAGIC:
        raise ValueError("bad magic")
    size = int.from_bytes(blob[8:16], "little")
    header = json.loads(blob[16 : 16 + size])
    payload = memoryview(blob)[16 + size :]
    if header["format"] != FORMAT or header["key"] != key or header["payload_bytes"] != len(payload):
        raise ValueError("header does not describe this entry")
    if hashlib.sha256(payload).hexdigest() != header["payload_sha256"]:
        raise ValueError("payload checksum mismatch")
    rows, cols = header["index"], header["columns"]
    stamps = np.frombuffer(payload, dtype="<i8", count=rows["length"]).view(f"datetime64[{rows['unit']}]")
    index = pd.DatetimeIndex(stamps.copy(), name=rows["name"])
    if rows["tz"] is not None:
        index = index.tz_localize("UTC").tz_convert(rows["tz"])
    if rows["freq"] is not None:
        index = pd.DatetimeIndex(index, freq=rows["freq"])
    columns = pd.Index(cols["labels"], dtype=cols["dtype"], name=cols["name"])
    offset, built = 8 * rows["length"], []
    for block in header["blocks"]:
        placement = np.frombuffer(payload, dtype="<i8", count=block["placed"], offset=offset).astype(np.intp)
        offset += 8 * block["placed"]
        dtype, shape = np.dtype(block["dtype"]), tuple(block["shape"])
        count = int(np.prod(shape))
        values = np.frombuffer(payload, dtype=dtype, count=count, offset=offset).reshape(shape, order=block["order"])
        built.append((values.copy(order="K"), placement))
        offset += count * dtype.itemsize
    if offset != len(payload):
        raise ValueError("payload length does not match its blocks")
    internals = importlib.import_module("pandas.api.internals")  # absent from pandas-stubs
    frame: pd.DataFrame = internals.create_dataframe_from_blocks(built, index=index, columns=columns)
    return frame


def identical(left: pd.DataFrame, right: pd.DataFrame) -> bool:
    """Same labels, same blocks in the same order and memory layout, same bits.  Stricter than `_bit_for_bit`."""
    if not (left.index.identical(right.index) and left.index.dtype == right.index.dtype):
        return False
    if getattr(left.index, "freq", None) != getattr(right.index, "freq", None):
        return False
    if not (left.columns.identical(right.columns) and left.columns.dtype == right.columns.dtype):
        return False
    ours, theirs = _numeric_blocks(left), _numeric_blocks(right)
    if len(ours) != len(theirs):
        return False
    for (a, place_a, order_a), (b, place_b, order_b) in zip(ours, theirs, strict=True):
        same_layout = (a.flags.c_contiguous, a.flags.f_contiguous) == (b.flags.c_contiguous, b.flags.f_contiguous)
        if a.dtype != b.dtype or a.shape != b.shape or order_a != order_b or not same_layout:
            return False
        if not np.array_equal(place_a, place_b):
            return False
        if not np.array_equal(_c_view(a, order_a).view(np.uint8), _c_view(b, order_b).view(np.uint8)):
            return False
    return True


@dataclass
class FeatureStore:
    root: Path
    cap_bytes: int = DEFAULT_CAP_BYTES
    code: Callable[[], str] = code_digest
    stats: StoreStats = field(default_factory=StoreStats)
    disabled: str | None = None
    code_hex: str | None = field(default=None, init=False)

    def path(self, key: str) -> Path:
        return self.root / f"{key}.scores"

    def key(self, signal_id: str, params: Mapping[str, Any], panel: Panel) -> str:
        if self.code_hex is None:
            self.code_hex = self.code()
        payload = [FORMAT, "signal_scores", signal_id, _canonical(dict(params)), panel_digest(panel), self.code_hex]
        return hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode()).hexdigest()

    def scores(self, signal_id: str, params: Mapping[str, Any], panel: Panel) -> pd.DataFrame:
        """`get_signal(signal_id).compute(panel, params)`, read from disk when this exact call was made before."""
        compute = get_signal(signal_id).compute
        if self.disabled is None and self.code_hex is None:
            try:
                self.code_hex = self.code()
            except Exception as exc:  # a store that cannot name the code it runs must key nothing
                self.disabled = f"{type(exc).__name__}: {exc}"
                click.echo(f"feature store disabled for this process: {self.disabled}", err=True)
        if self.disabled is not None:
            self.stats.bypassed += 1
            return compute(panel, params)
        try:
            key = self.key(signal_id, params, panel)
        except Uncacheable:
            self.stats.uncacheable += 1
            return compute(panel, params)
        except Exception as exc:  # e.g. pandas internals moved: an optimisation must not end the run
            self.stats.uncacheable += 1
            click.echo(f"feature store could not key {signal_id}: {type(exc).__name__}: {exc}", err=True)
            return compute(panel, params)
        cached = self.read(key)
        if cached is not None:
            return cached
        self.stats.misses += 1
        frame = compute(panel, params)
        self.write(key, frame)
        return frame

    def read(self, key: str) -> pd.DataFrame | None:
        path = self.path(key)
        try:
            blob = path.read_bytes()
        except OSError:
            return None
        try:
            frame = decode(blob, key)
        except Exception:  # any way an entry can be wrong is the same answer: recompute it
            self.stats.corrupt += 1
            return None
        self.stats.hits += 1
        self.stats.bytes_read += len(blob)
        with contextlib.suppress(OSError):  # recency for eviction; losing a race to an evictor costs nothing
            os.utime(path)
        return frame

    def write(self, key: str, frame: pd.DataFrame) -> None:
        """Publish `frame` under `key` only if what lands on disk reads back identical.  Never raises."""
        tmp = self.root / f".{key}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
        try:
            chunks = encode(key, frame)
            self.root.mkdir(parents=True, exist_ok=True)
            with tmp.open("wb") as handle:
                for chunk in chunks:
                    handle.write(chunk)
                handle.flush()
                os.fsync(handle.fileno())
            if not identical(frame, decode(tmp.read_bytes(), key)):
                raise Uncacheable("the stored form does not read back identical")
            os.replace(tmp, self.path(key))
        except Uncacheable:
            self.stats.unstorable += 1
            return
        except Exception as exc:  # a cache that fails to write costs a recompute, never the run
            self.stats.unstorable += 1
            click.echo(f"feature store could not write {key[:12]}: {type(exc).__name__}: {exc}", err=True)
            return
        finally:
            tmp.unlink(missing_ok=True)
        self.stats.writes += 1
        self.stats.bytes_written += sum(len(chunk) for chunk in chunks)
        try:
            self.evict()
        except OSError as exc:
            click.echo(f"feature store could not evict: {exc}", err=True)

    def evict(self) -> None:
        """Least recently used first, down to `LOW_WATER` of the cap; only names this store writes."""
        entries: list[tuple[float, str, int]] = []
        now = time.time()
        with os.scandir(self.root) as items:
            for item in items:
                try:
                    stat = item.stat()
                    if _TMP.match(item.name) and now - stat.st_mtime > STALE_TMP_SECONDS:
                        os.unlink(item.path)
                    elif _ENTRY.match(item.name):
                        entries.append((stat.st_mtime, item.path, stat.st_size))
                except FileNotFoundError:
                    continue
        total = sum(size for _mtime, _path, size in entries)
        if total <= self.cap_bytes:
            return
        for _mtime, path, size in sorted(entries):
            if total <= self.cap_bytes * LOW_WATER:
                break
            try:
                os.unlink(path)
                self.stats.evicted += 1
            except FileNotFoundError:
                pass
            total -= size


_STORES: dict[Path, FeatureStore] = {}


def store_from_env() -> FeatureStore | None:
    """The process's store for `STARQUANT_FEATURE_STORE`, or None when research has not turned it on."""
    raw = os.environ.get(ENV, "").strip()
    if raw.lower() in {"", "0", "off", "false", "no"}:
        return None
    if raw.lower() in {"1", "on", "true", "yes"}:
        root = Path(__file__).resolve().parents[1] / ".starquant" / "features"
    else:
        root = Path(raw).resolve()  # no expanduser: the shell already expanded ~, and only lock.py may name home
    if root not in _STORES:
        _STORES[root] = FeatureStore(root)
        click.echo(f"feature store: {root} ({ENV})", err=True)  # never silent, like STARQUANT_TRIALS_LEDGER
    return _STORES[root]


@dataclass(frozen=True)
class StoredScoresModel(AlphaModel):
    """An `AlphaModel` whose one seam - `strategy_scores` - reads through a feature store.

    A subclass in the research layer rather than a field on `AlphaModel`, so that nothing the live loop
    executes changed.  The body mirrors `AlphaModel.strategy_scores`;
    `tests/cli/test_the_feature_store_is_exact.py` compares the two end to end, so a change there that
    this copy misses fails a test instead of moving a reading.
    """

    store: FeatureStore | None = field(default=None, compare=False, repr=False)

    def strategy_scores(self, panel: Panel, reference: pd.DataFrame | None = None) -> dict[str, pd.DataFrame]:
        if self.store is None:
            return super().strategy_scores(panel, reference)
        scored = panel if reference is None else panel.with_reference(reference)
        return {entry.id: self.store.scores(entry.id, entry.params, scored) for entry in self.entries}


def with_feature_store(model: AlphaModel) -> AlphaModel:
    """`model` itself when the store is off; otherwise the same model reading its scores through the store."""
    store = store_from_env()
    if store is None or isinstance(model, StoredScoresModel):
        return model
    values = {item.name: getattr(model, item.name) for item in dataclasses.fields(AlphaModel)}
    return StoredScoresModel(**values, store=store)


def feature_scores(signal_id: str, params: Mapping[str, Any], panel: Panel) -> pd.DataFrame:
    """One signal's scores for a caller that builds no model (`research diagnose`)."""
    store = store_from_env()
    if store is None:
        return get_signal(signal_id).compute(panel, params)
    return store.scores(signal_id, params, panel)
