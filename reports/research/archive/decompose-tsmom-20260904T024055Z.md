# Decomposition: tsmom

## Range

| key | value |
| --- | --- |
| start | 2025-01-31 01:00:00+00:00 |
| end | 2026-09-03 11:00:00+00:00 |
| bars | 13931 |
| oos_start | 2025-07-16 17:00:00+00:00 |

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

- full: sharpe=2.00 oos=2.19 net=0.610 mdd=-0.079 turnover=72 exposure=0.494 corr_full=1.00 folds=[1.5, 2.46, 1.71, 3.0, 2.29]
- constant_long: sharpe=-0.41 oos=-0.76 net=-0.112 mdd=-0.266 turnover=6 exposure=0.259 corr_full=-0.25 folds=[1.2, -3.82, -2.21, -0.73, 1.94]
- sign_only: sharpe=2.00 oos=2.19 net=0.610 mdd=-0.079 turnover=72 exposure=0.494 corr_full=1.00 folds=[1.5, 2.46, 1.71, 3.0, 2.29]
- long_only: sharpe=0.68 oos=0.31 net=0.150 mdd=-0.175 turnover=32 exposure=0.226 corr_full=0.09 folds=[1.67, -3.6, -0.76, 1.6, 1.97]
- short_only: sharpe=1.15 oos=1.62 net=0.292 mdd=-0.162 turnover=27 exposure=0.223 corr_full=0.49 folds=[-0.73, 3.98, 2.74, 2.11, -0.63]
- equal_notional: sharpe=1.42 oos=1.68 net=1.921 mdd=-0.316 turnover=61 exposure=0.997 corr_full=0.85 folds=[1.33, 2.13, 1.31, 1.49, 2.15]

## Increments (Sharpe)

| key | value |
| --- | --- |
| signal_over_construction | 2.4127 |
| magnitude_over_direction | 0.0000 |
| construction_over_signal | 0.5762 |

## Legs of the full book

| key | value |
| --- | --- |
| long | net_return=0.2585; sharpe=0.9797 |
| short | net_return=0.2458; sharpe=0.8514 |
| share_of_long_symbol_bars | 0.4001 |

## Benchmark (equal-weight long, zero cost)

| key | value |
| --- | --- |
| full_sharpe | -0.0988 |
| net_return | -0.3760 |
| max_drawdown | -0.5816 |
| oos_sharpe | -0.1360 |
