# Validation: flow — FAIL

## Range

| key | value |
| --- | --- |
| start | 2021-12-01 01:00:00+00:00 |
| end | 2026-09-03 11:00:00+00:00 |
| bars | 41699 |

## Best params (full sample)

| key | value |
| --- | --- |
| window | 168 |
| scale | 0.0500 |
| volume_window | 48 |
| cross_sectional | yes |
| entry_threshold | 0.2000 |
| short_gate | 0.3000 |
| long_side | no |
| gate_horizons | 168, 336, 720 |
| gate_weights | 0.2000, 0.3000, 0.5000 |
| gate_return_scale | 0.2000 |
| gate_vol_window | 400 |

## Full sample

| key | value |
| --- | --- |
| bars | 41699 |
| gross_return | 0.0834 |
| net_return | 0.0686 |
| annualized_sharpe | 0.2855 |
| annualized_sharpe_gross | 0.3390 |
| max_drawdown | -0.0967 |
| average_absolute_exposure | 0.0380 |
| turnover_units | 19.6465 |
| nonzero_target_bars | 10690 |
| hit_rate | 0.5017 |
| cost_share_of_gross | 0.1578 |

## Walk-forward (out of sample)

| key | value |
| --- | --- |
| folds | 5 |
| oos_sharpe | 0.0832 |
| oos_return | 0.0128 |
| oos_max_drawdown | -0.0967 |
| fold_sharpes | 0.2526, -0.2981, -0.0322, 1.1180, -0.4033 |
| fold_consistency | 0.4000 |

## CPCV

| key | value |
| --- | --- |
| paths | 15 |
| oos_sharpe_mean | 0.3559 |
| oos_sharpe_q05 | -0.6769 |
| oos_sharpe_min | -0.7653 |
| fraction_negative | 0.2667 |

## Multiple testing

| key | value |
| --- | --- |
| n_trials | 48 |
| grid_trials | 1 |
| prior_trials | 39 |
| sharpe_variance_period | 0.0000 |
| candidate_sharpe_annual | 0.2855 |
| expected_max_sharpe_annual | 1.4699 |
| dsr | 0.0049 |
| dsr_p_value | 0.9951 |
| pbo | n/a |
| pbo_combinations | n/a |
| degradation_slope | n/a |
| prob_oos_loss | n/a |
| ledger_trials | 8 |

## Stability

| key | value |
| --- | --- |
| time_split_sharpes | 0.0496, 0.7009, 0.2998, -0.1603 |
| worst_neighbour_degradation | 1.0033 |

## Cost stress (Sharpe)

| key | value |
| --- | --- |
| x1 | 0.2855 |
| x1.5 | 0.2587 |
| x2 | 0.2319 |

## Verdict

| key | value |
| --- | --- |
| verdict | FAIL |
| reasons | oos_sharpe 0.08 < 0.5, dsr_p_value 0.9951059173474786 > 0.1, fold_consistency 0.40 < 0.6 |
