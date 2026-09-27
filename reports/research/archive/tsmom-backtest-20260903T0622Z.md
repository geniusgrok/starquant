# Backtest: tsmom

## Range

| key | value |
| --- | --- |
| start | 2021-07-01 01:00:00+00:00 |
| end | 2026-09-03 04:00:00+00:00 |
| bars | 45364 |

## Params

| key | value |
| --- | --- |
| horizons | 168, 336, 720 |
| horizon_weights | 0.2000, 0.3000, 0.5000 |
| return_weight | 0.4000 |
| slope_weight | 0.2500 |
| persistence_weight | 0.1000 |
| return_scale | 0.2000 |
| slope_scale | 0.0100 |
| entry_threshold | 0.2000 |
| vol_window | 400 |

## Summary

| key | value |
| --- | --- |
| bars | 45364 |
| gross_return | 3.2744 |
| net_return | 2.3471 |
| annualized_sharpe | 1.5528 |
| annualized_sharpe_gross | 1.8513 |
| max_drawdown | -0.1313 |
| average_absolute_exposure | 0.4129 |
| turnover_units | 310.5 |
| nonzero_target_bars | 45364 |
| hit_rate | 0.5098 |
| cost_share_of_gross | 0.1612 |

## Benchmark (equal-weight long, zero cost)

| key | value |
| --- | --- |
| gross_return | 2.0607 |
| sharpe | 0.6633 |

## Yearly

| key | value |
| --- | --- |
| 2021 | ret=0.116 sharpe=1.50 |
| 2022 | ret=0.253 sharpe=1.52 |
| 2023 | ret=0.208 sharpe=1.25 |
| 2024 | ret=0.273 sharpe=1.59 |
| 2025 | ret=0.326 sharpe=1.88 |
| 2026 | ret=0.172 sharpe=1.56 |

## Per symbol

| key | value |
| --- | --- |
| BTCUSDT | net=0.201 sharpe=1.20 turnover=34.4 |
| ETHUSDT | net=0.129 sharpe=0.76 turnover=30.0 |
| SOLUSDT | net=0.160 sharpe=0.81 turnover=27.4 |
| XRPUSDT | net=0.052 sharpe=0.31 turnover=32.4 |
| ZECUSDT | net=0.173 sharpe=0.83 turnover=28.4 |
| HYPEUSDT | net=0.014 sharpe=0.19 turnover=6.7 |
| DOGEUSDT | net=0.090 sharpe=0.50 turnover=27.9 |
| TRUMPUSDT | net=-0.019 sharpe=-0.22 turnover=9.2 |
| BNBUSDT | net=0.028 sharpe=0.19 turnover=36.2 |
| ENAUSDT | net=0.027 sharpe=0.25 turnover=9.7 |
| 1000PEPEUSDT | net=0.100 sharpe=0.67 turnover=15.8 |
| PUMPUSDT | net=0.062 sharpe=0.61 turnover=5.1 |
| SUIUSDT | net=0.181 sharpe=1.16 turnover=16.6 |
| AKEUSDT | net=0.100 sharpe=0.92 turnover=2.8 |
| ADAUSDT | net=0.028 sharpe=0.18 turnover=27.8 |
