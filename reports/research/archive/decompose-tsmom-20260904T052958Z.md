# Decomposition: tsmom

## Range

| key | value |
| --- | --- |
| start | 2021-01-31 01:00:00+00:00 |
| end | 2026-09-04 04:00:00+00:00 |
| bars | 49012 |
| oos_start | 2021-07-16 17:00:00+00:00 |

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

## Variants (same portfolio construction, different convictions)

- full: sharpe=1.72 oos=1.64 net=3.444 mdd=-0.121 turnover=226 exposure=0.457 corr_full=1.00 folds=[1.47, 0.78, 2.32, 1.05, 2.58]
- constant_long: sharpe=0.10 oos=-0.01 net=0.022 mdd=-0.334 turnover=19 exposure=0.225 corr_full=-0.10 folds=[-0.56, -0.05, 0.33, 0.71, -0.45]
- sign_only: sharpe=1.72 oos=1.64 net=3.444 mdd=-0.121 turnover=226 exposure=0.457 corr_full=1.00 folds=[1.47, 0.78, 2.32, 1.05, 2.58]
- long_only: sharpe=0.65 oos=0.56 net=0.631 mdd=-0.227 turnover=89 exposure=0.202 corr_full=0.17 folds=[0.04, 0.42, 0.88, 1.41, 0.04]
- short_only: sharpe=0.69 oos=0.83 net=0.685 mdd=-0.161 turnover=95 exposure=0.195 corr_full=0.38 folds=[1.15, 0.07, 0.86, 0.36, 1.69]
- equal_notional: sharpe=0.91 oos=0.84 net=7.592 mdd=-0.495 turnover=271 exposure=0.999 corr_full=0.83 folds=[0.92, -0.31, 1.08, 0.75, 1.62]

## Increments (Sharpe)

| key | value |
| --- | --- |
| signal_over_construction | 1.6129 |
| magnitude_over_direction | 0.0000 |
| construction_over_signal | 0.8049 |

## Legs of the full book

| key | value |
| --- | --- |
| long | net_return=0.5812; sharpe=0.5503 |
| short | net_return=1.5107; sharpe=0.9453 |
| share_of_long_symbol_bars | 0.5009 |

## Benchmark (equal-weight long, zero cost)

| key | value |
| --- | --- |
| full_sharpe | 0.5026 |
| net_return | 0.3081 |
| max_drawdown | -0.8366 |
| oos_sharpe | 0.2963 |
