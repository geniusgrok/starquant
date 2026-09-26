# Validation: flow — PASS

## Range

| key | value |
| --- | --- |
| start | 2021-07-01 00:00:00+00:00 |
| end | 2026-09-03 04:00:00+00:00 |
| bars | 45365 |

## Best params (full sample)

| key | value |
| --- | --- |
| window | 168 |
| scale | 0.0500 |
| volume_window | 48 |
| cross_sectional | yes |
| entry_threshold | 0.2000 |

## Full sample

| key | value |
| --- | --- |
| bars | 45365 |
| gross_return | 1.6644 |
| net_return | 1.3792 |
| annualized_sharpe | 1.1582 |
| annualized_sharpe_gross | 1.2994 |
| max_drawdown | -0.2612 |
| average_absolute_exposure | 0.7844 |
| turnover_units | 135.9 |
| nonzero_target_bars | 45059 |
| hit_rate | 0.5061 |
| cost_share_of_gross | 0.1086 |

## Walk-forward (out of sample)

| key | value |
| --- | --- |
| folds | 5 |
| oos_sharpe | 1.0684 |
| oos_return | 0.9299 |
| oos_max_drawdown | -0.2612 |
| fold_sharpes | 0.6452, 2.3769, -0.8128, 1.1519, 2.0516 |
| fold_consistency | 0.8000 |

## CPCV

| key | value |
| --- | --- |
| paths | 15 |
| oos_sharpe_mean | 1.1613 |
| oos_sharpe_q05 | 0.2418 |
| oos_sharpe_min | 0.1393 |
| fraction_negative | 0.0000 |

## Multiple testing

| key | value |
| --- | --- |
| n_trials | 4 |
| candidate_sharpe_annual | 1.1582 |
| expected_max_sharpe_annual | 0.4266 |
| dsr | 0.9520 |
| dsr_p_value | 0.0480 |
| pbo | 0.2730 |
| pbo_combinations | 5000 |
| degradation_slope | -0.5511 |
| prob_oos_loss | 0.0994 |

## Stability

| key | value |
| --- | --- |
| time_split_sharpes | 1.0080, 1.7530, -1.0014, 2.5456 |
| worst_neighbour_degradation | 0.1357 |

## Cost stress (Sharpe)

| key | value |
| --- | --- |
| x1 | 1.1582 |
| x1.5 | 1.0989 |
| x2 | 1.0395 |

## Verdict

| key | value |
| --- | --- |
| verdict | PASS |
| reasons | - |
