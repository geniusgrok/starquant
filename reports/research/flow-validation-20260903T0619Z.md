# Validation: flow — FAIL

## Range

| key | value |
| --- | --- |
| start | 2021-07-01 00:00:00+00:00 |
| end | 2026-09-03 04:00:00+00:00 |
| bars | 45365 |

## Best params (full sample)

| key | value |
| --- | --- |
| window | 72 |
| scale | 0.1000 |
| volume_window | 48 |
| cross_sectional | yes |
| entry_threshold | 0.2000 |

## Full sample

| key | value |
| --- | --- |
| bars | 45365 |
| gross_return | 2.3447 |
| net_return | 2.1442 |
| annualized_sharpe | 1.5459 |
| annualized_sharpe_gross | 1.6255 |
| max_drawdown | -0.1857 |
| average_absolute_exposure | 0.7099 |
| turnover_units | 59.1906 |
| nonzero_target_bars | 44779 |
| hit_rate | 0.5064 |
| cost_share_of_gross | 0.0488 |

## Walk-forward (out of sample)

| key | value |
| --- | --- |
| folds | 5 |
| oos_sharpe | 1.1147 |
| oos_return | 0.9914 |
| oos_max_drawdown | -0.1811 |
| fold_sharpes | -0.8730, 2.5731, 0.0065, 1.3545, 2.4328 |
| fold_consistency | 0.8000 |

## CPCV

| key | value |
| --- | --- |
| paths | 15 |
| oos_sharpe_mean | 0.8764 |
| oos_sharpe_q05 | -0.0388 |
| oos_sharpe_min | -0.1759 |
| fraction_negative | 0.0667 |

## Multiple testing

| key | value |
| --- | --- |
| n_trials | 24 |
| candidate_sharpe_annual | 1.5459 |
| expected_max_sharpe_annual | 1.5888 |
| dsr | 0.4611 |
| dsr_p_value | 0.5389 |
| pbo | 0.1986 |
| pbo_combinations | 5000 |
| degradation_slope | -0.6919 |
| prob_oos_loss | 0.0482 |

## Stability

| key | value |
| --- | --- |
| time_split_sharpes | 0.1461, 1.8370, -0.3472, 2.8189 |
| worst_neighbour_degradation | 0.3441 |

## Cost stress (Sharpe)

| key | value |
| --- | --- |
| x1 | 1.5459 |
| x1.5 | 1.5192 |
| x2 | 1.4925 |

## Verdict

| key | value |
| --- | --- |
| verdict | FAIL |
| reasons | dsr_p_value 0.5388528984242302 > 0.1 |
