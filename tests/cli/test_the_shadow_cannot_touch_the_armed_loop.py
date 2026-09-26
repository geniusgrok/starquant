"""DL-G5: the two flags a canary needs, and the one rule that keeps them from being a second book.

`--state-dir` and `--registry` exist so a shadow loop can soak a candidate registry beside the armed
one.  Both refuse to run armed, for reasons that are different and both load-bearing:

* `state.json` carries the day's equity mark, the leaving set, the exit anchors and `stopped_books`.
  An armed loop reading a different copy of it is a second book trading the same account, and the
  account lock would NOT stop it - that lock is keyed on the API key, not on the directory.
* An armed loop is promoted by WRITING the registry file, as a transaction that can roll back
  (`starquant_governance.promote`).  Pointing an armed loop at a different file instead would produce a
  running book whose registry nothing on disk describes, which is KILL-Q15 with the sign flipped.
"""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from starquant_cli import main


def _run(*args: str) -> object:
    return CliRunner().invoke(main, ["live", "run", *args])


def test_state_dir_is_refused_on_an_armed_run() -> None:
    result = _run("--armed", "--state-dir", ".starquant/live-shadow", "--cycles", "0")
    assert result.exit_code != 0
    assert "--state-dir requires --dry-run or --paper" in result.output


def test_a_candidate_registry_is_refused_on_an_armed_run() -> None:
    result = _run("--armed", "--registry", "config/alpha_registry.candidate.yaml", "--cycles", "0")
    assert result.exit_code != 0
    assert "--registry requires --dry-run or --paper" in result.output


def test_both_flags_are_offered_and_documented() -> None:
    """A flag whose help does not say why it refuses gets used by someone who then works around it."""
    help_text = CliRunner().invoke(main, ["live", "run", "--help"]).output
    assert "--state-dir" in help_text and "--registry" in help_text
    assert "canary" in help_text


def test_state_dir_is_honoured_under_paper_too(tmp_path: Path) -> None:
    """A flag whose entire purpose is isolation must not be silently discarded by one of its modes.

    `--paper --state-dir X` wrote to `.starquant/paper` regardless of X, because the paper branch applied
    `with_name("paper")` to whatever the profile said - which is right for the DEFAULT (it makes the
    paper directory a sibling of the live one) and wrong the moment somebody names a directory.  Two
    paper canaries would have shared one `state.json` and neither would have said so.
    """
    from starquant_cli.live_cmd import _paper_state_dir

    profile = {"paths": {"state_dir": ".starquant/live"}}
    assert _paper_state_dir(profile, "") == Path(".starquant/paper")
    assert _paper_state_dir(profile, str(tmp_path / "shadow")) == tmp_path / "shadow"


def test_a_shadow_does_not_re_rank_the_shared_universe() -> None:
    """The third isolation, and the one `--state-dir` cannot give.

    `universe.json` lives under the DATA root, which no state flag isolates, and every enabled
    strategy's cited evidence records the universe fingerprint it was produced under.  A shadow that
    re-ranks the pool therefore invalidates the ARMED loop's evidence, and the dataset gate refuses
    its next start - measured on 2026-09-08, when a shadow at 18:00Z moved the fingerprint
    d47dbc7c -> 788ade10 and an armed restart went from clean to blocked.

    This used to assert the literal text `if state_dir or registry_override:` was present, which is
    how it passed while a bare `--paper` re-ranked the shared pool at 18:00Z that same day: the
    string was there and the CONDITION was wrong.  A source assertion can only check that a rule is
    wired, never that it is right.  So the rule now lives in `trades_the_account`, its truth
    table is asserted per-flag beside the pin it protects
    (`tests/live/test_the_universe_is_pinned_by_the_registry.py`), and what is left here is the one
    thing that genuinely needs the source: that `live_run` asks it at all.
    """
    import inspect

    from starquant_cli.live_cmd import live_run, trades_the_account

    source = inspect.getsource(live_run.callback)
    assert "trades_the_account(" in source, "the rule exists but nothing asks it"
    assert "pool = None" in source, "a shadow must inherit the armed loop's universe, not re-rank it"
    assert trades_the_account(dry_run=False, paper=True, state_dir="", registry_override=None) is False


def test_a_shadow_does_not_write_the_shared_metrics_record() -> None:
    """The second shared record, found the same way and one day later.

    `MetricsStore.append` is read-modify-write through one `.parquet.tmp` per symbol, so two writers
    can publish a file one of them was still writing - and DL-Q6 says that store holds "the metrics
    the loop could read", meaning the ARMED loop.  A paper process adding rows makes M-011 compare
    the live decision against data no live decision was made on.
    """
    import asyncio

    from starquant_live.engine import LiveEngine

    engine = LiveEngine.__new__(LiveEngine)
    engine.metrics_store = object()  # present, so "no store wired" is not what answers
    engine.record_metrics = False

    out = asyncio.run(LiveEngine._snapshot_metrics(engine))
    assert out["stored"] == {}
    assert "the armed loop" in out["reason"], out["reason"]


def test_the_shared_records_are_written_by_the_account_process_and_only_it() -> None:
    """One predicate, both records: the pool and the metrics snapshot ask the same question."""
    from starquant_cli.live_cmd import trades_the_account

    live = {"dry_run": False, "paper": False, "state_dir": "", "registry_override": None}
    assert trades_the_account(**live) is True
    for flag in ("dry_run", "paper"):
        assert trades_the_account(**{**live, flag: True}) is False
    assert trades_the_account(**{**live, "state_dir": "/tmp/canary"}) is False
    assert trades_the_account(**{**live, "registry_override": "candidate.yaml"}) is False


def test_the_candidate_does_not_lie_about_what_it_is() -> None:
    """The identity in the candidate's own header is checked by something other than a sentence.

    `config/alpha_registry.candidate.yaml` opens by saying it is byte-different from the armed registry
    "by this comment block and NOTHING ELSE", because the canary's first job is a POSITIVE CONTROL and a
    control that has drifted is not one.  That claim was true on 2026-09-12 and false by 2026-09-15: the
    armed registry moved three times (most consequentially `081f57da`, which unpinned the universe) and
    the candidate did not, so a 90-cycle soak was quietly soaking an 18-symbol population the armed loop
    no longer traded, against a superseded evidence pointer.  Nothing said a word, because every other
    identity in this repository is checked by an instrument - the registry digest, the construction
    fingerprint, the evidence sha256 - and this one was checked by prose.

    Conditional on the claim rather than asserting it outright, which is the whole point.  The header's
    last line is "Replace this file with the first real promotion candidate when one exists", and a real
    candidate MUST differ semantically or it is not a candidate.  So the invariant is not "these files
    agree" - it is "this file does not lie about itself".  Whoever writes the first real candidate
    deletes the NOTHING ELSE sentence in the same edit, and this test relaxes on its own.
    """
    root = Path(__file__).resolve().parents[2]
    candidate = (root / "config" / "alpha_registry.candidate.yaml").read_text(encoding="utf-8")
    armed = (root / "config" / "alpha_registry.yaml").read_text(encoding="utf-8")

    def body(text: str) -> list[str]:
        return [line for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]

    claims_identity = any("NOTHING ELSE" in line for line in candidate.splitlines() if line.lstrip().startswith("#"))
    if not claims_identity:
        return  # a real promotion candidate; it is allowed - required, even - to differ.
    assert body(candidate) == body(armed), (
        "the candidate registry claims it differs from the armed one by comments alone, and it does not. "
        "Either regenerate it (`cat <header> config/alpha_registry.yaml > config/alpha_registry.candidate.yaml`) "
        "or, if this is a real promotion candidate now, delete the 'NOTHING ELSE' claim from its header."
    )
