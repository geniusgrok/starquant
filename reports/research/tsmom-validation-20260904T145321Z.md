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
| gross_return | 20.7308 |
| net_return | 15.1741 |
| annualized_sharpe | 1.7085 |
| annualized_sharpe_gross | 1.8726 |
| max_drawdown | -0.2427 |
| average_absolute_exposure | 0.8545 |
| turnover_units | 394.3 |
| nonzero_target_bars | 49014 |
| hit_rate | 0.5128 |
| cost_share_of_gross | 0.0877 |

## Walk-forward (out of sample)

| key | value |
| --- | --- |
| folds | 5 |
| oos_sharpe | 1.6574 |
| oos_return | 10.8229 |
| oos_max_drawdown | -0.2427 |
| oos_bars | 45014 |
| oos_t_stat | 3.7935 |
| oos_t_lags | 15 |
| fold_sharpes | 1.4459, 0.5038, 2.5117, 1.0976, 2.6953 |
| fold_consistency | 1.0000 |

## CPCV

| key | value |
| --- | --- |
| paths | 15 |
| oos_sharpe_mean | 1.7093 |
| oos_sharpe_q05 | 1.3475 |
| oos_sharpe_min | 1.3445 |
| fraction_negative | 0.0000 |

## Multiple testing

| key | value |
| --- | --- |
| n_trials | 91 |
| grid_trials | 1 |
| prior_trials | 30 |
| sharpe_variance_period | 0.0000 |
| candidate_sharpe_annual | 1.7085 |
| expected_max_sharpe_annual | 1.4588 |
| dsr | 0.7233 |
| dsr_p_value | 0.2767 |
| pbo | n/a |
| pbo_combinations | n/a |
| degradation_slope | n/a |
| prob_oos_loss | n/a |
| noise_null | sharpe_variance_period=0.0000; expected_max_sharpe_annual=1.0519; dsr_p_value=0.0595 |
| ledger_trials | 60 |

## Selection-deflated OOS threshold (D-028)

| key | value |
| --- | --- |
| n_obs | 45014 |
| n_trials | 91 |
| variance | 0.0000 |
| threshold_annual | 1.0973 |
| oos_sharpe_annual | 1.6574 |

## Stability

| key | value |
| --- | --- |
| time_split_sharpes | 1.4294, 1.2078, 1.8497, 2.1360 |
| worst_neighbour_degradation | 0.0801 |
| parameter_neighbourhood | entry_threshold=down=1.66 base=1.71 up=1.57; return_scale=down=1.71 base=1.71 up=1.65; vol_window=down=1.71 base=1.71 up=1.71 |

## Grid (full-sample Sharpe per configuration)

- single configuration: sharpe=1.71

## Cost stress (Sharpe)

| key | value |
| --- | --- |
| x1 | 1.7082 |
| x1.5 | 1.6313 |
| x2 | 1.5544 |

## Verdict

| key | value |
| --- | --- |
| verdict | PASS |
| reasons | - |
