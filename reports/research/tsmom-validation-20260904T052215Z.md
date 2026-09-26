# Validation: tsmom — PASS

## Range

| key | value |
| --- | --- |
| start | 2021-01-31 01:00:00+00:00 |
| end | 2026-09-04 04:00:00+00:00 |
| bars | 49012 |

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
| bars | 49012 |
| gross_return | 4.2156 |
| net_return | 3.4437 |
| annualized_sharpe | 1.7160 |
| annualized_sharpe_gross | 1.8917 |
| max_drawdown | -0.1211 |
| average_absolute_exposure | 0.4568 |
| turnover_units | 225.7 |
| nonzero_target_bars | 49012 |
| hit_rate | 0.5129 |
| cost_share_of_gross | 0.0928 |

## Walk-forward (out of sample)

| key | value |
| --- | --- |
| folds | 5 |
| oos_sharpe | 1.6436 |
| oos_return | 2.7092 |
| oos_max_drawdown | -0.1211 |
| oos_bars | 45012 |
| oos_t_stat | 3.7701 |
| oos_t_lags | 15 |
| fold_sharpes | 1.4749, 0.7828, 2.3177, 1.0500, 2.5755 |
| fold_consistency | 1.0000 |

## CPCV

| key | value |
| --- | --- |
| paths | 15 |
| oos_sharpe_mean | 1.7173 |
| oos_sharpe_q05 | 1.4122 |
| oos_sharpe_min | 1.3850 |
| fraction_negative | 0.0000 |

## Multiple testing

| key | value |
| --- | --- |
| n_trials | 90 |
| grid_trials | 1 |
| prior_trials | 30 |
| sharpe_variance_period | 0.0000 |
| candidate_sharpe_annual | 1.7160 |
| expected_max_sharpe_annual | 1.4417 |
| dsr | 0.7426 |
| dsr_p_value | 0.2574 |
| pbo | n/a |
| pbo_combinations | n/a |
| degradation_slope | n/a |
| prob_oos_loss | n/a |
| noise_null | sharpe_variance_period=0.0000; expected_max_sharpe_annual=1.0501; dsr_p_value=0.0569 |
| ledger_trials | 59 |

## Selection-deflated OOS threshold (D-028)

| key | value |
| --- | --- |
| n_obs | 45012 |
| n_trials | 90 |
| variance | 0.0000 |
| threshold_annual | 1.0955 |
| oos_sharpe_annual | 1.6436 |

## Stability

| key | value |
| --- | --- |
| time_split_sharpes | 1.4853, 1.2548, 1.7429, 2.0848 |
| worst_neighbour_degradation | 0.0815 |
| parameter_neighbourhood | entry_threshold=down=1.66 base=1.72 up=1.58; return_scale=down=1.72 base=1.72 up=1.64; vol_window=down=1.72 base=1.72 up=1.72 |

## Grid (full-sample Sharpe per configuration)

- single configuration: sharpe=1.72

## Cost stress (Sharpe)

| key | value |
| --- | --- |
| x1 | 1.7158 |
| x1.5 | 1.6290 |
| x2 | 1.5423 |

## Verdict

| key | value |
| --- | --- |
| verdict | PASS |
| reasons | - |
