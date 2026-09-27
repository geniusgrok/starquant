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
| short_gate | 0.3000 |
| gate_horizons | 168, 336, 720 |
| gate_weights | 0.2000, 0.3000, 0.5000 |
| gate_return_scale | 0.2000 |
| gate_vol_window | 400 |

## Full sample

| key | value |
| --- | --- |
| bars | 45365 |
| gross_return | 2.8149 |
| net_return | 2.3194 |
| annualized_sharpe | 1.7406 |
| annualized_sharpe_gross | 1.9345 |
| max_drawdown | -0.1199 |
| average_absolute_exposure | 0.5465 |
| turnover_units | 163.6 |
| nonzero_target_bars | 45059 |
| hit_rate | 0.5115 |
| cost_share_of_gross | 0.1002 |

## Walk-forward (out of sample)

| key | value |
| --- | --- |
| folds | 5 |
| oos_sharpe | 1.3953 |
| oos_return | 1.4385 |
| oos_max_drawdown | -0.1525 |
| fold_sharpes | 0.4753, 1.4513, 1.9794, 0.7565, 2.3852 |
| fold_consistency | 1.0000 |

## CPCV

| key | value |
| --- | --- |
| paths | 15 |
| oos_sharpe_mean | 1.6625 |
| oos_sharpe_q05 | 1.2945 |
| oos_sharpe_min | 1.1782 |
| fraction_negative | 0.0000 |

## Multiple testing

| key | value |
| --- | --- |
| n_trials | 42 |
| grid_trials | 3 |
| prior_trials | 39 |
| sharpe_variance_period | 0.0000 |
| candidate_sharpe_annual | 1.7406 |
| expected_max_sharpe_annual | 0.6687 |
| dsr | 0.9927 |
| dsr_p_value | 0.0073 |
| pbo | 0.5738 |
| pbo_combinations | 5000 |
| degradation_slope | -0.9824 |
| prob_oos_loss | 0.0000 |
| ledger_trials | 0 |

## Stability

| key | value |
| --- | --- |
| time_split_sharpes | 0.9644, 2.2662, 0.0508, 2.2761 |
| worst_neighbour_degradation | 0.1438 |

## Cost stress (Sharpe)

| key | value |
| --- | --- |
| x1 | 1.7406 |
| x1.5 | 1.6608 |
| x2 | 1.5809 |

## Verdict

| key | value |
| --- | --- |
| verdict | PASS |
| reasons | - |
