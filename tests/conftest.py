from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from starquant_alpha.panel import Panel
from starquant_live import lock

# M-003's second threshold, wired here because a hook only fires from a conftest.  Imported rather
# than re-declared so there is exactly one copy of the arithmetic, and it is the one under test.
from tests.architecture.suite_duration import (  # noqa: F401 - pytest collects these by name
    pytest_configure,
    pytest_sessionfinish,
)

FIXTURES = Path(__file__).parent / "fixtures"
AUGUST_SYMBOLS = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT")


def load_august_panel(august_dir: Path) -> Panel:
    frames = {symbol: pd.read_parquet(august_dir / symbol / "1h.parquet") for symbol in AUGUST_SYMBOLS}
    return Panel.from_frames(frames, interval="1h")


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture(scope="session")
def august_dir() -> Path:
    return FIXTURES / "august_2026"


@pytest.fixture(scope="session")
def august_panel(august_dir: Path) -> Panel:
    return load_august_panel(august_dir)


@pytest.fixture(scope="session")
def august_baseline(august_dir: Path) -> dict:
    return json.loads((august_dir / "baseline-report.json").read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def isolated_trials_ledger(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the one ledger at a throwaway file for every test, without anyone having to remember.

    DL-K1 fixed the ledger's address so `--out` can no longer move it.  That is the right production
    behaviour and a live hazard for the test suite: a CLI test that runs `research book` would append
    real trials to `reports/research/trials.jsonl` and raise the DSR denominator for every strategy in
    the repository.  Autouse rather than opt-in, because the failure mode of forgetting is silent and
    permanent - the ledger is append-only by design, so a bad row cannot be taken back out.
    """
    path = tmp_path_factory.mktemp("trials-ledger") / "trials.jsonl"
    monkeypatch.setenv("STARQUANT_TRIALS_LEDGER", str(path))
    return path


@pytest.fixture(autouse=True)
def isolated_app_support(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The same hazard as the ledger above, aimed at the live state directory.

    `starquant_live.lock.APP_SUPPORT` is the account's address - the instance lock and the kill switch
    both hang off it, deliberately absolute so that seven worktrees contend for one file (L1-07).
    That is right in production and a live hazard here: a test only has to reach a helper that
    defaults `root=None` and it writes into the directory a trading loop is using.

    It happened.  2026-09-07T19:20:11Z, `682f6697fa93eca6.KILL_SWITCH` reading `engaged`, left in the
    operator's Application Support by `test_flatten_engages_every_path` - which had isolated the
    profile's `kill_switch_path` to `tmp_path` AND used a fake env var name, and still got there
    through `account_kill_switches()`.  Foreign fingerprint, so the running book was unaffected; had
    the test named the real `api_key_env`, a kill switch fails toward stopping and the book would
    have halted until somebody deleted the file by hand.

    Autouse for the ledger's reason: forgetting is silent, and this one is silent in the direction of
    an emergency stop.  `tests/architecture/test_tests_never_touch_the_real_app_support.py` is what
    keeps one redirected constant sufficient.
    """
    root = tmp_path_factory.mktemp("app-support")
    monkeypatch.setattr(lock, "APP_SUPPORT", root)
    return root


@pytest.fixture(autouse=True)
def feature_store_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """`STARQUANT_FEATURE_STORE` exported in a developer's shell must not reach the suite (#9.6).

    Off is what every research test was written against, and on would write cache files into whatever
    directory the shell names.  A test that wants the store sets the variable itself.
    """
    monkeypatch.delenv("STARQUANT_FEATURE_STORE", raising=False)
