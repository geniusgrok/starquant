# Validation: tsmom — FAIL

## Range

| key | value |
| --- | --- |
| start | 2021-03-02 01:00:00+00:00 |
| end | 2026-09-03 11:00:00+00:00 |
| bars | 48275 |

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
| gross_return | 4.0116 |
| net_return | 2.9067 |
| annualized_sharpe | 1.6411 |
| annualized_sharpe_gross | 1.9269 |
| max_drawdown | -0.1261 |
| average_absolute_exposure | 0.3938 |
| turnover_units | 367.3 |
| nonzero_target_bars | 48995 |
| hit_rate | 0.5092 |
| cost_share_of_gross | 0.1483 |

## Walk-forward (out of sample)

| key | value |
| --- | --- |
| folds | 5 |
| oos_sharpe | 1.4798 |
| oos_return | 2.0105 |
| oos_max_drawdown | -0.1261 |
| fold_sharpes | 1.1371, 0.7398, 1.6766, 1.9436, 1.9367 |
| fold_consistency | 1.0000 |

## CPCV

| key | value |
| --- | --- |
| paths | 15 |
| oos_sharpe_mean | 1.5838 |
| oos_sharpe_q05 | 1.0933 |
| oos_sharpe_min | 0.9514 |
| fraction_negative | 0.0000 |

## Multiple testing

| key | value |
| --- | --- |
| n_trials | 49 |
| grid_trials | 16 |
| prior_trials | 27 |
| sharpe_variance_period | 0.0000 |
| candidate_sharpe_annual | 1.5823 |
| expected_max_sharpe_annual | 1.4771 |
| dsr | 0.5980 |
| dsr_p_value | 0.4020 |
| pbo | 0.0008 |
| pbo_combinations | 5000 |
| degradation_slope | -1.0274 |
| prob_oos_loss | 0.0008 |
| ledger_trials | 6 |

## Stability

| key | value |
| --- | --- |
| time_split_sharpes | 0.9568, 1.6641, 1.4604, 1.8680 |
| worst_neighbour_degradation | 0.0864 |

## Cost stress (Sharpe)

| key | value |
| --- | --- |
| x1 | 1.6410 |
| x1.5 | 1.4933 |
| x2 | 1.3457 |

## Verdict

| key | value |
| --- | --- |
| verdict | FAIL |
| reasons | dsr_p_value 0.40203577447966143 > 0.1 |
