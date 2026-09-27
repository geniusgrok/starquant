# Validation: tsmom — WEAK_PASS

## Range

| key | value |
| --- | --- |
| start | 2021-03-02 01:00:00+00:00 |
| end | 2026-09-03 11:00:00+00:00 |
| bars | 48275 |

## Best params (full sample)

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

## Full sample

| key | value |
| --- | --- |
| bars | 48299 |
| gross_return | 3.6388 |
| net_return | 2.8073 |
| annualized_sharpe | 1.5468 |
| annualized_sharpe_gross | 1.7633 |
| max_drawdown | -0.1117 |
| average_absolute_exposure | 0.4608 |
| turnover_units | 236.3 |
| nonzero_target_bars | 48299 |
| hit_rate | 0.5088 |
| cost_share_of_gross | 0.1227 |

## Walk-forward (out of sample)

| key | value |
| --- | --- |
| folds | 5 |
| oos_sharpe | 0.9582 |
| oos_return | 1.0930 |
| oos_max_drawdown | -0.1392 |
| oos_bars | 44275 |
| oos_t_stat | 2.1698 |
| oos_t_lags | 15 |
| fold_sharpes | 0.4211, 0.4674, 0.4939, 1.6528, 1.7591 |
| fold_consistency | 1.0000 |

## CPCV

| key | value |
| --- | --- |
| paths | 15 |
| oos_sharpe_mean | 1.5161 |
| oos_sharpe_q05 | 1.0838 |
| oos_sharpe_min | 0.9764 |
| fraction_negative | 0.0000 |

## Multiple testing

| key | value |
| --- | --- |
| n_trials | 95 |
| grid_trials | 16 |
| prior_trials | 38 |
| sharpe_variance_period | 0.0000 |
| candidate_sharpe_annual | 1.5374 |
| expected_max_sharpe_annual | 1.4201 |
| dsr | 0.6090 |
| dsr_p_value | 0.3910 |
| pbo | 0.0200 |
| pbo_combinations | 5000 |
| degradation_slope | -0.8897 |
| prob_oos_loss | 0.0002 |
| noise_null | sharpe_variance_period=0.0000; expected_max_sharpe_annual=1.0649; dsr_p_value=0.1325 |
| ledger_trials | 41 |

## Stability

| key | value |
| --- | --- |
| time_split_sharpes | 0.4657, 0.4250, 1.2690, 1.6741 |
| worst_neighbour_degradation | 0.0782 |

## Cost stress (Sharpe)

| key | value |
| --- | --- |
| x1 | 1.5462 |
| x1.5 | 1.4554 |
| x2 | 1.3646 |

## Verdict

| key | value |
| --- | --- |
| verdict | WEAK_PASS |
| reasons | - |
