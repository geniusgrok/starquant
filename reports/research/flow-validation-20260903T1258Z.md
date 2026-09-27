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
| gross_return | 3.3663 |
| net_return | 2.7237 |
| annualized_sharpe | 1.7563 |
| annualized_sharpe_gross | 1.9608 |
| max_drawdown | -0.1199 |
| average_absolute_exposure | 0.5264 |
| turnover_units | 176.0 |
| nonzero_target_bars | 48995 |
| hit_rate | 0.5117 |
| cost_share_of_gross | 0.1042 |

## Walk-forward (out of sample)

| key | value |
| --- | --- |
| folds | 5 |
| oos_sharpe | 1.7993 |
| oos_return | 2.4501 |
| oos_max_drawdown | -0.1199 |
| fold_sharpes | 2.1590, 1.2302, 2.0629, 0.6475, 2.7333 |
| fold_consistency | 1.0000 |

## CPCV

| key | value |
| --- | --- |
| paths | 15 |
| oos_sharpe_mean | 1.7520 |
| oos_sharpe_q05 | 1.4190 |
| oos_sharpe_min | 1.4054 |
| fraction_negative | 0.0000 |

## Multiple testing

| key | value |
| --- | --- |
| n_trials | 43 |
| grid_trials | 1 |
| prior_trials | 39 |
| sharpe_variance_period | 0.0000 |
| candidate_sharpe_annual | 1.7563 |
| expected_max_sharpe_annual | 0.6190 |
| dsr | 0.9964 |
| dsr_p_value | 0.0036 |
| pbo | n/a |
| pbo_combinations | n/a |
| degradation_slope | n/a |
| prob_oos_loss | n/a |
| ledger_trials | 3 |

## Stability

| key | value |
| --- | --- |
| time_split_sharpes | 1.7042, 2.1228, 0.8728, 2.4440 |
| worst_neighbour_degradation | 0.1304 |

## Cost stress (Sharpe)

| key | value |
| --- | --- |
| x1 | 1.7570 |
| x1.5 | 1.6780 |
| x2 | 1.5989 |

## Verdict

| key | value |
| --- | --- |
| verdict | PASS |
| reasons | - |
