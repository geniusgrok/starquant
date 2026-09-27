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
| conviction_mode | score |

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
| oos_sharpe | 1.6060 |
| oos_return | 2.4319 |
| oos_max_drawdown | -0.1353 |
| oos_bars | 44995 |
| oos_t_stat | 3.6597 |
| oos_t_lags | 15 |
| fold_sharpes | 1.2980, 0.4928, 2.2356, 1.7057, 2.3137 |
| fold_consistency | 1.0000 |

## CPCV

| key | value |
| --- | --- |
| paths | 15 |
| oos_sharpe_mean | 1.6538 |
| oos_sharpe_q05 | 1.2556 |
| oos_sharpe_min | 1.2320 |
| fraction_negative | 0.0000 |

## Multiple testing

| key | value |
| --- | --- |
| n_trials | 79 |
| grid_trials | 2 |
| prior_trials | 38 |
| sharpe_variance_period | 0.0000 |
| candidate_sharpe_annual | 1.7158 |
| expected_max_sharpe_annual | 1.4595 |
| dsr | 0.7287 |
| dsr_p_value | 0.2713 |
| pbo | 0.7472 |
| pbo_combinations | 5000 |
| degradation_slope | -0.9902 |
| prob_oos_loss | 0.0000 |
| noise_null | sharpe_variance_period=0.0000; expected_max_sharpe_annual=1.0298; dsr_p_value=0.0516 |
| ledger_trials | 39 |

## Stability

| key | value |
| --- | --- |
| time_split_sharpes | 1.1452, 1.5405, 1.6676, 2.1160 |
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
