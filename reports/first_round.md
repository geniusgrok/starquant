# BTC risk, pyramid and short counterfactual — 2026-10-01

Protocol: `docs/first_round.md`, registered before measurement.
`btc_account_first_round.json` records the exact commit, full source/configuration/input
identities, all 25 matched scenarios, daily curves and the decision. No
production configuration or qualification gate changed.

Reproduce from the repository root:

```sh
python -m scripts.restore_btc
python -m btc_perp first-round
```

Restoration requires the three original SHA-256 identities; it also verifies
19 official premium-index archives. The restored causal base reproduces
CNY 1,839,663.45, 57 long and 35 short entries. Funding coverage remains
7,305 official, 56 premium proxies and one missing zero-filled slot.

| Configuration | Base CAGR | Base continuous MDD | CAGR with 10bp extra stop slip |
| --- | ---: | ---: | ---: |
| Baseline | 117.31% | 47.19% | 41.55% (locked) |
| Half risk | 57.97% | 33.65% | 56.60% |
| No pyramid adds | 19.43% | 39.66% | 19.17% |
| Half risk, no adds | 12.30% | 27.19% | 12.24% |
| Long-only | 27.31% | 51.79% | 26.65% (locked) |

The half-risk account survives all registered costs without a terminal lock
and has a worst-scenario CAGR of 49.03%. It fails the preregistered retention
floor of 93.85% (80% of the base CAGR). The other risk candidates also fail
the floor. **No candidate is promoted; retain the baseline as research.**
None meets the original 150% CAGR / less-than-50% MDD target. A more stable
half-risk candidate is available for further work, with its explicit return
tradeoff; it is not presented as meeting the original objective.

The long-only counterfactual ends at CNY 50,656 and breaches half peak. This
supports preserving shorts in the research route. Full-account counterfactual
differences include altered future trades, sizing and lock paths; they are not
isolated short PnL or proof of out-of-sample crash insurance.

The causal kernel is shared with the baseline. Long-only masks new short
entry channels and preserves long exits and stops. Existing ruff, mypy and
offline tests passed; the new restoration identity test passes separately.
The test run also remeasured the official same-close account with unchanged
economic values and refreshed its source/run metadata.

Eventual use remains one perpetual project and Spotquant. Preserve Starquant's
trend, shorts and pyramid research until an execution base is selected; these
results do not authorize combining two runtimes on one account. Native Demo
and small-live status remain NO_GO.
