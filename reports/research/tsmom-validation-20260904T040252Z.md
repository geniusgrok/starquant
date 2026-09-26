# Validation: tsmom — PASS

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
| bars | 48995 |
| gross_return | 4.8433 |
| net_return | 3.8887 |
| annualized_sharpe | 1.7949 |
| annualized_sharpe_gross | 1.9874 |
| max_drawdown | -0.1212 |
| average_absolute_exposure | 0.4538 |
| turnover_units | 232.9 |
| nonzero_target_bars | 48995 |
| hit_rate | 0.5092 |
| cost_share_of_gross | 0.0968 |

## Walk-forward (out of sample)

| key | value |
| --- | --- |
| folds | 5 |
| oos_sharpe | 1.3760 |
| oos_return | 1.9217 |
| oos_max_drawdown | -0.1491 |
| oos_bars | 44275 |
| oos_t_stat | 3.1280 |
| oos_t_lags | 15 |
| fold_sharpes | 1.4617, 0.7136, 0.5740, 1.7966, 2.3192 |
| fold_consistency | 1.0000 |

## CPCV

| key | value |
| --- | --- |
| paths | 15 |
| oos_sharpe_mean | 1.7144 |
| oos_sharpe_q05 | 1.2744 |
| oos_sharpe_min | 1.2358 |
| fraction_negative | 0.0000 |

## Multiple testing

| key | value |
| --- | --- |
| n_trials | 87 |
| grid_trials | 16 |
| prior_trials | 30 |
| sharpe_variance_period | 0.0000 |
| candidate_sharpe_annual | 1.7460 |
| expected_max_sharpe_annual | 1.3984 |
| dsr | 0.7936 |
| dsr_p_value | 0.2064 |
| pbo | 0.0148 |
| pbo_combinations | 5000 |
| degradation_slope | -0.9560 |
| prob_oos_loss | 0.0002 |
| noise_null | sharpe_variance_period=0.0000; expected_max_sharpe_annual=1.0531; dsr_p_value=0.0513 |
| ledger_trials | 41 |

## Stability

| key | value |
| --- | --- |
| time_split_sharpes | 1.3990, 0.7803, 1.2153, 2.1015 |
| worst_neighbour_degradation | 0.1039 |

## Cost stress (Sharpe)

| key | value |
| --- | --- |
| x1 | 1.7946 |
| x1.5 | 1.7064 |
| x2 | 1.6182 |

## Verdict

| key | value |
| --- | --- |
| verdict | PASS |
| reasons | - |
