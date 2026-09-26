"""Proof, on the real archive and the shipped registry, that B (`flow` warm-up knob) and D (keying
`strategy_targets` by id) move nothing.

Both changes are meant to be invisible today, and "meant to be" is not a measurement.  This runs the
whole model - `build_model(registry, profile).evaluate(panel, membership)`, i.e. per-strategy targets
through `weights_from` - on `.starquant/data` under `config/alpha_registry.yaml`, and writes the weight
frame plus a digest of every per-strategy target frame.  Run it once per tree and compare.

    # the tree the editable install points at (main checkout)
    python scratchpad/flow_warmup_and_keying_are_bit_identical.py /tmp/before.parquet
    # this worktree, and compare against what the first run wrote
    PYTHONPATH=. python scratchpad/flow_warmup_and_keying_are_bit_identical.py /tmp/after.parquet /tmp/before.parquet

`tsmom` has `crowding_window: 72`, so the panel MUST carry funding or `strategy_targets` raises
`FundingUnavailable` - which is the guard doing its job, not a loading problem.  `_load(..., True)` is
the loader that supplies it.

It also prints the thing that decides whether B could ever have been reachable in production: the
number of bars on which `expansion` is un-warm AND the imbalance is not, under the registry's own
window pair.  With `window` 168 against `volume_window` 48 that count is zero, which is why the default
stays 1.0 and adopting `None` is a decision rather than a correction.
"""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from starquant_alpha.features import taker_buy_ratio, volume_ratio
from starquant_alpha.signals import get_signal
from starquant_cli.research_cmd import _load, _membership, _resolve_symbols
from starquant_live.composition import build_model, load_registry
from starquant_shared.config import load_yaml

# Read-only.  A worktree has no archive of its own, so `STARQUANT_DATA_ROOT` points this at the shared one.
ROOT = os.environ.get("STARQUANT_DATA_ROOT", ".starquant/data")


def digest(frame: pd.DataFrame) -> str:
    """Bytes of the values plus the labels: a frame that reordered its columns is not the same frame."""
    payload = frame.to_numpy(dtype=float).tobytes() + "|".join(map(str, frame.columns)).encode()
    return hashlib.sha256(payload + str(frame.index[0]).encode() + str(frame.index[-1]).encode()).hexdigest()[:16]


def main(argv: list[str]) -> None:
    import starquant_alpha

    print(f"starquant_alpha from {starquant_alpha.__file__}")
    profile = load_yaml("config/live.demo.yaml")
    registry = load_registry(Path("config/alpha_registry.yaml"))
    symbols = _resolve_symbols(ROOT, "", "1h", "pit")
    panel = _load(ROOT, symbols, "1h", None, None, True)
    membership = _membership(ROOT, "pit", panel, 0)
    print(f"panel {panel.index[0]} .. {panel.index[-1]}  {len(panel.index)} bars x {len(panel.symbols)} symbols")
    print(f"funding: {panel.settled_symbols} symbols carry at least one settlement")

    model = build_model(registry, profile)
    weights, combined, per_strategy = model.evaluate(panel, membership)
    print(f"entries: {[entry.id for entry in model.entries]}")
    print(f"per-strategy keys, in order: {list(per_strategy)}")
    for name, frame in per_strategy.items():
        print(f"  targets[{name}] {digest(frame)}  non-null {int(frame.notna().to_numpy().sum()):,}")
    print(f"combined {digest(combined)}")
    print(f"weights  {digest(weights)}  gross mean {weights.abs().sum(axis=1).mean():.6f}")

    # B's reachability under the registry's own parameters, not under the dataclass defaults.
    params = get_signal("flow").canonical_params(dict(next(e for e in model.entries if e.id == "flow").params))
    expansion = volume_ratio(panel.volume, int(params["volume_window"])).clip(upper=1.0)
    imbalance = taker_buy_ratio(panel.taker_buy_quote, panel.quote_volume, int(params["window"])) - 0.5
    reachable = int((expansion.isna() & imbalance.notna()).to_numpy().sum())
    print(
        f"flow window={params['window']} volume_window={params['volume_window']} "
        f"volume_warmup_fill={params.get('volume_warmup_fill', '<absent>')}: "
        f"symbol-bars where the fill is visible = {reachable:,}"
    )

    out = Path(argv[1])
    weights.to_parquet(out)
    print(f"wrote {out}")
    if len(argv) > 2:
        other = pd.read_parquet(argv[2])
        left, right = weights.to_numpy(dtype=float), other.to_numpy(dtype=float)
        same_nan = (np.isnan(left) == np.isnan(right)).all()
        seen = ~np.isnan(left) & ~np.isnan(right)
        print(
            f"vs {argv[2]}: same shape {left.shape == right.shape}, same NaN mask {bool(same_nan)}, "
            f"max |diff| {np.abs(left[seen] - right[seen]).max():.3e}"
        )
        # `check_freq=False`: a parquet round-trip drops the index's inferred `freq`, which is an
        # attribute of the object and not of the book.
        pd.testing.assert_frame_equal(weights, other, check_freq=False)
        print("assert_frame_equal: identical")


if __name__ == "__main__":
    main(sys.argv)
