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
| gross_return | 4.0633 |
| net_return | 3.1543 |
| annualized_sharpe | 1.6802 |
| annualized_sharpe_gross | 1.9027 |
| max_drawdown | -0.1175 |
| average_absolute_exposure | 0.4448 |
| turnover_units | 263.8 |
| nonzero_target_bars | 48995 |
| hit_rate | 0.5096 |
| cost_share_of_gross | 0.1169 |

## Walk-forward (out of sample)

| key | value |
| --- | --- |
| folds | 5 |
| oos_sharpe | 1.6026 |
| oos_return | 2.4778 |
| oos_max_drawdown | -0.1175 |
| oos_bars | 44995 |
| oos_t_stat | 3.6858 |
| oos_t_lags | 15 |
| fold_sharpes | 1.2980, 0.5184, 2.3557, 1.5344, 2.2987 |
| fold_consistency | 1.0000 |

## CPCV

| key | value |
| --- | --- |
| paths | 15 |
| oos_sharpe_mean | 1.6838 |
| oos_sharpe_q05 | 1.2318 |
| oos_sharpe_min | 1.2313 |
| fraction_negative | 0.0000 |

## Multiple testing

| key | value |
| --- | --- |
| n_trials | 79 |
| grid_trials | 1 |
| prior_trials | 38 |
| sharpe_variance_period | 0.0000 |
| candidate_sharpe_annual | 1.6802 |
| expected_max_sharpe_annual | 1.4595 |
| dsr | 0.6995 |
| dsr_p_value | 0.3005 |
| pbo | n/a |
| pbo_combinations | n/a |
| degradation_slope | n/a |
| prob_oos_loss | n/a |
| noise_null | sharpe_variance_period=0.0000; expected_max_sharpe_annual=1.0321; dsr_p_value=0.0623 |
| ledger_trials | 40 |

## Stability

| key | value |
| --- | --- |
| time_split_sharpes | 1.1544, 1.5275, 1.7627, 1.9929 |
| worst_neighbour_degradation | 0.0772 |

## Cost stress (Sharpe)

| key | value |
| --- | --- |
| x1 | 1.6799 |
| x1.5 | 1.5759 |
| x2 | 1.4718 |

## Verdict

| key | value |
| --- | --- |
| verdict | PASS |
| reasons | - |
