"""D-024: an ensemble-level report records the registry it was computed against."""

from __future__ import annotations

from starquant_alpha.registry import parse_registry, registry_fingerprint
from starquant_alpha.signals import get_signal


def _canonical(signal_id: str, params: dict) -> dict:
    return get_signal(signal_id).canonical_params(params)


def _payload(**tsmom_params: object) -> dict:
    return {
        "version": 1,
        "ensemble": {"method": "mean", "turnover_penalty": 0.0},
        "books": {"flow_short": {"fraction": 1.0 / 3.0}},
        "strategies": [
            {"id": "tsmom", "enabled": True, "params": {"horizons": [168, 336, 720], **tsmom_params}},
            {"id": "flow", "enabled": True, "book": "flow_short", "params": {"window": 168}},
            {"id": "xsmom", "enabled": False, "params": {"skip_bars": 24}},
        ],
    }


def test_digest_follows_what_runs_not_how_the_file_is_written() -> None:
    base = registry_fingerprint(parse_registry(_payload()), _canonical)
    assert set(base["strategies"]) == {"tsmom", "flow"}, "a disabled strategy is not part of what runs"
    assert base["books"] == {"flow_short": 1.0 / 3.0}
    # writing a default out explicitly is not a change
    explicit = registry_fingerprint(parse_registry(_payload(entry_threshold=0.20)), _canonical)
    assert explicit["digest"] == base["digest"]
    # the parameter that moved the live book in round 7 does change it
    changed = registry_fingerprint(parse_registry(_payload(conviction_mode="sign")), _canonical)
    assert changed["digest"] != base["digest"]
    assert changed["strategies"]["tsmom"]["params"]["conviction_mode"] == "sign"


def test_the_case_this_exists_for() -> None:
    """P5, 2026-09-04: an overlay run finished at 02:10 and `conviction_mode: sign` merged at 02:25:58.

    The conclusion drawn at 02:2x rested on a measurement of a book that no longer existed, and nothing
    in the report said so.  With the fingerprint recorded, the two runs are distinguishable by their
    digest alone, without comparing wall-clock timestamps against a merge log.
    """
    before = registry_fingerprint(parse_registry(_payload()), _canonical)
    after = registry_fingerprint(parse_registry(_payload(conviction_mode="sign")), _canonical)
    assert before["digest"] != after["digest"]
    assert before["strategies"]["tsmom"]["params"]["conviction_mode"] == "score"
    assert after["strategies"]["tsmom"]["params"]["conviction_mode"] == "sign"


def test_digest_moves_with_the_ensemble_and_the_book_fractions() -> None:
    base = registry_fingerprint(parse_registry(_payload()), _canonical)
    other_method = _payload()
    other_method["ensemble"] = {"method": "rolling_zscore", "turnover_penalty": 0.0}
    assert registry_fingerprint(parse_registry(other_method), _canonical)["digest"] != base["digest"]
    other_fraction = _payload()
    other_fraction["books"] = {"flow_short": {"fraction": 0.2}}
    assert registry_fingerprint(parse_registry(other_fraction), _canonical)["digest"] != base["digest"]
    disabled = _payload()
    disabled["strategies"][1]["enabled"] = False
    assert registry_fingerprint(parse_registry(disabled), _canonical)["digest"] != base["digest"]


def test_fingerprint_without_a_canonicaliser_still_describes_the_registry() -> None:
    """The pure contract holds when the caller has no signal table (an unwritten default is then just absent)."""
    bare = registry_fingerprint(parse_registry(_payload()))
    assert bare["strategies"]["tsmom"]["params"] == {"horizons": [168, 336, 720]}
    assert len(bare["digest"]) == 64
    assert bare["digest"] != registry_fingerprint(parse_registry(_payload()), _canonical)["digest"]


def test_the_shipped_registry_fingerprints() -> None:
    from pathlib import Path

    from starquant_shared.config import load_yaml

    registry = parse_registry(load_yaml(Path(__file__).resolve().parents[2] / "config" / "alpha_registry.yaml"))
    fingerprint = registry_fingerprint(registry, _canonical)
    assert len(fingerprint["digest"]) == 64
    assert set(fingerprint["strategies"]) == {entry.id for entry in registry.enabled}
    for row in fingerprint["strategies"].values():
        assert row["params"], "a canonicalised entry always carries the signal's full parameter set"
