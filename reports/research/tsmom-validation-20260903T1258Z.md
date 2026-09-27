# Validation: tsmom — PASS

## Range

| key | value |
| --- | --- |
| start | 2021-01-31 01:00:00+00:00 |
| end | 2026-09-03 11:00:00+00:00 |
| bars | 48995 |

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
| bars | 48995 |
| gross_return | 4.5899 |
| net_return | 3.3083 |
| annualized_sharpe | 1.7407 |
| annualized_sharpe_gross | 2.0372 |
| max_drawdown | -0.1185 |
| average_absolute_exposure | 0.4085 |
| turnover_units | 329.5 |
| nonzero_target_bars | 48995 |
| hit_rate | 0.5124 |
| cost_share_of_gross | 0.1455 |

## Walk-forward (out of sample)

| key | value |
| --- | --- |
| folds | 5 |
| oos_sharpe | 1.5243 |
| oos_return | 2.2216 |
| oos_max_drawdown | -0.1185 |
| fold_sharpes | 1.4332, 0.8207, 2.3668, 1.1103, 1.8278 |
| fold_consistency | 1.0000 |

## CPCV

| key | value |
| --- | --- |
| paths | 15 |
| oos_sharpe_mean | 1.7418 |
| oos_sharpe_q05 | 1.1710 |
| oos_sharpe_min | 1.1368 |
| fraction_negative | 0.0000 |

## Multiple testing

| key | value |
| --- | --- |
| n_trials | 46 |
| grid_trials | 1 |
| prior_trials | 43 |
| sharpe_variance_period | 0.0000 |
| candidate_sharpe_annual | 1.7407 |
| expected_max_sharpe_annual | 0.2245 |
| dsr | 0.9998 |
| dsr_p_value | 0.0002 |
| pbo | n/a |
| pbo_combinations | n/a |
| degradation_slope | n/a |
| prob_oos_loss | n/a |
| ledger_trials | 2 |

## Stability

| key | value |
| --- | --- |
| time_split_sharpes | 1.3405, 1.5005, 1.6262, 1.6260 |
| worst_neighbour_degradation | 0.0541 |

## Cost stress (Sharpe)

| key | value |
| --- | --- |
| x1 | 1.7406 |
| x1.5 | 1.6092 |
| x2 | 1.4778 |

## Verdict

| key | value |
| --- | --- |
| verdict | PASS |
| reasons | - |
