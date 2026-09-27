# Validation: tsmom — FAIL

## Range

| key | value |
| --- | --- |
| start | 2021-06-09 09:00:00+00:00 |
| end | 2026-09-03 04:00:00+00:00 |
| bars | 45884 |

## Best params (full sample)

| key | value |
| --- | --- |
| horizons | 5, 20, 50 |
| horizon_weights | 0.2000, 0.3000, 0.5000 |
| return_weight | 0.4000 |
| slope_weight | 0.2500 |
| persistence_weight | 0.1000 |
| return_scale | 0.3000 |
| slope_scale | 0.0100 |
| entry_threshold | 0.3000 |
| vol_window | 400 |

## Full sample

| key | value |
| --- | --- |
| bars | 45884 |
| gross_return | 0.4430 |
| net_return | 0.1588 |
| annualized_sharpe | 0.2717 |
| annualized_sharpe_gross | 0.5725 |
| max_drawdown | -0.1447 |
| average_absolute_exposure | 0.4259 |
| turnover_units | 277.9 |
| nonzero_target_bars | 45878 |
| hit_rate | 0.5041 |
| cost_share_of_gross | 0.5253 |

## Walk-forward (out of sample)

| key | value |
| --- | --- |
| folds | 5 |
| oos_sharpe | 0.3238 |
| oos_return | 0.1636 |
| oos_max_drawdown | -0.1441 |
| fold_sharpes | 1.1341, -0.1096, 0.7311, -0.1511, -0.1152 |
| fold_consistency | 0.4000 |

## CPCV

| key | value |
| --- | --- |
| paths | 15 |
| oos_sharpe_mean | 0.1467 |
| oos_sharpe_q05 | -0.5162 |
| oos_sharpe_min | -0.7274 |
| fraction_negative | 0.3333 |

## Multiple testing

| key | value |
| --- | --- |
| n_trials | 27 |
| candidate_sharpe_annual | 0.2717 |
| expected_max_sharpe_annual | 0.6921 |
| dsr | 0.1679 |
| dsr_p_value | 0.8321 |
| pbo | 0.2124 |
| pbo_combinations | 5000 |
| degradation_slope | -0.9179 |
| prob_oos_loss | 0.4364 |

## Stability

| key | value |
| --- | --- |
| time_split_sharpes | 0.7636, 0.5373, 0.2197, -0.2738 |
| worst_neighbour_degradation | 1.2582 |

## Cost stress (Sharpe)

| key | value |
| --- | --- |
| x1 | 0.2717 |
| x1.5 | 0.1383 |
| x2 | 0.0049 |

## Verdict

| key | value |
| --- | --- |
| verdict | FAIL |
| reasons | oos_sharpe 0.32 < 0.5, dsr_p_value 0.8320534562396051 > 0.1, fold_consistency 0.40 < 0.6 |
