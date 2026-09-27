# Validation: tsmom — PASS

## Range

| key | value |
| --- | --- |
| start | 2021-01-31 01:00:00+00:00 |
| end | 2026-09-04 16:00:00+00:00 |
| bars | 49024 |

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
| crowding_window | 72 |
| crowding_cut | 0.7000 |
| crowding_penalty | 0.5000 |
| momentum_mode | fixed |
| conviction_mode | sign |

## Full sample

| key | value |
| --- | --- |
| bars | 49024 |
| gross_return | 25.1237 |
| net_return | 19.1414 |
| annualized_sharpe | 1.8261 |
| annualized_sharpe_gross | 1.9702 |
| max_drawdown | -0.2219 |
| average_absolute_exposure | 0.8594 |
| turnover_units | 384.3 |
| nonzero_target_bars | 49024 |
| hit_rate | 0.5130 |
| cost_share_of_gross | 0.0732 |

## Walk-forward (out of sample)

| key | value |
| --- | --- |
| folds | 5 |
| oos_sharpe | 1.7647 |
| oos_return | 13.1996 |
| oos_max_drawdown | -0.2219 |
| oos_bars | 45024 |
| oos_t_stat | 4.0266 |
| oos_t_lags | 15 |
| fold_sharpes | 1.6264, 0.9046, 2.5890, 1.1014, 2.5593 |
| fold_consistency | 1.0000 |

## CPCV

| key | value |
| --- | --- |
| paths | 15 |
| oos_sharpe_mean | 1.7947 |
| oos_sharpe_q05 | 1.3378 |
| oos_sharpe_min | 1.1358 |
| fraction_negative | 0.0000 |

## Multiple testing

| key | value |
| --- | --- |
| n_trials | 93 |
| grid_trials | 2 |
| prior_trials | 30 |
| sharpe_variance_period | 0.0000 |
| candidate_sharpe_annual | 1.8261 |
| expected_max_sharpe_annual | 1.4950 |
| dsr | 0.7845 |
| dsr_p_value | 0.2155 |
| pbo | 0.1360 |
| pbo_combinations | 5000 |
| degradation_slope | -1.0022 |
| prob_oos_loss | 0.0000 |
| noise_null | sharpe_variance_period=0.0000; expected_max_sharpe_annual=1.0529; dsr_p_value=0.0329 |
| ledger_trials | 61 |

## Selection-deflated OOS threshold (D-028)

| key | value |
| --- | --- |
| n_obs | 45024 |
| n_trials | 93 |
| variance | 0.0000 |
| threshold_annual | 1.0981 |
| oos_sharpe_annual | 1.7647 |

## Stability

| key | value |
| --- | --- |
| time_split_sharpes | 1.5587, 1.6292, 1.8523, 2.0174 |
| worst_neighbour_degradation | 0.1080 |
| parameter_neighbourhood | entry_threshold=down=1.69 base=1.83 up=1.63; return_scale=down=1.79 base=1.83 up=1.78; vol_window=down=1.83 base=1.83 up=1.83 |

## Grid (full-sample Sharpe per configuration)

- crowding_window=72: sharpe=1.83
- crowding_window=0: sharpe=1.70

## Cost stress (Sharpe)

| key | value |
| --- | --- |
| x1 | 1.8259 |
| x1.5 | 1.7512 |
| x2 | 1.6764 |

## Verdict

| key | value |
| --- | --- |
| verdict | PASS |
| reasons | - |
