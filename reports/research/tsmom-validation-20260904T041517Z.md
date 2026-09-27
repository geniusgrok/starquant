# Validation: tsmom — PASS

## Range

| key | value |
| --- | --- |
| start | 2021-01-31 01:00:00+00:00 |
| end | 2026-09-03 11:00:00+00:00 |
| bars | 48995 |

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
| oos_sharpe | 1.6450 |
| oos_return | 2.7978 |
| oos_max_drawdown | -0.1583 |
| oos_bars | 44995 |
| oos_t_stat | 3.7772 |
| oos_t_lags | 15 |
| fold_sharpes | 1.2947, 0.2872, 2.6951, 1.5814, 2.3542 |
| fold_consistency | 1.0000 |

## CPCV

| key | value |
| --- | --- |
| paths | 15 |
| oos_sharpe_mean | 1.7476 |
| oos_sharpe_q05 | 1.2606 |
| oos_sharpe_min | 1.0799 |
| fraction_negative | 0.0000 |

## Multiple testing

| key | value |
| --- | --- |
| n_trials | 97 |
| grid_trials | 2 |
| prior_trials | 38 |
| sharpe_variance_period | 0.0000 |
| candidate_sharpe_annual | 1.7949 |
| expected_max_sharpe_annual | 1.4479 |
| dsr | 0.7948 |
| dsr_p_value | 0.2052 |
| pbo | 0.1466 |
| pbo_combinations | 5000 |
| degradation_slope | -1.0329 |
| prob_oos_loss | 0.0000 |
| noise_null | sharpe_variance_period=0.0000; expected_max_sharpe_annual=1.0620; dsr_p_value=0.0410 |
| ledger_trials | 57 |

## Stability

| key | value |
| --- | --- |
| time_split_sharpes | 1.1685, 1.4666, 1.9610, 2.0079 |
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
