# Backtest: tsmom

## Range

| key | value |
| --- | --- |
| start | 2021-06-05 05:00:00+00:00 |
| end | 2026-09-03 04:00:00+00:00 |
| bars | 45984 |

## Params

| key | value |
| --- | --- |
| horizons | 5, 20, 50 |
| horizon_weights | 0.2000, 0.3000, 0.5000 |
| return_weight | 0.4000 |
| slope_weight | 0.2500 |
| persistence_weight | 0.1000 |
| return_scale | 0.2000 |
| slope_scale | 0.0100 |
| entry_threshold | 0.2000 |
| vol_window | 200 |

## Summary

| key | value |
| --- | --- |
| bars | 45984 |
| gross_return | 0.8453 |
| net_return | -0.1904 |
| annualized_sharpe | -0.2053 |
| annualized_sharpe_gross | 0.8782 |
| max_drawdown | -0.2763 |
| average_absolute_exposure | 0.3697 |
| turnover_units | 1150.4 |
| nonzero_target_bars | 45984 |
| hit_rate | 0.4910 |
| cost_share_of_gross | 1.2339 |

## Benchmark (equal-weight long, zero cost)

| key | value |
| --- | --- |
| gross_return | 1.2358 |
| sharpe | 0.5612 |

## Yearly

| key | value |
| --- | --- |
| 2021 | ret=-0.055 sharpe=-0.59 |
| 2022 | ret=-0.089 sharpe=-0.56 |
| 2023 | ret=0.074 sharpe=0.57 |
| 2024 | ret=0.029 sharpe=0.27 |
| 2025 | ret=-0.179 sharpe=-1.29 |
| 2026 | ret=0.036 sharpe=0.45 |

## Per symbol

| key | value |
| --- | --- |
| BTCUSDT | net=-0.195 sharpe=-0.78 turnover=282.6 |
| ETHUSDT | net=-0.089 sharpe=-0.28 turnover=293.7 |
| BNBUSDT | net=-0.150 sharpe=-0.53 turnover=286.0 |
| SOLUSDT | net=0.324 sharpe=0.81 turnover=288.1 |
