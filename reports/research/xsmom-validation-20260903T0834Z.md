# Validation: xsmom — FAIL

## Range

| key | value |
| --- | --- |
| start | 2021-07-03 01:00:00+00:00 |
| end | 2026-09-03 04:00:00+00:00 |
| bars | 45316 |

## Best params (full sample)

| key | value |
| --- | --- |
| horizons | 168, 336, 720 |
| horizon_weights | 0.2000, 0.3000, 0.5000 |
| skip_bars | 24 |
| risk_adjusted | yes |
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
| bars | 45340 |
| gross_return | 0.5321 |
| net_return | 0.3484 |
| annualized_sharpe | 0.4499 |
| annualized_sharpe_gross | 0.6090 |
| max_drawdown | -0.2038 |
| average_absolute_exposure | 0.7461 |
| turnover_units | 237.4 |
| nonzero_target_bars | 45340 |
| hit_rate | 0.5008 |
| cost_share_of_gross | 0.2612 |

## Walk-forward (out of sample)

| key | value |
| --- | --- |
| folds | 5 |
| oos_sharpe | 0.1951 |
| oos_return | 0.0805 |
| oos_max_drawdown | -0.2639 |
| fold_sharpes | 1.5103, -0.5507, 0.2223, 1.0130, -1.1593 |
| fold_consistency | 0.6000 |

## CPCV

| key | value |
| --- | --- |
| paths | 15 |
| oos_sharpe_mean | 0.2879 |
| oos_sharpe_q05 | -0.5067 |
| oos_sharpe_min | -0.5679 |
| fraction_negative | 0.3333 |

## Multiple testing

| key | value |
| --- | --- |
| n_trials | 8 |
| candidate_sharpe_annual | 0.4479 |
| expected_max_sharpe_annual | 0.2307 |
| dsr | 0.6894 |
| dsr_p_value | 0.3106 |
| pbo | 0.2340 |
| pbo_combinations | 5000 |
| degradation_slope | -0.9484 |
| prob_oos_loss | 0.2138 |

## Stability

| key | value |
| --- | --- |
| time_split_sharpes | 0.8644, -0.1324, 0.4839, -0.3689 |
| worst_neighbour_degradation | 0.4604 |

## Cost stress (Sharpe)

| key | value |
| --- | --- |
| x1 | 0.4487 |
| x1.5 | 0.3452 |
| x2 | 0.2416 |

## Verdict

| key | value |
| --- | --- |
| verdict | FAIL |
| reasons | oos_sharpe 0.20 < 0.5, dsr_p_value 0.31057791308619775 > 0.1 |
