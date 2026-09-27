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
| gate_horizons | 168, 336, 720 |
| gate_weights | 0.2000, 0.3000, 0.5000 |
| gate_return_scale | 0.2000 |
| gate_vol_window | 400 |

## Full sample

| key | value |
| --- | --- |
| bars | 48995 |
| gross_return | 1.3077 |
| net_return | 0.9230 |
| annualized_sharpe | 0.8390 |
| annualized_sharpe_gross | 1.0514 |
| max_drawdown | -0.3331 |
| average_absolute_exposure | 0.4258 |
| turnover_units | 241.3 |
| nonzero_target_bars | 48994 |
| hit_rate | 0.5100 |
| cost_share_of_gross | 0.2022 |

## Walk-forward (out of sample)

| key | value |
| --- | --- |
| folds | 5 |
| oos_sharpe | 0.5846 |
| oos_return | 0.4918 |
| oos_max_drawdown | -0.3331 |
| fold_sharpes | -0.3974, -0.0428, 1.5009, 1.1277, 0.7852 |
| fold_consistency | 0.6000 |

## CPCV

| key | value |
| --- | --- |
| paths | 15 |
| oos_sharpe_mean | 0.8479 |
| oos_sharpe_q05 | -0.5454 |
| oos_sharpe_min | -0.6481 |
| fraction_negative | 0.2667 |

## Multiple testing

| key | value |
| --- | --- |
| n_trials | 44 |
| grid_trials | 1 |
| prior_trials | 39 |
| sharpe_variance_period | 0.0000 |
| candidate_sharpe_annual | 0.8390 |
| expected_max_sharpe_annual | 0.8990 |
| dsr | 0.4436 |
| dsr_p_value | 0.5564 |
| pbo | n/a |
| pbo_combinations | n/a |
| degradation_slope | n/a |
| prob_oos_loss | n/a |
| ledger_trials | 4 |

## Stability

| key | value |
| --- | --- |
| time_split_sharpes | -0.4549, 1.2258, 0.7785, 0.8101 |
| worst_neighbour_degradation | 0.0170 |

## Cost stress (Sharpe)

| key | value |
| --- | --- |
| x1 | 0.8385 |
| x1.5 | 0.7400 |
| x2 | 0.6415 |

## Verdict

| key | value |
| --- | --- |
| verdict | FAIL |
| reasons | dsr_p_value 0.5564450348245358 > 0.1 |
