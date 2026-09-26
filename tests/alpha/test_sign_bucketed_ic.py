"""KILL-042: separating "the signal is wrong" from "the magnitude is uninformative"."""

from __future__ import annotations

import numpy as np
import pandas as pd

from starquant_alpha.validation.metrics import sign_bucketed_ic


def _frames(scores: np.ndarray, forward: np.ndarray) -> tuple[pd.DataFrame, pd.DataFrame]:
    index = pd.date_range("2024-01-01", periods=len(scores), freq="h", tz="UTC")
    return pd.DataFrame({"A": scores}, index=index), pd.DataFrame({"A": forward}, index=index)


def test_a_right_sign_with_an_inverted_magnitude_is_reported_as_such() -> None:
    """The tsmom case: the direction earns while a bigger score predicts a slightly smaller move."""
    rng = np.random.default_rng(0)
    n = 4_000
    scores = rng.uniform(0.2, 1.0, n) * rng.choice([-1.0, 1.0], n)
    forward = np.sign(scores) * (0.02 - 0.01 * np.abs(scores)) + rng.normal(0, 0.001, n)
    result = sign_bucketed_ic(*_frames(scores, forward), horizon=1, threshold=0.2)
    assert result["long"]["mean_forward_return"] > 0 > result["short"]["mean_forward_return"]
    assert result["long"]["ic"] < 0 and result["short"]["ic"] < 0, "within a bucket, bigger predicts smaller"
    assert result["long"]["hit_rate"] > 0.9 and result["samples"] == n


def test_a_genuinely_wrong_signal_looks_different_from_an_uninformative_magnitude() -> None:
    rng = np.random.default_rng(1)
    n = 2_000
    scores = rng.uniform(0.2, 1.0, n) * rng.choice([-1.0, 1.0], n)
    forward = -np.sign(scores) * 0.01 + rng.normal(0, 0.001, n)
    result = sign_bucketed_ic(*_frames(scores, forward), horizon=1, threshold=0.2)
    assert result["long"]["mean_forward_return"] < 0 < result["short"]["mean_forward_return"]


def test_labels_are_sampled_non_overlapping() -> None:
    """D-011: overlapping windows are what made the original time-series IC look strongly negative."""
    scores = np.arange(100, dtype=float) / 100.0 + 0.2
    forward = np.arange(100, dtype=float)
    result = sign_bucketed_ic(*_frames(scores, forward), horizon=10, threshold=0.2)
    assert result["samples"] == 10, "every tenth bar, not every bar"


def test_a_bucket_with_no_dispersion_reports_no_ic_rather_than_a_number() -> None:
    """Under conviction_mode sign every actionable score is +-1, so a within-bucket IC does not exist."""
    rng = np.random.default_rng(2)
    n = 500
    scores = rng.choice([-1.0, 1.0], n)
    forward = scores * 0.01 + rng.normal(0, 0.001, n)
    result = sign_bucketed_ic(*_frames(scores, forward), horizon=1, threshold=0.2)
    assert result["long"]["ic"] is None and result["short"]["ic"] is None
    assert result["long"]["mean_forward_return"] > 0, "the direction is still measurable"


def test_empty_and_tiny_buckets_are_safe() -> None:
    result = sign_bucketed_ic(*_frames(np.full(50, 0.5), np.full(50, 0.01)), horizon=1, threshold=0.2)
    assert result["short"]["n"] == 0 and result["short"]["ic"] is None
    assert result["long"]["n"] == 50
