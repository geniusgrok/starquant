# Validation: tsmom — PASS

## Range

| key | value |
| --- | --- |
| start | 2021-07-31 01:00:00+00:00 |
| end | 2026-09-03 04:00:00+00:00 |
| bars | 44644 |

## Best params (full sample)

| key | value |
| --- | --- |
| horizons | 168, 336, 720 |
| horizon_weights | 0.2000, 0.3000, 0.5000 |
| return_weight | 0.4000 |
| slope_weight | 0.2500 |
| persistence_weight | 0.1000 |
| return_scale | 0.2000 |
| slope_scale | 0.0100 |
| entry_threshold | 0.2000 |
| vol_window | 400 |

## Full sample

| key | value |
| --- | --- |
| bars | 45364 |
| gross_return | 3.2744 |
| net_return | 2.3471 |
| annualized_sharpe | 1.5528 |
| annualized_sharpe_gross | 1.8513 |
| max_drawdown | -0.1313 |
| average_absolute_exposure | 0.4129 |
| turnover_units | 310.5 |
| nonzero_target_bars | 45364 |
| hit_rate | 0.5098 |
| cost_share_of_gross | 0.1612 |

## Walk-forward (out of sample)

| key | value |
| --- | --- |
| folds | 5 |
| oos_sharpe | 1.3760 |
| oos_return | 1.3745 |
| oos_max_drawdown | -0.1150 |
| fold_sharpes | 0.1795, 2.3386, 1.2497, 1.0530, 2.0371 |
| fold_consistency | 1.0000 |

## CPCV

| key | value |
| --- | --- |
| paths | 15 |
| oos_sharpe_mean | 1.5002 |
| oos_sharpe_q05 | 1.1965 |
| oos_sharpe_min | 1.1660 |
| fraction_negative | 0.0000 |

## Multiple testing

| key | value |
| --- | --- |
| n_trials | 16 |
| candidate_sharpe_annual | 1.5556 |
| expected_max_sharpe_annual | 0.8100 |
| dsr | 0.9547 |
| dsr_p_value | 0.0453 |
| pbo | 0.0374 |
| pbo_combinations | 5000 |
| degradation_slope | -0.8027 |
| prob_oos_loss | 0.0074 |

## Stability

| key | value |
| --- | --- |
| time_split_sharpes | 0.4094, 2.0865, 1.1998, 1.7903 |
| worst_neighbour_degradation | 0.0495 |

## Cost stress (Sharpe)

| key | value |
| --- | --- |
| x1 | 1.5537 |
| x1.5 | 1.4209 |
| x2 | 1.2882 |

## Verdict

| key | value |
| --- | --- |
| verdict | PASS |
| reasons | - |
