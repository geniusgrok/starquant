"""Fills, full-size protection, disconnect, and late fills. Live orders stay shut."""

from __future__ import annotations

from btc_perp.exchange import BinanceExchange, SimExchange
from btc_perp.session import Intent, ManualClock, Session


def _buy_once(view):
    if view.position_qty == 0 and view.known:
        return Intent(1, 0.010, 90.0, 900.0)
    return None


def test_full_fill_places_stop_and_take_profit_for_the_filled_qty():
    ex = SimExchange()
    view = Session(ex, ManualClock(), duration_s=15, poll_s=5).run(_buy_once)
    assert ex.submits == 1
    assert view.position_qty == 0.010
    kinds = {p.kind: p for p in view.protections}
    assert kinds["stop"].qty == 0.010
    assert kinds["take_profit"].qty == 0.010
    assert view.free_qty_unprotected == 0.0


def test_partial_fill_protects_only_the_filled_qty_until_the_rest_arrives():
    ex = SimExchange(partial_ratio=0.4, defer_remainder=True)
    clock = ManualClock()
    session = Session(ex, clock, duration_s=10, poll_s=5)
    # First poll fills 0.004 and parks 0.006. Protection matches the fill before the late print.
    session._poll(_buy_once)
    assert ex.position_qty == 0.004
    assert ex.protections[0].qty == 0.004
    assert ex.late
    session._poll(_buy_once)
    assert ex.position_qty == 0.010
    assert {p.qty for p in ex.protections} == {0.010}
    assert ex.protection_covers_position()


def test_disconnect_blocks_new_risk_and_protection_survives_session_exit():
    ex = SimExchange()
    clock = ManualClock()
    session = Session(ex, clock, duration_s=25, poll_s=5)
    session._poll(_buy_once)
    assert ex.position_qty == 0.010
    ex.disconnect()
    before = ex.submits
    session._poll(_buy_once)
    assert session.halted
    assert ex.submits == before
    view = session.run(lambda _view: Intent(-1, 0.020, 1.0, 1.0))
    assert ex.submits == before
    assert view.position_qty == 0.010
    assert len(view.protections) == 2


def test_late_fill_after_the_session_still_receives_protection():
    ex = SimExchange(partial_ratio=0.5, defer_remainder=True)
    Session(ex, ManualClock(), duration_s=5, poll_s=5).run(_buy_once)
    # The poll fills half. The remainder is still on the venue when the process has returned.
    assert ex.position_qty == 0.005
    assert ex.late
    ex.deliver_late_fills()
    assert ex.position_qty == 0.010
    assert ex.protection_covers_position()
    assert {p.qty for p in ex.protections} == {0.010}


def test_unclear_protection_does_not_open_a_new_position():
    ex = SimExchange()
    ex.position_qty = 0.002
    ex.protections = []
    session = Session(ex, ManualClock(), duration_s=10, poll_s=5)
    session._poll(_buy_once)
    assert session.halted
    assert ex.submits == 0
    assert ex.position_qty == 0.002


def test_binance_adapter_refuses_orders():
    venue = BinanceExchange(False, True, True, "k")
    assert venue.allowed() is False
    try:
        venue.submit_market(1, 0.01, 1.0, 2.0)
    except RuntimeError as exc:
        assert "live orders are disabled" in str(exc)
    else:
        raise AssertionError("expected a refusal")
