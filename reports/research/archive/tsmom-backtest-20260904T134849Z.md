# Backtest: tsmom

## Range

| key | value |
| --- | --- |
| start | 2021-01-31 01:00:00+00:00 |
| end | 2026-09-04 06:00:00+00:00 |
| bars | 49014 |

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
| crowding_window | 0 |
| crowding_cut | 0.7000 |
| crowding_penalty | 0.5000 |
| momentum_mode | fixed |
| conviction_mode | sign |

## Summary

| key | value |
| --- | --- |
| bars | 49014 |
| gross_return | 4.0944 |
| net_return | 3.0480 |
| annualized_sharpe | 1.5760 |
| annualized_sharpe_gross | 1.8211 |
| max_drawdown | -0.1360 |
| average_absolute_exposure | 0.4663 |
| turnover_units | 212.7 |
| nonzero_target_bars | 49014 |
| hit_rate | 0.5112 |
| cost_share_of_gross | 0.1347 |
| guards | replayed=yes; gross_capped_bars=0; daily_loss_pause_bars=0; bars=49014 |

## Benchmark (equal-weight long, zero cost)

| key | value |
| --- | --- |
| gross_return | 9.3582 |
| sharpe | 0.9240 |

## Yearly

| key | value |
| --- | --- |
| 2021 | ret=0.402 sharpe=2.32 |
| 2022 | ret=0.231 sharpe=1.35 |
| 2023 | ret=0.333 sharpe=1.79 |
| 2024 | ret=0.241 sharpe=1.36 |
| 2025 | ret=0.252 sharpe=1.42 |
| 2026 | ret=0.133 sharpe=1.15 |

## Per symbol

| key | value |
| --- | --- |
| BTCUSDT | net=0.262 sharpe=1.26 turnover=24.3 |
| ETHUSDT | net=0.103 sharpe=0.52 turnover=21.1 |
| SOLUSDT | net=0.169 sharpe=0.81 turnover=17.1 |
| XRPUSDT | net=0.040 sharpe=0.21 turnover=21.9 |
| ZECUSDT | net=0.202 sharpe=0.93 turnover=14.5 |
| HYPEUSDT | net=0.039 sharpe=0.45 turnover=3.4 |
| DOGEUSDT | net=0.126 sharpe=0.62 turnover=19.7 |
| TRUMPUSDT | net=-0.061 sharpe=-0.57 turnover=4.3 |
| BNBUSDT | net=0.216 sharpe=1.05 turnover=24.7 |
| ENAUSDT | net=0.022 sharpe=0.20 turnover=5.3 |
| 1000PEPEUSDT | net=0.103 sharpe=0.69 turnover=7.8 |
| SUIUSDT | net=0.152 sharpe=1.02 turnover=8.6 |
| AKEUSDT | net=0.084 sharpe=1.08 turnover=1.3 |
| ADAUSDT | net=0.074 sharpe=0.38 turnover=19.3 |
| LINKUSDT | net=0.025 sharpe=0.15 turnover=19.5 |
