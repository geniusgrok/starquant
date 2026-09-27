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
| gross_return | 17.7617 |
| net_return | 11.7425 |
| annualized_sharpe | 1.5652 |
| annualized_sharpe_gross | 1.7783 |
| max_drawdown | -0.2342 |
| average_absolute_exposure | 0.8056 |
| turnover_units | 308.2 |
| nonzero_target_bars | 49014 |
| hit_rate | 0.5097 |
| cost_share_of_gross | 0.1200 |
| guards | replayed=yes; gross_capped_bars=0; daily_loss_pause_bars=33; bars=49014 |

## Benchmark (equal-weight long, zero cost)

| key | value |
| --- | --- |
| gross_return | 9.3582 |
| sharpe | 0.9240 |

## Yearly

| key | value |
| --- | --- |
| 2021 | ret=0.942 sharpe=2.35 |
| 2022 | ret=0.405 sharpe=1.22 |
| 2023 | ret=0.562 sharpe=1.58 |
| 2024 | ret=0.512 sharpe=1.43 |
| 2025 | ret=0.530 sharpe=1.46 |
| 2026 | ret=0.292 sharpe=1.33 |

## Per symbol

| key | value |
| --- | --- |
| BTCUSDT | net=0.393 sharpe=1.16 turnover=26.5 |
| ETHUSDT | net=0.214 sharpe=0.63 turnover=26.9 |
| SOLUSDT | net=0.426 sharpe=1.01 turnover=27.4 |
| XRPUSDT | net=0.108 sharpe=0.33 turnover=28.6 |
| ZECUSDT | net=0.388 sharpe=0.92 turnover=24.1 |
| HYPEUSDT | net=0.050 sharpe=0.34 turnover=6.0 |
| DOGEUSDT | net=0.334 sharpe=0.83 turnover=31.0 |
| TRUMPUSDT | net=-0.075 sharpe=-0.41 turnover=6.2 |
| BNBUSDT | net=0.485 sharpe=1.33 turnover=28.3 |
| ENAUSDT | net=0.051 sharpe=0.24 turnover=10.2 |
| 1000PEPEUSDT | net=0.184 sharpe=0.63 turnover=14.0 |
| SUIUSDT | net=0.310 sharpe=1.04 turnover=14.8 |
| AKEUSDT | net=0.157 sharpe=1.02 turnover=2.6 |
| ADAUSDT | net=0.102 sharpe=0.31 turnover=29.3 |
| LINKUSDT | net=0.025 sharpe=0.10 turnover=32.1 |
