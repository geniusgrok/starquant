# Validation: breakout — FAIL

## Range

| key | value |
| --- | --- |
| start | 2021-01-31 01:00:00+00:00 |
| end | 2026-09-03 11:00:00+00:00 |
| bars | 48995 |

## Best params (full sample)

| key | value |
| --- | --- |
| window | 24 |
| atr_window | 14 |
| distance_scale | 3.0000 |
| volume_window | 20 |
| entry_threshold | 0.2000 |

## Full sample

| key | value |
| --- | --- |
| bars | 48995 |
| gross_return | 0.2645 |
| net_return | -0.9908 |
| annualized_sharpe | -5.1264 |
| annualized_sharpe_gross | 0.3421 |
| max_drawdown | -0.9909 |
| average_absolute_exposure | 0.6866 |
| turnover_units | 7036.5 |
| nonzero_target_bars | 48994 |
| hit_rate | 0.4755 |
| cost_share_of_gross | 16.0603 |

## Walk-forward (out of sample)

| key | value |
| --- | --- |
| folds | 5 |
| oos_sharpe | -5.6177 |
| oos_return | -0.9907 |
| oos_max_drawdown | -0.9908 |
| oos_bars | 44995 |
| oos_t_stat | -13.0797 |
| oos_t_lags | 15 |
| fold_sharpes | -4.8341, -6.9119, -5.6047, -4.4903, -6.2731 |
| fold_consistency | 0.0000 |

## CPCV

| key | value |
| --- | --- |
| paths | 15 |
| oos_sharpe_mean | -5.6495 |
| oos_sharpe_q05 | -7.0895 |
| oos_sharpe_min | -7.3731 |
| fraction_negative | 1.0000 |

## Multiple testing

| key | value |
| --- | --- |
| n_trials | 10 |
| grid_trials | 9 |
| prior_trials | 1 |
| sharpe_variance_period | 0.0004 |
| candidate_sharpe_annual | -5.1264 |
| expected_max_sharpe_annual | 2.9233 |
| dsr | 0.0000 |
| dsr_p_value | 1.0000 |
| pbo | 0.0000 |
| pbo_combinations | 5000 |
| degradation_slope | -0.8293 |
| prob_oos_loss | 1.0000 |
| noise_null | sharpe_variance_period=0.0000; expected_max_sharpe_annual=0.6598; dsr_p_value=1.0000 |
| ledger_trials | 0 |

## Stability

| key | value |
| --- | --- |
| time_split_sharpes | -4.2775, -7.9086, -4.1189, -6.2222 |
| worst_neighbour_degradation | 0.2118 |

## Cost stress (Sharpe)

| key | value |
| --- | --- |
| x1 | -5.1291 |
| x1.5 | -7.8164 |
| x2 | -10.4461 |

## Verdict

| key | value |
| --- | --- |
| verdict | FAIL |
| reasons | oos_sharpe -5.62 < 0.5, oos_t_stat -13.079703472133513 < 1.5, fold_consistency 0.00 < 0.6, cpcv fraction_negative 1.00 > 0.1, cost stress x2 sharpe -10.45 < 0.0 |
