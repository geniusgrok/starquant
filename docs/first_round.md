# BTC contract candidates — registered 2026-10-01

The owner authorized runnable first-round changes toward one BTC perpetual
project and one spot project. Use the frozen 2020-01-01 through 2026-09-20
account, CNY 10,000, causal next-minute fills and existing costs. This is
historical diagnosis on a selected sample, not a new out-of-sample result.

Exactly five configurations: current baseline; risk 0.024 (half of 0.048);
max_units 1 (no pyramid adds); both changes; baseline long-only. The last
configuration suppresses new short signals only, preserving long entry/exit
and stop mechanics. Do not refit channels or loosen the permanent drawdown lock.

Each configuration runs at base cost, extra stop slip 0.1%, 0.2%, and 0.5%,
and taker 0.05%. Retain daily equity, long/short counts, half-peak breaches and
lock duration. Attribute short usefulness through matched full-account
counterfactuals: the difference is marginal account contribution, not an
isolated short PnL or a guarantee of protection.

An eligible risk candidate must avoid half-peak breach and terminal lock in
every scenario and retain at least 80% of baseline base CAGR. Rank eligible
candidates by worst-scenario CAGR, then base final CNY. Otherwise retain the
baseline pending further evidence. Long-only is diagnostic, not automatically
promoted. Report original 150%/50% target separately. Validate inputs and
reproduce the published causal baseline before any recommendation. Deliver
the candidate code/configuration and a mechanical adoption/rejection record.

Execution selection is separate: compare account protection, unknown-response
recovery, partial fills and operation schedule before retiring a runtime.
Coinquant is an execution-base candidate; this experiment does not prove it
or Starquant native-ready. Migration changes must be remeasured.
