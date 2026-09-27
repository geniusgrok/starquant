# Validation: tsmom — PASS

## Range

| key | value |
| --- | --- |
| start | 2021-01-31 01:00:00+00:00 |
| end | 2026-09-05 16:00:00+00:00 |
| bars | 49048 |

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
| bars | 49048 |
| gross_return | 24.8469 |
| net_return | 18.8984 |
| annualized_sharpe | 1.8177 |
| annualized_sharpe_gross | 1.9625 |
| max_drawdown | -0.2368 |
| average_absolute_exposure | 0.8601 |
| turnover_units | 374.8 |
| nonzero_target_bars | 49048 |
| hit_rate | 0.5124 |
| cost_share_of_gross | 0.0738 |

## Walk-forward (out of sample)

| key | value |
| --- | --- |
| folds | 5 |
| oos_sharpe | 1.7662 |
| oos_return | 13.2489 |
| oos_max_drawdown | -0.2368 |
| oos_bars | 45048 |
| oos_t_stat | 4.0546 |
| oos_t_lags | 15 |
| fold_sharpes | 1.7407, 0.6016, 2.5582, 1.3244, 2.5553 |
| fold_consistency | 1.0000 |

## CPCV

| key | value |
| --- | --- |
| paths | 15 |
| oos_sharpe_mean | 1.7942 |
| oos_sharpe_q05 | 1.4181 |
| oos_sharpe_min | 1.2500 |
| fraction_negative | 0.0000 |

## Multiple testing

| key | value |
| --- | --- |
| n_trials | 125 |
| grid_trials | 2 |
| prior_trials | 60 |
| sharpe_variance_period | 0.0000 |
| candidate_sharpe_annual | 1.8177 |
| expected_max_sharpe_annual | 1.5841 |
| dsr | 0.7107 |
| dsr_p_value | 0.2893 |
| pbo | 0.2186 |
| pbo_combinations | 5000 |
| degradation_slope | -0.9775 |
| prob_oos_loss | 0.0000 |
| noise_null | sharpe_variance_period=0.0000; expected_max_sharpe_annual=1.0971; dsr_p_value=0.0433 |
| ledger_trials | 63 |

## Selection-deflated OOS threshold (D-028)

| key | value |
| --- | --- |
| n_obs | 45048 |
| n_trials | 125 |
| variance | 0.0000 |
| threshold_annual | 1.1446 |
| oos_sharpe_annual | 1.7662 |

## Stability

| key | value |
| --- | --- |
| time_split_sharpes | 1.5540, 1.4839, 1.8885, 2.1388 |
| worst_neighbour_degradation | 0.1138 |
| parameter_neighbourhood | entry_threshold=down=1.67 base=1.82 up=1.61; return_scale=down=1.72 base=1.82 up=1.76; vol_window=down=1.82 base=1.82 up=1.82 |

## Grid (full-sample Sharpe per configuration)

- crowding_window=72: sharpe=1.82
- crowding_window=0: sharpe=1.71

## Cost stress (Sharpe)

| key | value |
| --- | --- |
| x1 | 1.8176 |
| x1.5 | 1.7448 |
| x2 | 1.6720 |

## Verdict

| key | value |
| --- | --- |
| verdict | PASS |
| reasons | - |
