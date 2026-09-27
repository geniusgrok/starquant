# Validation: meanrev — FAIL

## Range

| key | value |
| --- | --- |
| start | 2021-01-31 01:00:00+00:00 |
| end | 2026-09-03 11:00:00+00:00 |
| bars | 48995 |

## Best params (full sample)

| key | value |
| --- | --- |
| window | 96 |
| z_entry | 2.5000 |
| z_exit | 0.5000 |
| z_max | 5.0000 |
| trend_gate_z | 1.5000 |
| vol_window | 48 |
| entry_threshold | 0.2000 |

## Full sample

| key | value |
| --- | --- |
| bars | 48995 |
| gross_return | -0.7858 |
| net_return | -0.8559 |
| annualized_sharpe | -2.1994 |
| annualized_sharpe_gross | -1.7335 |
| max_drawdown | -0.8611 |
| average_absolute_exposure | 0.1583 |
| turnover_units | 592.9 |
| nonzero_target_bars | 37537 |
| hit_rate | 0.4913 |
| cost_share_of_gross | n/a |

## Walk-forward (out of sample)

| key | value |
| --- | --- |
| folds | 5 |
| oos_sharpe | -2.8891 |
| oos_return | -0.9042 |
| oos_max_drawdown | -0.9111 |
| oos_bars | 44995 |
| oos_t_stat | -6.6629 |
| oos_t_lags | 15 |
| fold_sharpes | -3.2979, -1.7447, -2.3043, -3.3507, -3.7721 |
| fold_consistency | 0.0000 |

## CPCV

| key | value |
| --- | --- |
| paths | 15 |
| oos_sharpe_mean | -2.3954 |
| oos_sharpe_q05 | -2.9325 |
| oos_sharpe_min | -3.2227 |
| fraction_negative | 1.0000 |

## Multiple testing

| key | value |
| --- | --- |
| n_trials | 28 |
| grid_trials | 27 |
| prior_trials | 1 |
| sharpe_variance_period | 0.0001 |
| candidate_sharpe_annual | -2.1994 |
| expected_max_sharpe_annual | 1.7177 |
| dsr | 0.0000 |
| dsr_p_value | 1.0000 |
| pbo | 0.0252 |
| pbo_combinations | 5000 |
| degradation_slope | -1.0635 |
| prob_oos_loss | 1.0000 |
| noise_null | sharpe_variance_period=0.0000; expected_max_sharpe_annual=0.8502; dsr_p_value=1.0000 |
| ledger_trials | 0 |

## Stability

| key | value |
| --- | --- |
| time_split_sharpes | -2.9416, -1.9713, -2.9914, -3.6848 |
| worst_neighbour_degradation | 0.0856 |

## Cost stress (Sharpe)

| key | value |
| --- | --- |
| x1 | -2.1995 |
| x1.5 | -2.4428 |
| x2 | -2.6859 |

## Verdict

| key | value |
| --- | --- |
| verdict | FAIL |
| reasons | oos_sharpe -2.89 < 0.5, oos_t_stat -6.662936560477312 < 1.5, fold_consistency 0.00 < 0.6, cpcv fraction_negative 1.00 > 0.1, cost stress x2 sharpe -2.69 < 0.0 |
