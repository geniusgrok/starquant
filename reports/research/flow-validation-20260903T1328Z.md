# Validation: flow — FAIL

## Range

| key | value |
| --- | --- |
| start | 2021-01-31 01:00:00+00:00 |
| end | 2026-09-03 11:00:00+00:00 |
| bars | 48995 |

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
| bars | 48995 |
| gross_return | 0.9840 |
| net_return | 0.8910 |
| annualized_sharpe | 1.1078 |
| annualized_sharpe_gross | 1.1874 |
| max_drawdown | -0.1101 |
| average_absolute_exposure | 0.0936 |
| turnover_units | 93.9774 |
| nonzero_target_bars | 31619 |
| hit_rate | 0.4987 |
| cost_share_of_gross | 0.0669 |

## Walk-forward (out of sample)

| key | value |
| --- | --- |
| folds | 5 |
| oos_sharpe | 1.0933 |
| oos_return | 0.7795 |
| oos_max_drawdown | -0.1101 |
| fold_sharpes | 1.6348, 0.9055, 0.7936, -0.6275, 2.1331 |
| fold_consistency | 0.8000 |

## CPCV

| key | value |
| --- | --- |
| paths | 15 |
| oos_sharpe_mean | 1.0873 |
| oos_sharpe_q05 | 0.4715 |
| oos_sharpe_min | 0.1417 |
| fraction_negative | 0.0000 |

## Multiple testing

| key | value |
| --- | --- |
| n_trials | 46 |
| grid_trials | 1 |
| prior_trials | 39 |
| sharpe_variance_period | 0.0000 |
| candidate_sharpe_annual | 1.1078 |
| expected_max_sharpe_annual | 0.8358 |
| dsr | 0.7423 |
| dsr_p_value | 0.2577 |
| pbo | n/a |
| pbo_combinations | n/a |
| degradation_slope | n/a |
| prob_oos_loss | n/a |
| ledger_trials | 6 |

## Stability

| key | value |
| --- | --- |
| time_split_sharpes | 1.3048, 1.1362, -0.0848, 1.8857 |
| worst_neighbour_degradation | 0.1565 |

## Cost stress (Sharpe)

| key | value |
| --- | --- |
| x1 | 1.1078 |
| x1.5 | 1.0534 |
| x2 | 0.9990 |

## Verdict

| key | value |
| --- | --- |
| verdict | FAIL |
| reasons | dsr_p_value 0.25767909438157477 > 0.1 |
