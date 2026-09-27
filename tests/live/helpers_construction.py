"""Build the live config the shipped profile describes, for tests that pin the construction digest."""

from __future__ import annotations

from pathlib import Path

import yaml

from starquant_alpha.registry import parse_registry
from starquant_live.config import live_config

ROOT = Path(__file__).resolve().parents[2]


def live_config_for_profile():
    profile = yaml.safe_load((ROOT / "config" / "live.demo.yaml").read_text(encoding="utf-8"))
    registry = parse_registry(yaml.safe_load((ROOT / "config" / "alpha_registry.yaml").read_text(encoding="utf-8")))
    return live_config(profile, ["BTCUSDT"], registry, dry_run=True)
