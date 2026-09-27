"""Does a manual flatten still move R8's reading, now that the ruler carries unrealised P&L?

Before 2026-09-13T22:00Z the ladder read realised income only, so a flatten - which converts held
paper losses into booked ones - handed it a loss it had never seen.  Measured on the live record that
day: the 21:00Z flatten moved the reading from -0.924% to -1.754%, nearly doubling it.

The new ruler is `path + carried` where `path` carries realised income and `carried` is the unrealised
term, so realising a loss should move both by the same amount with opposite sign and leave the reading
where it was.  This builds the two worlds and asks `attributed_drawdown_state` itself rather than
trusting that algebra:

  held      the book carries an unrealised loss U and books nothing
  flattened the same book realises exactly U in the last bar and carries nothing

Same equity path, same base, same everything else.  If the ruler is realisation-invariant the two
readings are equal.
"""

from __future__ import annotations

import json

from starquant_live.risk_budget import RiskBudgetParams, attributed_drawdown_state

BAR = 3_600_000
START = 1_789_000_000_000
EQUITY = 10_000.0
U = -400.0  # the unrealised loss the book is holding when the operator flattens


def world(realise: bool) -> tuple[list[dict], list[dict]]:
    """(cycles, attribution) for a three-bar book that ends either holding U or having booked it."""
    cycles, attribution = [], []
    for i in range(3):
        last = i == 2
        cycles.append(
            {
                "at": f"2026-09-01T0{i}:00:00+00:00",
                "bar_open_ms": START + i * BAR,
                "equity": EQUITY,
                # the mark-to-market hole is there from bar 1 in both worlds; only bar 2 differs in
                # whether it has been booked
                "unrealized": 0.0 if i == 0 else (0.0 if (last and realise) else U),
            }
        )
        booked = U if (last and realise) else 0.0
        attribution.append({"bar_open_ms": START + i * BAR, "until_ms": START + (i + 1) * BAR, "total": booked})
    return cycles, attribution


def main() -> None:
    out = {}
    for label, realise in (("held", False), ("flattened", True)):
        cycles, attribution = world(realise)
        block = attributed_drawdown_state(cycles, attribution, RiskBudgetParams())
        out[label] = {
            "ruler": block["ruler"],
            "reading": round(float(block["value"]), 9),
            "path": round(float(block["path"]), 4),
            "attributed": round(float(block["attributed"]), 4),
            "marked_rows": block["marked_rows"],
        }
    same = out["held"]["reading"] == out["flattened"]["reading"]
    out["realisation_invariant"] = same
    print(json.dumps(out, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
