# BTC perpetual comparison and execution evidence — 2026-10-01

The fixed candidates are Coinquant default, Starquant default and Starquant
half-risk (risk=0.024). No new channel/risk/pyramid search. Preserve the existing
150% CAGR / MDD <50% target, CNY 10,000, no additions and frozen window.

Reference operation: Coinquant's frozen 795 finite manually started sessions.
Continuous Starquant results remain separately labeled. Ranking is blocked
until schedule, mark/fills, fees/slippage, latency, funding, FX/conversion,
stops and missing-data conventions are genuinely aligned. The comparison
command must expose unresolved dimensions; selecting a common display schema
does not make the accounts comparable.

Reuse existing offline runner tests for partial fill, lost ACK, restart,
protection replacement and disconnect. Save source identity and actual case
results, separately from native Demo/Live status. A winner requires execution
proof and acceptable maintenance burden before strategy migration and archive
of the other runtime. No new runtime or trading account is created here.

## Recorded second-round outcome

`reports/local-execution-20261001.json` records seven case groups actually
passing (parameterized replacement-failure inputs retain their individual
pytest outcomes). Reproduce with:

```sh
python -m scripts.local_checks --out reports/local-execution-NEW.json
```

Coinquant's `evidence/second-round-20261001/comparison.json` records the original
artifact hashes and all nine comparison blockers. No candidate is selected.
Half-risk remains a useful fixed survival control without changing its failed
93.85% retention threshold or the original 150% goal. Production and economic
kernel code are unchanged; Demo/Live remain NO_GO.
