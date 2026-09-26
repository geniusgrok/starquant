# Validation: xsmom — FAIL

## Range

| key | value |
| --- | --- |
| start | 2021-07-01 01:00:00+00:00 |
| end | 2026-09-03 04:00:00+00:00 |
| bars | 45364 |

## Best params (full sample)

| key | value |
| --- | --- |
| horizons | 168, 336, 720 |
| horizon_weights | 0.2000, 0.3000, 0.5000 |
| score_scale | 0.1500 |
| relative_weight | 0.7500 |
| rank_weight | 0.2500 |
| entry_threshold | 0.3000 |
| min_symbols | 3 |

## Full sample

| key | value |
| --- | --- |
| bars | 45364 |
| gross_return | 0.9362 |
| net_return | 0.6506 |
| annualized_sharpe | 0.6971 |
| annualized_sharpe_gross | 0.8943 |
| max_drawdown | -0.1596 |
| average_absolute_exposure | 0.7373 |
| turnover_units | 276.6 |
| nonzero_target_bars | 45364 |
| hit_rate | 0.5002 |
| cost_share_of_gross | 0.2204 |

## Walk-forward (out of sample)

| key | value |
| --- | --- |
| folds | 5 |
| oos_sharpe | 0.7199 |
| oos_return | 0.5329 |
| oos_max_drawdown | -0.1570 |
| fold_sharpes | 1.2689, 0.2814, 0.3589, 1.8192, -0.0907 |
| fold_consistency | 0.8000 |

## CPCV

| key | value |
| --- | --- |
| paths | 15 |
| oos_sharpe_mean | 0.7002 |
| oos_sharpe_q05 | -0.0112 |
| oos_sharpe_min | -0.0210 |
| fraction_negative | 0.1333 |

## Multiple testing

| key | value |
| --- | --- |
| n_trials | 4 |
| candidate_sharpe_annual | 0.6971 |
| expected_max_sharpe_annual | 0.1881 |
| dsr | 0.8769 |
| dsr_p_value | 0.1231 |
| pbo | 0.0478 |
| pbo_combinations | 5000 |
| degradation_slope | -1.0129 |
| prob_oos_loss | 0.0296 |

## Stability

| key | value |
| --- | --- |
| time_split_sharpes | 0.7555, 0.2817, 1.1019, 0.7548 |
| worst_neighbour_degradation | 0.0493 |

## Cost stress (Sharpe)

| key | value |
| --- | --- |
| x1 | 0.6991 |
| x1.5 | 0.5795 |
| x2 | 0.4598 |

## Verdict

| key | value |
| --- | --- |
| verdict | FAIL |
| reasons | dsr_p_value 0.12312774289747863 > 0.1 |
