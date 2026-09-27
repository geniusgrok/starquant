# Validation: residual — FAIL

## Range

| key | value |
| --- | --- |
| start | 2021-07-01 01:00:00+00:00 |
| end | 2026-09-03 04:00:00+00:00 |
| bars | 45364 |

## Best params (full sample)

| key | value |
| --- | --- |
| horizons | 24, 72, 168 |
| beta_window | 336 |
| scale | 0.1000 |
| benchmark | BTCUSDT |
| entry_threshold | 0.2000 |

## Full sample

| key | value |
| --- | --- |
| bars | 45365 |
| gross_return | 2.6520 |
| net_return | 0.8655 |
| annualized_sharpe | 0.8255 |
| annualized_sharpe_gross | 1.6282 |
| max_drawdown | -0.2271 |
| average_absolute_exposure | 0.4512 |
| turnover_units | 955.8 |
| nonzero_target_bars | 45365 |
| hit_rate | 0.4984 |
| cost_share_of_gross | 0.4929 |

## Walk-forward (out of sample)

| key | value |
| --- | --- |
| folds | 5 |
| oos_sharpe | 0.7811 |
| oos_return | 0.6010 |
| oos_max_drawdown | -0.2902 |
| fold_sharpes | 1.5672, -1.0545, 1.8083, 0.9365, 0.6070 |
| fold_consistency | 0.8000 |

## CPCV

| key | value |
| --- | --- |
| paths | 15 |
| oos_sharpe_mean | 0.5028 |
| oos_sharpe_q05 | -0.5044 |
| oos_sharpe_min | -0.8702 |
| fraction_negative | 0.2000 |

## Multiple testing

| key | value |
| --- | --- |
| n_trials | 8 |
| candidate_sharpe_annual | 0.8276 |
| expected_max_sharpe_annual | 0.3861 |
| dsr | 0.8435 |
| dsr_p_value | 0.1565 |
| pbo | 0.3938 |
| pbo_combinations | 5000 |
| degradation_slope | -0.9510 |
| prob_oos_loss | 0.0858 |

## Stability

| key | value |
| --- | --- |
| time_split_sharpes | 1.4278, -0.4640, 0.9549, 1.2403 |
| worst_neighbour_degradation | 0.0518 |

## Cost stress (Sharpe)

| key | value |
| --- | --- |
| x1 | 0.8275 |
| x1.5 | 0.4278 |
| x2 | 0.0283 |

## Verdict

| key | value |
| --- | --- |
| verdict | FAIL |
| reasons | dsr_p_value 0.15651712470971257 > 0.1, pbo 0.39 > 0.3 |
