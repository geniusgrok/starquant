"""Restoration must refuse a different frozen input instead of using it."""

from pathlib import Path

import pytest

from scripts.restore_btc import require_digest


def test_restore_refuses_a_corrupt_or_different_input(tmp_path: Path) -> None:
    path = tmp_path / "input.npz"
    path.write_bytes(b"different")
    with pytest.raises(ValueError, match="identity mismatch"):
        require_digest(path, "0" * 64)
