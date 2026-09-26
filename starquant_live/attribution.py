"""Attribute realised venue income to strategies via the previous cycle's contributions; flag external cash flows."""

from __future__ import annotations

from collections.abc import Collection, Mapping
from typing import Any

# DL-X1 / T-X1-3: INSURANCE_CLEAR is the liquidation clearance fee.  It was not in this tuple, so
# `summarize_income` skipped it - the one income row that exists ONLY after the event this whole item
# is built to observe would have been the one row attribution never saw.  It is a trading cost, so it
# belongs here and not in EXTERNAL_FLOW_TYPES: treating it as a cash flow would re-base the day's
# equity and hide the loss instead of booking it (E-044's path, in reverse).
INCOME_TYPES = ("REALIZED_PNL", "COMMISSION", "FUNDING_FEE", "INSURANCE_CLEAR")
# Money that arrives or leaves without a trade: deposits/withdrawals, a demo-account reset (E-044 showed up as
# two TRANSFER rows and vanished positions), collateral swaps.  They make equity non-comparable across cycles.
EXTERNAL_FLOW_TYPES = frozenset(
    {
        "TRANSFER",
        "INTERNAL_TRANSFER",
        "WELCOME_BONUS",
        "CROSS_COLLATERAL_TRANSFER",
        "COIN_SWAP_DEPOSIT",
        "COIN_SWAP_WITHDRAW",
        "AUTO_EXCHANGE",
    }
)


def summarize_income(rows: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    """{symbol: {REALIZED_PNL: x, COMMISSION: y, FUNDING_FEE: z, total: t}}"""
    out: dict[str, dict[str, float]] = {}
    for row in rows:
        kind = str(row.get("incomeType", ""))
        if kind not in INCOME_TYPES:
            continue
        symbol = str(row.get("symbol", "") or "ACCOUNT")
        bucket = out.setdefault(symbol, dict.fromkeys(INCOME_TYPES, 0.0) | {"total": 0.0})
        try:
            amount = float(row.get("income", 0.0))
        except (TypeError, ValueError):
            continue
        bucket[kind] += amount
        bucket["total"] += amount
    return out


def external_flows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Sum of non-trading cash flows in ``rows``: ``{"total", "rows", "by_type"}`` (zero when there are none)."""
    total = 0.0
    count = 0
    by_type: dict[str, float] = {}
    for row in rows:
        kind = str(row.get("incomeType", ""))
        if kind not in EXTERNAL_FLOW_TYPES:
            continue
        try:
            amount = float(row.get("income", 0.0))
        except (TypeError, ValueError):
            continue
        total += amount
        count += 1
        by_type[kind] = by_type.get(kind, 0.0) + amount
    return {"total": total, "rows": count, "by_type": by_type}


# D-044: how small the net exposure may get, as a fraction of the gross, before a symbol stops being
# attributable at all.  E-050's explosion (+50x / -49x) is the net/gross ratio approaching zero; this
# bounds any single share at 1/MIN_NET_SHARE = 10x instead of letting it run.  0.10 is a floor on the
# arithmetic, not a tuned number - the live book's three overlapping symbols sit at 0.86-0.87.
MIN_NET_SHARE = 0.10
# The splitting rule this module currently applies, carried on every row it writes.  `attribution.jsonl`
# holds 55 rows produced under the magnitude rule and they stay as they are - a ledger that rewrites its
# own history is not a record - so the two series are told apart by the presence of this key.
ATTRIBUTION_BASIS = "net_exposure"


def strategy_shares(
    contributions: Mapping[str, Mapping[str, float]], strategy_weights: Mapping[str, float], symbol: str
) -> dict[str, float]:
    """Share of a symbol's income owned by each strategy: w_k T_k / sum_j w_j T_j.  Signed (D-044).

    The denominator is the NET exposure and the numerator keeps its sign, so a strategy that is short
    a symbol the book made money on is charged a negative share.  The shares still sum to 1, so
    ``sum_k share_k * income`` is the income; what changes is that a share may be negative or above 1.

    What this replaces and why.  E-050 hit a signed denominator going to zero and fixed it by taking
    magnitudes - which bounds every share to [0, 1] and, in doing so, makes each strategy's attributed
    P&L carry the sign of the SYMBOL's P&L rather than the sign of its own exposure.  Inside one
    symbol every strategy is then paid or charged together, whatever side it is on.  That is not a
    corner case here: measured 2026-09-17 on the running loop, flow and tsmom overlapped on three
    symbols (ENA, LINK, TRUMP) and disagreed on all three - flow short about -0.07 of equity against
    tsmom long 1.0 - so on 100 USDT of income the magnitude split paid flow about +6.5 where its own
    exposure earns about -7.4.  The registry's "91% of its positions stack on tsmom's shorts" is a
    backtest-period statistic and was 0% agreement on the day this was measured.

    It matters because of what reads the number.  `starquant_live.probe` sums `by_strategy` over 30 days
    and closes a probe book at -2% of equity; that stop is the ONLY automatic control on the flow
    sleeve, which runs against a book-level REJECT by the operator's D-029 exception.  A sign error
    in the sleeve's own P&L is a sign error in its brake.

    E-050's failure is answered by refusing rather than by rewriting: when the legs cancel to within
    ``MIN_NET_SHARE`` of their gross, the symbol has no attributable owner and this returns ``{}``,
    which ``attribute`` already books as ``unattributed``.  An un-owned bar is a true statement; a
    bounded-but-wrong-signed one is not.
    """
    signed = {
        k: float(strategy_weights.get(k, 1.0)) * float(contrib.get(symbol, 0.0)) for k, contrib in contributions.items()
    }
    gross = sum(abs(value) for value in signed.values())
    net = sum(signed.values())
    if gross < 1e-12 or abs(net) < MIN_NET_SHARE * gross:
        return {}
    return {k: value / net for k, value in signed.items() if abs(value) > 1e-12}


def split_by_origin(
    income_rows: list[dict[str, Any]], own_trade_ids: Collection[str]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(rows from fills the loop placed, rows from fills it did not) — D-032.

    Only a row that names a ``tradeId`` can be classified.  FUNDING_FEE carries none, and funding accrues
    on a position regardless of who opened it, so those rows stay with the book: this splits *who traded*,
    not *who is exposed*.

    The case this exists for: on 2026-09-04 the operator flattened the whole book by hand and its +26.30
    realised P&L was attributed to tsmom.  That is right in economic terms - tsmom chose and held those
    positions - but it compressed a whole holding period's unrealised P&L into one bar, and M-010 reads a
    per-bar income series, so mean and variance both move.  Splitting keeps the operator's P&L in the
    ledger (it is real money) while keeping it out of the series that judges the strategy.
    """
    own: list[dict[str, Any]] = []
    foreign: list[dict[str, Any]] = []
    known = {str(trade_id) for trade_id in own_trade_ids}
    for row in income_rows:
        trade_id = str(row.get("tradeId") or "")
        (foreign if trade_id and trade_id not in known else own).append(row)
    return own, foreign


def attribute(
    income_rows: list[dict[str, Any]],
    contributions: Mapping[str, Mapping[str, float]],
    strategy_weights: Mapping[str, float],
    *,
    own_trade_ids: Collection[str] | None = None,
) -> dict[str, Any]:
    """``own_trade_ids``: when given, fills outside it are reported under ``foreign`` and kept out of
    ``by_strategy`` / ``by_symbol`` / ``total`` (D-032).  ``None`` attributes everything, as before.

    ``basis`` (D-044) names the splitting rule, because the rows written before 2026-09-17 were
    produced by a different one and a reader joining the two series would be adding up two different
    quantities.  A row with no ``basis`` key is a magnitude row; the name travels with the number for
    the same reason ``SELECTION_GATE`` does one package over.
    """
    rows, foreign_rows = (income_rows, []) if own_trade_ids is None else split_by_origin(income_rows, own_trade_ids)
    by_symbol = summarize_income(rows)
    by_strategy: dict[str, float] = {}
    unattributed = 0.0
    cancelled: dict[str, float] = {}
    for symbol, bucket in by_symbol.items():
        shares = strategy_shares(contributions, strategy_weights, symbol)
        if not shares:
            unattributed += bucket["total"]
            # Two ways to have no owner, kept apart.  Nobody held it (a foreign symbol, or a bar with
            # no contributions at all) is an absence; the legs cancelling is a symbol this book DID
            # hold, from both sides, closely enough that no split of it is meaningful.  Only the
            # second is a fact about the strategies, and folding it into a single `unattributed`
            # would hide exactly the bars where the sleeves are fighting each other.
            if any(contrib.get(symbol) for contrib in contributions.values()):
                cancelled[symbol] = bucket["total"]
            continue
        for strategy, share in shares.items():
            by_strategy[strategy] = by_strategy.get(strategy, 0.0) + share * bucket["total"]
    foreign_by_symbol = summarize_income(foreign_rows)
    return {
        "basis": ATTRIBUTION_BASIS,
        "by_symbol": by_symbol,
        "by_strategy": by_strategy,
        "unattributed": unattributed,
        "cancelled": cancelled,
        "total": sum(bucket["total"] for bucket in by_symbol.values()),
        "external_flows": external_flows(income_rows),
        "foreign": {
            "by_symbol": foreign_by_symbol,
            "total": sum(bucket["total"] for bucket in foreign_by_symbol.values()),
            "rows": len(foreign_rows),
            "reconciled": own_trade_ids is not None,
        },
    }
