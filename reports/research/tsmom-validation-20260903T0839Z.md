# Validation: tsmom — FAIL

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
| return_weight | 0.4000 |
| slope_weight | 0.2500 |
| persistence_weight | 0.1000 |
| return_scale | 0.2000 |
| slope_scale | 0.0100 |
| entry_threshold | 0.2000 |
| vol_window | 400 |
| crowding_window | 72 |
| crowding_cut | 0.7000 |
| crowding_penalty | 0.5000 |

## Full sample

| key | value |
| --- | --- |
| bars | 45364 |
| gross_return | 3.3423 |
| net_return | 2.4201 |
| annualized_sharpe | 1.5872 |
| annualized_sharpe_gross | 1.8801 |
| max_drawdown | -0.1230 |
| average_absolute_exposure | 0.4272 |
| turnover_units | 316.2 |
| nonzero_target_bars | 45364 |
| hit_rate | 0.5096 |
| cost_share_of_gross | 0.1558 |

## Walk-forward (out of sample)

| key | value |
| --- | --- |
| folds | 5 |
| oos_sharpe | 1.6056 |
| oos_return | 1.7915 |
| oos_max_drawdown | -0.1056 |
| fold_sharpes | 1.1425, 2.1130, 1.9922, 0.9179, 1.8368 |
| fold_consistency | 1.0000 |

## CPCV

| key | value |
| --- | --- |
| paths | 15 |
| oos_sharpe_mean | 1.5274 |
| oos_sharpe_q05 | 1.1438 |
| oos_sharpe_min | 0.9806 |
| fraction_negative | 0.0000 |

## Multiple testing

| key | value |
| --- | --- |
| n_trials | 18 |
| grid_trials | 2 |
| prior_trials | 16 |
| candidate_sharpe_annual | 1.5872 |
| expected_max_sharpe_annual | 0.0450 |
| dsr | 0.9998 |
| dsr_p_value | 0.0002 |
| pbo | 0.6716 |
| pbo_combinations | 5000 |
| degradation_slope | -0.9902 |
| prob_oos_loss | 0.0000 |

## Stability

| key | value |
| --- | --- |
| time_split_sharpes | 1.3338, 2.0652, 1.4026, 1.6063 |
| worst_neighbour_degradation | 0.0732 |

## Cost stress (Sharpe)

| key | value |
| --- | --- |
| x1 | 1.5880 |
| x1.5 | 1.4521 |
| x2 | 1.3161 |

## Verdict

| key | value |
| --- | --- |
| verdict | FAIL |
| reasons | pbo 0.67 > 0.3 |
