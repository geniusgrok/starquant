# BTCUSDT account

One Binance USD-M BTCUSDT account. Isolated, one-way, leverage fixed at 20x.
Starting capital 10,000 CNY, no deposits. The model may be long or short.
A person starts a session (default 5 minutes). The session re-reads the market
and the account every 5 seconds, then exits. After a fill, the exchange holds a
stop and a take-profit for the filled quantity, including a partial fill, and
those orders stay up after the process exits. If funds, orders, or protection
are unclear, the session does not open new risk.

The full-sample replay is `python -m btc_perp --measure`. It walks
2020-01-01 through 2026-09-20 (the end date is exclusive) on the 1-minute tape,
with taker fees, slippage, bar-range impact, funding, liquidation capped at
isolated margin, and CNY/USD conversion. Live orders stay off
(`config/btc_account.yaml`) until that replay and the execution checks both pass.
There is no API key in this tree, and the Binance adapter refuses to send orders.

The older StarQuant packages are still in the tree. This account is the system
the measurement refers to.

# StarQuant — Alpha-First

A quantitative trading system for crypto perpetual futures on **Binance USDⓈ-M**,
currently at the **demo/testnet** stage. Research and signals run on mainnet
public data only; execution runs against the demo venue. The system's entire
output is one thing: **a set of target weights recomputed at every closed bar**,
plus a body of evidence that can explain itself.

## Architecture

Seven packages and one architectural rule — the dependency direction.
90% of the effort goes into alpha (strategies and factors).

```
mainnet public data ──► starquant_data ──► starquant_alpha
                                              (features → signals → ensemble →
                                               books → portfolio → overlays)
                                                      │
                                                      ▼ target weights
demo venue (Binance USDⓈ-M) ◄── starquant_exchange ◄── starquant_live
(scheduler → throttle → exits → guards → rebalancer → margin →
 execution → reconciler → reports)
```

| Package | Responsibility |
| --- | --- |
| `starquant_alpha` | Features → signals → ensemble → portfolio → backtest/validation. Pure functions over numpy/pandas only. |
| `starquant_data` | Official monthly-archive download and validation, REST gap repair, parquet storage, universe ranking with hysteresis, point-in-time pool membership, live closed bars. No interpolation, no forward fill. |
| `starquant_exchange` | Binance USDⓈ-M REST adapter with a host allowlist and a kill-switch. |
| `starquant_governance` | Evidence → verdict → promotion: pre-registration, a trials ledger, family gates, transactional (rollback-able) registry writes. |
| `starquant_live` | The bar-driven live loop: idempotent rebalance, reconciliation, attribution, daily report. |
| `starquant_shared` | Value types (Side, InstrumentRules, Position, OrderRequest) and YAML/env config loading. |
| `starquant_cli` | `starquant data \| research \| governance \| live \| report`. |

- Architecture detail: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
- Operating manual: [`docs/RUNBOOK.md`](docs/RUNBOOK.md)
- Glossary: [`docs/GLOSSARY.md`](docs/GLOSSARY.md)
- **Security: [`SECURITY.md`](SECURITY.md)** — red lines for a public repository, what each of the four interception layers covers, and the response order after a leak.

## What Actually Trades

The live configuration is deliberately small:

- **Main book — `tsmom`** (weekly-scale time-series momentum). Horizons
  168/336/720 h, validated 2026-09-03 on 15 symbols, 2021-07 → 2026-09:
  walk-forward OOS Sharpe 1.38, CPCV q05 1.20, DSR p 0.045, PBO 0.04,
  costs ×2 Sharpe 1.29. The legacy 5/20/50-hour horizons **failed** validation
  and are gone.
- **Probe book — `flow` (short-only)**, a sleeve running at 1/3 of the risk
  budget next to the main book. Its own standalone verdict is FAIL
  (DSR p 0.81 at 48 charged trials); it runs as a probe precisely because the
  pre-registered book-level rule (total OOS Sharpe 1.53 → 1.68) says so, and it
  is one ruling away from being retired.
- Six further signals (`xsmom`, `carry`, `meanrev`, `breakout`, `residual`,
  `chanlun`) exist in `starquant_alpha/signals/` and are **disabled**: each one
  either failed validation or never earned the evidence to run. They are kept
  as negative results.

Risk posture: annualised portfolio vol target 0.60, max leverage 5, orders
capped at 2% of hourly quote volume, universe = top-15 by 30-day volume with
hysteresis (enter ≤ 15, leave > 20).

## The Governance Layer (why this repo is shaped like this)

Every live change is a **transaction**: pre-registered, charged against a
trials ledger, gated by family-level multiple-testing budgets, and written
through an append-only log that can take itself back. Concepts in daily use:

- **Evidence before enablement** — a strategy runs only with a validation
  report whose sha256 is pinned in the registry; `starquant live run` verifies
  this at startup.
- **KILL-*** — falsified assumptions get an ID, a reason, and a reopen
  condition. Sixteen KILLs are currently standing; they are the majority of
  what has been learned here.
- **51 strategies tried, 2 survived** — the ledger records every trial, so the
  survivors' statistics are read against the real number of attempts
  (DSR/PBO), not the reported ones.

## What This Is Good At

- **Discipline by construction.** You cannot enable a strategy by editing a
  YAML file and hoping: the startup gates read the evidence digest, the trials
  ledger, and the family budgets, and refuse to start otherwise.
- **Honest backtests.** Point-in-time universe membership, no survivorship
  bias, no interpolated gaps, costs charged, multiple-testing corrections
  (walk-forward, CPCV, DSR, PBO) wired into the verdict path rather than
  bolted on.
- **Operable single-person deployment.** launchd units, a single-instance lock
  per account, idempotent rebalancing, reconciliation and attribution per
  cycle, a daily report, and a plain-text research log that is the actual
  source of truth.
- **Four quality gates** on every push: `ruff format`, `ruff check`, `mypy`,
  `pytest -m "not network"` (CI pins everything from `requirements.lock`),
  plus gitleaks hooks.

## What This Is Not Good At / Known Limitations

- **Not tested against real capital.** Everything runs on demo/testnet; the
  cost model is a flat 7 bps which is a fair approximation at demo notionals
  and probably is not at real size.
- **Single venue, single account, one person.** No multi-exchange routing, no
  shared-state concurrency, no team workflow. The governance process is built
  for one operator making sequential rulings.
- **Small alpha surface.** Two live sleeves (one main, one probe). The 49
  other candidates are negative results. The edge, where it exists, is
  weekly-scale momentum — slow signals, low turnover, no latency game.
- **Chinese-annotated research record.** The code comments and the research
  log (`docs/RESEARCH_LOG.md`, ~17k lines) are largely in Chinese; this README
  and the license are English. Translating the full research record is
  deliberately out of scope for now.
- **No live funding-rate path for modifiers.** The funding-crowding modifier
  saga (enabled → killed → re-examined) is documented precisely because the
  live panel lacked funding history; the same class of mismatch can recur
  wherever evidence is produced on data the live path does not feed itself.

## Getting Started

```bash
# 1. hooks first (not optional for a public repo)
brew install gitleaks && bash deploy/install-hooks.sh

# 2. environment + full test suite
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]" && pytest -q
```

## License

Proprietary — all rights reserved. Full terms in [`LICENSE`](LICENSE):
**public visibility does not grant a license**; the repository is publicly
readable on GitHub only for the author's own reference and collaboration.

Exception: `vendor/backtest-guard/` is a merged copy of two third-party MIT
projects (backtest engineering review + strategy-logic adversarial review). It
keeps the original MIT license inside that directory and is not covered by
the paragraph above — `LICENSE` spells this out separately. It is the
yardstick used when this repository is reviewed.
