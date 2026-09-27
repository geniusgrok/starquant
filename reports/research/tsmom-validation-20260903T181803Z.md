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

## Full sample

| key | value |
| --- | --- |
| bars | 48995 |
| gross_return | 4.3812 |
| net_return | 3.1692 |
| annualized_sharpe | 1.7158 |
| annualized_sharpe_gross | 2.0085 |
| max_drawdown | -0.1353 |
| average_absolute_exposure | 0.3832 |
| turnover_units | 357.4 |
| nonzero_target_bars | 48995 |
| hit_rate | 0.5090 |
| cost_share_of_gross | 0.1457 |

## Walk-forward (out of sample)

| key | value |
| --- | --- |
| folds | 5 |
| oos_sharpe | 1.5445 |
| oos_return | 2.2331 |
| oos_max_drawdown | -0.1353 |
| oos_bars | 44995 |
| oos_t_stat | 3.5027 |
| oos_t_lags | 15 |
| fold_sharpes | 1.2234, 0.4928, 2.0446, 1.6549, 2.3137 |
| fold_consistency | 1.0000 |

## CPCV

| key | value |
| --- | --- |
| paths | 15 |
| oos_sharpe_mean | 1.6506 |
| oos_sharpe_q05 | 1.2619 |
| oos_sharpe_min | 1.2529 |
| fraction_negative | 0.0000 |

## Multiple testing

| key | value |
| --- | --- |
| n_trials | 69 |
| grid_trials | 2 |
| prior_trials | 27 |
| sharpe_variance_period | 0.0000 |
| candidate_sharpe_annual | 1.7158 |
| expected_max_sharpe_annual | 1.4405 |
| dsr | 0.7434 |
| dsr_p_value | 0.2566 |
| pbo | 0.5484 |
| pbo_combinations | 5000 |
| degradation_slope | -0.9278 |
| prob_oos_loss | 0.0000 |
| ledger_trials | 40 |

## Stability

| key | value |
| --- | --- |
| time_split_sharpes | 1.0798, 1.4935, 1.5392, 2.0936 |
| worst_neighbour_degradation | 0.0712 |

## Cost stress (Sharpe)

| key | value |
| --- | --- |
| x1 | 1.7156 |
| x1.5 | 1.5719 |
| x2 | 1.4282 |

## Verdict

| key | value |
| --- | --- |
| verdict | PASS |
| reasons | - |
