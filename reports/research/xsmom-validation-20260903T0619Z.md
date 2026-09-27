# Validation: xsmom — FAIL

## Range

| key | value |
| --- | --- |
| start | 2021-07-31 01:00:00+00:00 |
| end | 2026-09-03 04:00:00+00:00 |
| bars | 44644 |

## Best params (full sample)

| key | value |
| --- | --- |
| horizons | 24, 72, 168 |
| horizon_weights | 0.2000, 0.3000, 0.5000 |
| score_scale | 0.1500 |
| relative_weight | 0.7500 |
| rank_weight | 0.2500 |
| entry_threshold | 0.3000 |
| min_symbols | 3 |

## Full sample

| key | value |
| --- | --- |
| bars | 45365 |
| gross_return | 1.9132 |
| net_return | 0.9503 |
| annualized_sharpe | 0.8958 |
| annualized_sharpe_gross | 1.3868 |
| max_drawdown | -0.1485 |
| average_absolute_exposure | 0.7495 |
| turnover_units | 612.6 |
| nonzero_target_bars | 45365 |
| hit_rate | 0.5023 |
| cost_share_of_gross | 0.3539 |

## Walk-forward (out of sample)

| key | value |
| --- | --- |
| folds | 5 |
| oos_sharpe | 1.0335 |
| oos_return | 0.8803 |
| oos_max_drawdown | -0.1485 |
| fold_sharpes | 1.0357, 1.0465, 0.8184, 1.3928, 0.8773 |
| fold_consistency | 1.0000 |

## CPCV

| key | value |
| --- | --- |
| paths | 15 |
| oos_sharpe_mean | 0.7204 |
| oos_sharpe_q05 | -0.3296 |
| oos_sharpe_min | -0.9427 |
| fraction_negative | 0.1333 |

## Multiple testing

| key | value |
| --- | --- |
| n_trials | 12 |
| candidate_sharpe_annual | 0.9631 |
| expected_max_sharpe_annual | 0.4551 |
| dsr | 0.8746 |
| dsr_p_value | 0.1254 |
| pbo | 0.2018 |
| pbo_combinations | 5000 |
| degradation_slope | -1.0643 |
| prob_oos_loss | 0.1494 |

## Stability

| key | value |
| --- | --- |
| time_split_sharpes | 1.1307, 0.5257, 0.8819, 1.5839 |
| worst_neighbour_degradation | 0.1842 |

## Cost stress (Sharpe)

| key | value |
| --- | --- |
| x1 | 0.8960 |
| x1.5 | 0.6336 |
| x2 | 0.3714 |

## Verdict

| key | value |
| --- | --- |
| verdict | FAIL |
| reasons | dsr_p_value 0.12542432177423835 > 0.1 |
