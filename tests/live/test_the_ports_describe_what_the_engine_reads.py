"""A protocol that omits what the caller actually reads has stopped describing the contract.

`ports.py` says that in its own words, about `SignalModel`, after mypy saw one of four accesses and
said nothing about the other three.  The `Venue` and `MarketData` ports had the same defect and it was
worse in both directions at once: seven members the engine reads with `getattr` appeared nowhere in
the file, and two that DID appear - `venue_time_ms`, `user_trades` - were declared required while
every call site probed them and fell back.

`getattr(obj, "name", None)` is invisible to a type checker by construction, so the guard cannot be
mypy.  It is this file: the set of names the engine probes must equal the set the ports declare.  Add
a probe without declaring it and the first test fails; declare a member nobody probes and the second
does.
"""

from __future__ import annotations

import ast
from pathlib import Path

from starquant_live import ports

ENGINE = Path(ports.__file__).with_name("engine.py")

#: `self.venue` / `self.market`, and the protocol that is allowed to declare what is read off each.
PORTS = {
    "venue": (ports.Venue, ports.VenueProbes),
    "market": (ports.MarketData, ports.MarketDataProbes),
}

#: Probed AND required, on purpose: the probe exists to REFUSE, not to fall back.
#:
#: `startup` asks whether the feed can supply `funding_history` only so that it can decline to start
#: when an enabled signal declares `needs_funding` and the port cannot answer - D-023, closing KILL-027
#: structurally.  A member whose absence stops the loop is required; what makes the other nine optional
#: is that their absence is survivable and silently survived.  Any addition here has to name the line
#: that raises.
REFUSES_RATHER_THAN_FALLS_BACK = {
    ("market", "funding_history"),  # engine.startup: "refusing to trade an unvalidated configuration"
}


def _probed(attribute: str) -> set[str]:
    """Every `getattr(self.<attribute>, "name", ...)` in the engine."""
    tree = ast.parse(ENGINE.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "getattr"):
            continue
        target, name = node.args[0], node.args[1]
        if not (isinstance(target, ast.Attribute) and target.attr == attribute):
            continue
        if isinstance(target.value, ast.Name) and target.value.id == "self" and isinstance(name, ast.Constant):
            found.add(str(name.value))
    return found


def _declared(*protocols: type) -> set[str]:
    return {name for protocol in protocols for name in protocol.__protocol_attrs__}  # type: ignore[attr-defined]


def test_every_probed_member_is_declared_by_a_port() -> None:
    """The direction that bites: the engine depending on something no adapter was ever told about."""
    for attribute, protocols in PORTS.items():
        undeclared = _probed(attribute) - _declared(*protocols)
        assert not undeclared, (
            f"engine.py probes self.{attribute} for {sorted(undeclared)}, which no port declares. "
            "Add it to the Probes protocol in ports.py, or stop reading it."
        )


def test_the_probed_members_are_on_the_probes_protocol_not_the_required_one() -> None:
    """The other direction, and the contradiction this file was written for.

    `venue_time_ms` and `user_trades` sat on `Venue` - required - while the engine probed them and fell
    back to the host clock (D-030's exact failure) or to full attribution (D-032's).  A member that
    every call site treats as optional is optional; saying otherwise in the port means the port is not
    what anyone reads.
    """
    for attribute, (required, optional) in PORTS.items():
        exempt = {name for port, name in REFUSES_RATHER_THAN_FALLS_BACK if port == attribute}
        misfiled = (_probed(attribute) & _declared(required)) - exempt
        assert not misfiled, (
            f"{sorted(misfiled)} are declared required on {required.__name__} but probed with getattr. "
            f"Move them to {optional.__name__}, stop probing, or - if the probe refuses rather than "
            "falls back - add it to REFUSES_RATHER_THAN_FALLS_BACK with the line that raises."
        )


def test_nothing_is_declared_on_a_probes_protocol_that_nobody_probes() -> None:
    """A Probes protocol is a list of what the engine reads; a stale entry makes it fiction again."""
    for attribute, (_required, optional) in PORTS.items():
        unread = _declared(optional) - _probed(attribute)
        assert not unread, f"{optional.__name__} declares {sorted(unread)}, which engine.py never probes"


#: The one probed member that belongs to the OTHER adapter.  `mark` moves the paper venue's marks onto
#: the newest closed bar; a real venue's marks come from the exchange, so its absence there is the
#: adapters differing rather than the shipped one lagging.
PAPER_ONLY = {"mark"}


def test_the_real_venue_adapter_supplies_every_probe_that_is_not_paper_only() -> None:
    """Two adapters make the seam real, and this is the one that trades.

    The shipped adapter supplies every probed member, which is what makes their absence elsewhere a
    property of the OTHER adapter rather than of the contract.
    """
    from starquant_exchange.binance_usdm.venue import BinanceUsdmVenue

    for name in (_declared(ports.Venue) | _declared(ports.VenueProbes)) - PAPER_ONLY:
        assert hasattr(BinanceUsdmVenue, name), f"the shipped venue adapter is missing {name}"


def test_the_paper_venue_is_where_mark_lives() -> None:
    """And the other adapter holds up its end, so PAPER_ONLY stays a statement about two real things."""
    from starquant_live.paper import PaperVenue

    for name in PAPER_ONLY:
        assert hasattr(PaperVenue, name), f"the paper venue is missing {name}, so nothing supplies it"


def test_the_shared_fake_can_now_be_a_feed_with_a_clock_and_one_without() -> None:
    """The test cost the missing declaration was hiding.

    `FakeMarketData` had no `server_time_ms`, so every engine test built on it took `_clock_skew`'s
    all-None branch and D-025's skew/alignment/jump instrumentation was reachable only through one
    bespoke subclass in `test_round6b_funding_and_verify.py`.  Absence stays the default - flipping it
    would change what two hundred existing tests measure - but it is now a setting rather than a
    property of the fake, so a test can ask for either feed.
    """
    import pandas as pd

    from starquant_alpha.panel import Panel
    from tests.live.fakes import FakeMarketData

    index = pd.date_range("2026-01-01", periods=4, freq="1h", tz="UTC")
    frame = pd.DataFrame({"BTCUSDT": [1.0, 2.0, 3.0, 4.0]}, index=index)
    panel = Panel(open=frame, high=frame, low=frame, close=frame, volume=frame, interval="1h")

    absent = FakeMarketData(panel, cursor=2)
    assert getattr(absent, "server_time_ms", None) is None, "the default must still be a feed with no clock"

    present = FakeMarketData(panel, cursor=2)
    present.server_skew_ms = 20_000
    probe = getattr(present, "server_time_ms", None)
    assert callable(probe), "configuring a skew must make the probe appear, the way a real feed has one"
