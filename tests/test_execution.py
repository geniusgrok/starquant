"""Fills, full-size protection, disconnect, and late fills. Live orders stay shut."""

from __future__ import annotations

from btc_perp.exchange import BinanceExchange, Protection, SimExchange
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


def _arm(ex: SimExchange, qty: float) -> None:
    side = 1 if qty > 0 else -1
    ex.position_qty = qty
    ex.protections = [
        Protection("stop", side, abs(qty), 90.0 if side > 0 else 110.0),
        Protection("take_profit", side, abs(qty), 900.0 if side > 0 else 40.0),
    ]


def test_a_long_can_be_closed_without_opening_the_other_side():
    ex = SimExchange()
    ex.position_qty = 0.010
    ex.protections = []
    session = Session(ex, ManualClock(), duration_s=5, poll_s=5)
    session._poll(lambda _view: Intent(-1, 0.050, 1.0, 2.0))
    assert session.halted
    assert ex.submits == 1
    assert ex.position_qty == 0.0
    assert ex.protections == []


def test_a_short_can_be_closed():
    ex = SimExchange()
    _arm(ex, -0.008)
    Session(ex, ManualClock(), duration_s=5, poll_s=5)._poll(lambda _view: Intent(1, 0.008, 1.0, 2.0))
    assert ex.submits == 1
    assert ex.position_qty == 0.0
    assert ex.protections == []


def test_a_partial_close_leaves_protection_on_the_remainder():
    ex = SimExchange()
    Session(ex, ManualClock(), duration_s=5, poll_s=5).run(_buy_once)
    Session(ex, ManualClock(), duration_s=5, poll_s=5)._poll(lambda _view: Intent(-1, 0.004, 80.0, 800.0))
    assert ex.position_qty == 0.006
    assert ex.protection_covers_position()
    kinds = {p.kind: p for p in ex.protections}
    assert kinds["stop"].qty == 0.006
    assert kinds["stop"].price == 80.0
    assert kinds["take_profit"].qty == 0.006
    assert kinds["take_profit"].price == 800.0


def test_a_halted_session_refreshes_protection_and_does_not_add():
    ex = SimExchange()
    ex.position_qty = 0.010
    ex.protections = []
    Session(ex, ManualClock(), duration_s=5, poll_s=5)._poll(lambda _view: Intent(1, 0.005, 70.0, 700.0))
    assert ex.submits == 0
    assert ex.position_qty == 0.010
    assert ex.protection_covers_position()
    assert ex.protections[0].price == 70.0


def test_a_zero_qty_intent_amends_protection_without_another_fill():
    ex = SimExchange()
    Session(ex, ManualClock(), duration_s=5, poll_s=5).run(_buy_once)
    Session(ex, ManualClock(), duration_s=5, poll_s=5)._poll(lambda _view: Intent(1, 0.0, 88.0, 880.0))
    assert ex.submits == 1
    assert ex.position_qty == 0.010
    assert ex.protections[0].price == 88.0
    assert ex.protections[1].price == 880.0


def test_a_partial_close_does_not_open_the_other_side_in_the_same_poll():
    ex = SimExchange(partial_ratio=0.5, defer_remainder=True)
    _arm(ex, 0.010)

    def decide(_view):
        return (Intent(0, 0.010, 1.0, 2.0), Intent(-1, 0.008, 110.0, 40.0))

    Session(ex, ManualClock(), duration_s=5, poll_s=5)._poll(decide)
    assert ex.submits == 1
    assert ex.position_qty == 0.005
    assert ex.late
    assert ex.protection_covers_position() is False
    Session(ex, ManualClock(), duration_s=5, poll_s=5)._poll(lambda _view: None)
    assert ex.submits == 1
    assert ex.position_qty == 0.0
    assert ex.late == []
    assert ex.protection_covers_position()


def test_one_poll_can_close_and_then_open_the_other_side():
    ex = SimExchange()
    _arm(ex, 0.010)

    def decide(_view):
        return (Intent(0, 0.010, 1.0, 2.0), Intent(-1, 0.008, 110.0, 40.0))

    Session(ex, ManualClock(), duration_s=5, poll_s=5)._poll(decide)
    assert ex.submits == 2
    assert ex.position_qty == -0.008
    assert ex.protection_covers_position()
    assert {p.qty for p in ex.protections} == {0.008}


def test_the_default_entry_refuses_and_does_not_run_a_session(capsys):
    import sys

    from btc_perp.__main__ import main

    argv = sys.argv
    sys.argv = ["btc_perp"]
    try:
        main()
    finally:
        sys.argv = argv
    out = capsys.readouterr().out
    assert "禁止实盘" in out
    assert "不会下单" in out


def test_binance_adapter_refuses_orders():
    venue = BinanceExchange()
    assert venue.allowed() is False
    try:
        venue.submit_market(1, 0.01, 1.0, 2.0)
    except RuntimeError as exc:
        assert "禁止实盘" in str(exc)
    else:
        raise AssertionError("expected a refusal")
