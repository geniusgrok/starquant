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
| entry_threshold | 0.7000 |
| min_symbols | 5 |

## Full sample

| key | value |
| --- | --- |
| bars | 45365 |
| gross_return | 0.1334 |
| net_return | 0.1276 |
| annualized_sharpe | 0.2286 |
| annualized_sharpe_gross | 0.2351 |
| max_drawdown | -0.3467 |
| average_absolute_exposure | 0.7543 |
| turnover_units | 188.2 |
| nonzero_target_bars | 45365 |
| hit_rate | 0.5022 |
| cost_share_of_gross | 0.0276 |

## Walk-forward (out of sample)

| key | value |
| --- | --- |
| folds | 5 |
| oos_sharpe | 0.0565 |
| oos_return | -0.0124 |
| oos_max_drawdown | -0.3467 |
| fold_sharpes | 0.5581, 2.3824, -0.7972, -0.0656, -1.6190 |
| fold_consistency | 0.4000 |

## CPCV

| key | value |
| --- | --- |
| paths | 15 |
| oos_sharpe_mean | 0.2351 |
| oos_sharpe_q05 | -0.8146 |
| oos_sharpe_min | -1.0853 |
| fraction_negative | 0.4000 |

## Multiple testing

| key | value |
| --- | --- |
| n_trials | 1 |
| candidate_sharpe_annual | 0.2286 |
| expected_max_sharpe_annual | 0.0000 |
| dsr | 0.6985 |
| dsr_p_value | 0.3015 |
| pbo | n/a |
| pbo_combinations | n/a |
| degradation_slope | n/a |
| prob_oos_loss | n/a |

## Stability

| key | value |
| --- | --- |
| time_split_sharpes | 0.5401, 0.7878, 0.7607, -1.8581 |
| worst_neighbour_degradation | 0.8180 |

## Cost stress (Sharpe)

| key | value |
| --- | --- |
| x1 | 0.2266 |
| x1.5 | 0.1428 |
| x2 | 0.0591 |

## Verdict

| key | value |
| --- | --- |
| verdict | FAIL |
| reasons | oos_sharpe 0.06 < 0.5, dsr_p_value 0.3014591154739982 > 0.1, fold_consistency 0.40 < 0.6 |
