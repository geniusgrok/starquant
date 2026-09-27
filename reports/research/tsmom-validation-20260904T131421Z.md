# Validation: tsmom — PASS

## Range

| key | value |
| --- | --- |
| start | 2021-01-31 01:00:00+00:00 |
| end | 2026-09-04 06:00:00+00:00 |
| bars | 49014 |

## Holdout (KILL-006)

| key | value |
| --- | --- |
| months | 0 |
| note | no tail reserved: every bar was available to this run |

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
| conviction_mode | sign |

## Full sample

| key | value |
| --- | --- |
| bars | 49014 |
| gross_return | 4.1634 |
| net_return | 3.3659 |
| annualized_sharpe | 1.6972 |
| annualized_sharpe_gross | 1.8811 |
| max_drawdown | -0.1190 |
| average_absolute_exposure | 0.4567 |
| turnover_units | 225.6 |
| nonzero_target_bars | 49014 |
| hit_rate | 0.5131 |
| cost_share_of_gross | 0.0978 |

## Walk-forward (out of sample)

| key | value |
| --- | --- |
| folds | 5 |
| oos_sharpe | 1.6496 |
| oos_return | 2.7268 |
| oos_max_drawdown | -0.1190 |
| oos_bars | 45014 |
| oos_t_stat | 3.7846 |
| oos_t_lags | 15 |
| fold_sharpes | 1.4163, 0.7925, 2.3267, 1.0704, 2.6298 |
| fold_consistency | 1.0000 |

## CPCV

| key | value |
| --- | --- |
| paths | 15 |
| oos_sharpe_mean | 1.6984 |
| oos_sharpe_q05 | 1.3889 |
| oos_sharpe_min | 1.3604 |
| fraction_negative | 0.0000 |

## Multiple testing

| key | value |
| --- | --- |
| n_trials | 91 |
| grid_trials | 1 |
| prior_trials | 30 |
| sharpe_variance_period | 0.0000 |
| candidate_sharpe_annual | 1.6972 |
| expected_max_sharpe_annual | 1.4581 |
| dsr | 0.7148 |
| dsr_p_value | 0.2852 |
| pbo | n/a |
| pbo_combinations | n/a |
| degradation_slope | n/a |
| prob_oos_loss | n/a |
| noise_null | sharpe_variance_period=0.0000; expected_max_sharpe_annual=1.0518; dsr_p_value=0.0627 |
| ledger_trials | 60 |

## Selection-deflated OOS threshold (D-028)

| key | value |
| --- | --- |
| n_obs | 45014 |
| n_trials | 91 |
| variance | 0.0000 |
| threshold_annual | 1.0972 |
| oos_sharpe_annual | 1.6496 |

## Stability

| key | value |
| --- | --- |
| time_split_sharpes | 1.4295, 1.3084, 1.7296, 2.1282 |
| worst_neighbour_degradation | 0.0800 |
| parameter_neighbourhood | entry_threshold=down=1.64 base=1.70 up=1.56; return_scale=down=1.70 base=1.70 up=1.62; vol_window=down=1.70 base=1.70 up=1.70 |

## Grid (full-sample Sharpe per configuration)

- single configuration: sharpe=1.70

## Cost stress (Sharpe)

| key | value |
| --- | --- |
| x1 | 1.6969 |
| x1.5 | 1.6102 |
| x2 | 1.5234 |

## Verdict

| key | value |
| --- | --- |
| verdict | PASS |
| reasons | - |
