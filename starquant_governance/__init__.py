"""StarQuant governance: the machine that decides whether a strategy may place orders.

The evaluation pipeline already existed - walk-forward, CPCV, the trials ledger, the D-020 verdict,
the D-028 selection gate.  What was missing was a *subject* for the sentence "and therefore it goes
live": every promotion so far was a person reading a report and editing `config/alpha_registry.yaml`.
This package is that subject.  The operator's ruling (2026-09-08) is that no human acts at runtime,
because people make mistakes; the rules are written down and executed strictly, and the protection
against a rule being wrong is exposure control (R3), transaction rollback (R6) and the P&L stop -
not a confirmation click.

Phase 0 is deliberately inert: `policy` and `lifecycle` are pure, and `replay` only reads.  Nothing
here writes a registry, a ledger row or a state file yet; that arrives with Phase 1-2 once the rules
have been replayed against the record they claim to reproduce.
"""

from __future__ import annotations

from starquant_governance.policy import POLICY_VERSION, Policy, policy_digest

__all__ = ["POLICY_VERSION", "Policy", "policy_digest"]
