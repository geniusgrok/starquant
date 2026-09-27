# Validation: xsmom — FAIL

## Range

| key | value |
| --- | --- |
| start | 2021-07-02 01:00:00+00:00 |
| end | 2026-09-03 04:00:00+00:00 |
| bars | 45340 |

## Best params (full sample)

| key | value |
| --- | --- |
| horizons | 168, 336, 720 |
| horizon_weights | 0.2000, 0.3000, 0.5000 |
| skip_bars | 0 |
| risk_adjusted | no |
| score_scale | 0.1500 |
| z_scale | 1.5000 |
| vol_window | 336 |
| relative_weight | 0.7500 |
| rank_weight | 0.2500 |
| entry_threshold | 0.3000 |
| min_symbols | 3 |

## Full sample

| key | value |
| --- | --- |
| bars | 45364 |
| gross_return | 0.9362 |
| net_return | 0.6506 |
| annualized_sharpe | 0.6971 |
| annualized_sharpe_gross | 0.8943 |
| max_drawdown | -0.1596 |
| average_absolute_exposure | 0.7373 |
| turnover_units | 276.6 |
| nonzero_target_bars | 45364 |
| hit_rate | 0.5002 |
| cost_share_of_gross | 0.2204 |

## Walk-forward (out of sample)

| key | value |
| --- | --- |
| folds | 5 |
| oos_sharpe | 0.5105 |
| oos_return | 0.3327 |
| oos_max_drawdown | -0.2767 |
| fold_sharpes | 1.6566, 0.1688, 0.4108, 1.6106, -1.2344 |
| fold_consistency | 0.8000 |

## CPCV

| key | value |
| --- | --- |
| paths | 15 |
| oos_sharpe_mean | 0.5442 |
| oos_sharpe_q05 | -0.5944 |
| oos_sharpe_min | -0.6426 |
| fraction_negative | 0.2000 |

## Multiple testing

| key | value |
| --- | --- |
| n_trials | 2 |
| candidate_sharpe_annual | 0.6999 |
| expected_max_sharpe_annual | 0.0628 |
| dsr | 0.9266 |
| dsr_p_value | 0.0734 |
| pbo | 0.4104 |
| pbo_combinations | 5000 |
| degradation_slope | -1.0291 |
| prob_oos_loss | 0.0524 |

## Stability

| key | value |
| --- | --- |
| time_split_sharpes | 0.8179, 0.5033, 0.9086, -0.1486 |
| worst_neighbour_degradation | 0.0502 |

## Cost stress (Sharpe)

| key | value |
| --- | --- |
| x1 | 0.6991 |
| x1.5 | 0.5795 |
| x2 | 0.4598 |

## Verdict

| key | value |
| --- | --- |
| verdict | FAIL |
| reasons | pbo 0.41 > 0.3 |
