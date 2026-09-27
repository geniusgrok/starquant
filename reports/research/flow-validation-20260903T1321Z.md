# Validation: flow — PASS

## Range

| key | value |
| --- | --- |
| start | 2021-01-31 00:00:00+00:00 |
| end | 2026-09-03 11:00:00+00:00 |
| bars | 48996 |

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
| bars | 48996 |
| gross_return | 3.1972 |
| net_return | 2.5763 |
| annualized_sharpe | 1.7082 |
| annualized_sharpe_gross | 1.9143 |
| max_drawdown | -0.1199 |
| average_absolute_exposure | 0.5271 |
| turnover_units | 177.2 |
| nonzero_target_bars | 48995 |
| hit_rate | 0.5112 |
| cost_share_of_gross | 0.1075 |

## Walk-forward (out of sample)

| key | value |
| --- | --- |
| folds | 5 |
| oos_sharpe | 1.7470 |
| oos_return | 2.3136 |
| oos_max_drawdown | -0.1199 |
| fold_sharpes | 1.9138, 1.2302, 2.0629, 0.6475, 2.7333 |
| fold_consistency | 1.0000 |

## CPCV

| key | value |
| --- | --- |
| paths | 15 |
| oos_sharpe_mean | 1.7036 |
| oos_sharpe_q05 | 1.2696 |
| oos_sharpe_min | 1.2577 |
| fraction_negative | 0.0000 |

## Multiple testing

| key | value |
| --- | --- |
| n_trials | 44 |
| grid_trials | 1 |
| prior_trials | 39 |
| sharpe_variance_period | 0.0000 |
| candidate_sharpe_annual | 1.7082 |
| expected_max_sharpe_annual | 0.5576 |
| dsr | 0.9968 |
| dsr_p_value | 0.0032 |
| pbo | n/a |
| pbo_combinations | n/a |
| degradation_slope | n/a |
| prob_oos_loss | n/a |
| ledger_trials | 4 |

## Stability

| key | value |
| --- | --- |
| time_split_sharpes | 1.5009, 2.1228, 0.8728, 2.4440 |
| worst_neighbour_degradation | 0.1198 |

## Cost stress (Sharpe)

| key | value |
| --- | --- |
| x1 | 1.7089 |
| x1.5 | 1.6291 |
| x2 | 1.5493 |

## Verdict

| key | value |
| --- | --- |
| verdict | PASS |
| reasons | - |
