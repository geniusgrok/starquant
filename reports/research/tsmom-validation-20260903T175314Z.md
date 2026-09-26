# Validation: tsmom — FAIL

## Range

| key | value |
| --- | --- |
| start | 2021-08-30 01:00:00+00:00 |
| end | 2026-09-03 11:00:00+00:00 |
| bars | 43931 |

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
| crowding_window | 0 |
| crowding_cut | 0.7000 |
| crowding_penalty | 0.5000 |
| momentum_mode | fixed |

## Full sample

| key | value |
| --- | --- |
| bars | 44651 |
| gross_return | 3.2272 |
| net_return | 2.3160 |
| annualized_sharpe | 1.5627 |
| annualized_sharpe_gross | 1.8633 |
| max_drawdown | -0.1264 |
| average_absolute_exposure | 0.4162 |
| turnover_units | 307.8 |
| nonzero_target_bars | 44651 |
| hit_rate | 0.5096 |
| cost_share_of_gross | 0.1613 |

## Walk-forward (out of sample)

| key | value |
| --- | --- |
| folds | 5 |
| oos_sharpe | 1.2094 |
| oos_return | 1.0877 |
| oos_max_drawdown | -0.1573 |
| fold_sharpes | -0.9864, 2.3292, 1.0060, 1.7511, 1.8529 |
| fold_consistency | 0.8000 |

## CPCV

| key | value |
| --- | --- |
| paths | 15 |
| oos_sharpe_mean | 1.4541 |
| oos_sharpe_q05 | 0.8165 |
| oos_sharpe_min | 0.8153 |
| fraction_negative | 0.0000 |

## Multiple testing

| key | value |
| --- | --- |
| n_trials | 40 |
| grid_trials | 16 |
| prior_trials | 0 |
| sharpe_variance_period | 0.0000 |
| candidate_sharpe_annual | 1.4793 |
| expected_max_sharpe_annual | 1.2854 |
| dsr | 0.6688 |
| dsr_p_value | 0.3312 |
| pbo | 0.0888 |
| pbo_combinations | 5000 |
| degradation_slope | -0.6640 |
| prob_oos_loss | 0.0232 |
| ledger_trials | 24 |

## Stability

| key | value |
| --- | --- |
| time_split_sharpes | -0.7114, 2.4043, 0.8784, 2.1762 |
| worst_neighbour_degradation | 0.0607 |

## Cost stress (Sharpe)

| key | value |
| --- | --- |
| x1 | 1.5627 |
| x1.5 | 1.4292 |
| x2 | 1.2956 |

## Verdict

| key | value |
| --- | --- |
| verdict | FAIL |
| reasons | dsr_p_value 0.3312008048716484 > 0.1 |
