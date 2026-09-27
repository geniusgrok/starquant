"""A corrupt `state.json` must stop `live run` and must not stop the way out of a position.

`StateStore.load` refuses a state file it cannot parse rather than returning a fresh `LiveState`
(2026-09-13).  That refusal is right for the loop: the file is the only copy of the income watermark,
the equity high-water mark, the exit anchors and the D-005 hold seeds, and silently zeroing it puts a
hole in M-010 that nothing can detect afterwards.

It is wrong for the two readers.  `starquant live flatten` needs the venue's positions and nothing else,
and the file is most likely to be half-written exactly when the process died mid-cycle - which is when
someone reaches for flatten.  `starquant report daily` is the unattended monitor: it is how a broken file
gets noticed at all, so it has to render and say so rather than die on the first line.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from starquant_live.reports import daily_alerts, readable_state
from starquant_live.state import LiveState, StateStore, StateUnreadable


def _corrupt(tmp_path: Path) -> StateStore:
    store = StateStore(tmp_path)
    store.state_path.write_text('{"last_bar_ms": 1234', encoding="utf-8")  # truncated mid-write
    return store


def test_an_absent_file_is_a_first_start_and_a_truncated_one_is_not(tmp_path: Path) -> None:
    assert StateStore(tmp_path / "fresh").load() == LiveState()
    with pytest.raises(StateUnreadable):
        _corrupt(tmp_path).load()


def test_the_refusal_names_the_file_and_a_way_out(tmp_path: Path) -> None:
    with pytest.raises(StateUnreadable) as caught:
        _corrupt(tmp_path).load()
    message = str(caught.value)
    assert "state.json" in message
    assert "state.json.bad" in message, "the refusal has to tell the operator what to do next"


def test_the_report_reader_degrades_to_an_empty_state_and_says_why(tmp_path: Path) -> None:
    state, reason = readable_state(_corrupt(tmp_path))
    assert state == LiveState()
    assert reason, "an empty state with no reason is the silent zeroing this exists to prevent"
    clean, no_reason = readable_state(StateStore(tmp_path / "fresh"))
    assert clean == LiveState() and no_reason == ""


def test_an_unreadable_state_file_pages_rather_than_passing_quietly() -> None:
    loud, _notices = daily_alerts({"state_file": {"readable": False, "reason": "truncated"}})
    assert any("state.json" in line for line in loud)
    quiet, _ = daily_alerts({"state_file": {"readable": True, "reason": ""}})
    assert not any("state.json" in line for line in quiet)
    # A payload written before the field existed must not start paging.
    older, _ = daily_alerts({})
    assert not any("state.json" in line for line in older)


def test_the_engine_accepts_an_explicit_state_so_flatten_can_run_without_the_file(tmp_path: Path) -> None:
    """The seam `starquant live flatten` uses.  Asserted on the signature, not by building an engine:
    a `LiveEngine` needs a venue, a market and a model, and none of them is what this is about."""
    import inspect

    from starquant_live.engine import LiveEngine

    parameter = inspect.signature(LiveEngine.__init__).parameters["state"]
    assert parameter.default is None, "the default has to keep `live run` on the refusing path"


def test_flatten_catches_the_refusal_and_run_does_not() -> None:
    source = Path("starquant_cli/live_cmd.py").read_text(encoding="utf-8")
    flatten = source.split("def live_flatten(")[1].split("\n@live.command")[0]
    assert "StateUnreadable" in flatten, "flatten must not be blocked by a corrupt state file"
    run = source.split("def live_run(")[1].split("\n@live.command")[0]
    assert "StateUnreadable" not in run, "live run must inherit the refusal"
