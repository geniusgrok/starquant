# Validation: carry — FAIL

## Range

| key | value |
| --- | --- |
| start | 2021-07-01 00:00:00+00:00 |
| end | 2026-09-03 04:00:00+00:00 |
| bars | 45365 |

## Best params (full sample)

| key | value |
| --- | --- |
| window_bars | 168 |
| mode | rank |
| scale | 0.0001 |
| cross_sectional | yes |
| winsor_pct | 0.1000 |
| entry_threshold | 0.3000 |
| min_symbols | 5 |

## Full sample

| key | value |
| --- | --- |
| bars | 45365 |
| gross_return | 0.2773 |
| net_return | 0.1366 |
| annualized_sharpe | 0.2410 |
| annualized_sharpe_gross | 0.3931 |
| max_drawdown | -0.3627 |
| average_absolute_exposure | 0.8055 |
| turnover_units | 366.1 |
| nonzero_target_bars | 45365 |
| hit_rate | 0.5040 |
| cost_share_of_gross | 0.3869 |

## Walk-forward (out of sample)

| key | value |
| --- | --- |
| folds | 5 |
| oos_sharpe | -0.1524 |
| oos_return | -0.1351 |
| oos_max_drawdown | -0.3680 |
| fold_sharpes | 1.3980, 0.7431, -0.4203, -0.2172, -2.1025 |
| fold_consistency | 0.4000 |

## CPCV

| key | value |
| --- | --- |
| paths | 15 |
| oos_sharpe_mean | 0.0416 |
| oos_sharpe_q05 | -1.0229 |
| oos_sharpe_min | -1.1573 |
| fraction_negative | 0.4667 |

## Multiple testing

| key | value |
| --- | --- |
| n_trials | 4 |
| candidate_sharpe_annual | 0.2410 |
| expected_max_sharpe_annual | 0.1549 |
| dsr | 0.5777 |
| dsr_p_value | 0.4223 |
| pbo | 0.5166 |
| pbo_combinations | 5000 |
| degradation_slope | -1.0602 |
| prob_oos_loss | 0.4514 |

## Stability

| key | value |
| --- | --- |
| time_split_sharpes | 1.0054, 0.0974, 0.5371, -2.1767 |
| worst_neighbour_degradation | 0.0348 |

## Cost stress (Sharpe)

| key | value |
| --- | --- |
| x1 | 0.2394 |
| x1.5 | 0.0723 |
| x2 | -0.0946 |

## Verdict

| key | value |
| --- | --- |
| verdict | FAIL |
| reasons | oos_sharpe -0.15 < 0.5, dsr_p_value 0.4223419254407518 > 0.1, fold_consistency 0.40 < 0.6, pbo 0.52 > 0.3, cost stress x2 sharpe -0.09 < 0.0 |
