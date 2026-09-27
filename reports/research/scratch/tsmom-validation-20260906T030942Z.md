# Validation: tsmom — PASS

## Range

| key | value |
| --- | --- |
| start | 2021-03-02 01:00:00+00:00 |
| end | 2026-09-05 16:00:00+00:00 |
| bars | 48328 |

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
| gross_return | 25.4376 |
| net_return | 19.3815 |
| annualized_sharpe | 1.8321 |
| annualized_sharpe_gross | 1.9762 |
| max_drawdown | -0.2219 |
| average_absolute_exposure | 0.8593 |
| turnover_units | 384.3 |
| nonzero_target_bars | 49048 |
| hit_rate | 0.5130 |
| cost_share_of_gross | 0.0730 |

## Walk-forward (out of sample)

| key | value |
| --- | --- |
| folds | 5 |
| oos_sharpe | 1.4852 |
| oos_return | 7.6386 |
| oos_max_drawdown | -0.2077 |
| oos_bars | 44328 |
| oos_t_stat | 3.3434 |
| oos_t_lags | 15 |
| fold_sharpes | 1.1906, 0.0600, 2.3038, 1.2461, 2.5688 |
| fold_consistency | 1.0000 |

## CPCV

| key | value |
| --- | --- |
| paths | 15 |
| oos_sharpe_mean | 1.7869 |
| oos_sharpe_q05 | 1.2538 |
| oos_sharpe_min | 1.2075 |
| fraction_negative | 0.0000 |

## Multiple testing

| key | value |
| --- | --- |
| n_trials | 46 |
| grid_trials | 16 |
| prior_trials | 30 |
| sharpe_variance_period | 0.0000 |
| candidate_sharpe_annual | 1.7873 |
| expected_max_sharpe_annual | 1.0239 |
| dsr | 0.9644 |
| dsr_p_value | 0.0356 |
| pbo | 0.0072 |
| pbo_combinations | 5000 |
| degradation_slope | -0.9906 |
| prob_oos_loss | 0.0000 |
| noise_null | sharpe_variance_period=0.0000; expected_max_sharpe_annual=0.9497; dsr_p_value=0.0239 |
| ledger_trials | 0 |

## Selection-deflated OOS threshold (D-028)

| key | value |
| --- | --- |
| n_obs | 44328 |
| n_trials | 46 |
| variance | 0.0000 |
| threshold_annual | 0.9937 |
| oos_sharpe_annual | 1.4852 |

## Stability

| key | value |
| --- | --- |
| time_split_sharpes | 0.9893, 1.1135, 1.6244, 2.2164 |
| worst_neighbour_degradation | 0.1076 |
| parameter_neighbourhood | entry_threshold=down=1.69 base=1.83 up=1.64; return_scale=down=1.79 base=1.83 up=1.79; vol_window=down=1.83 base=1.83 up=1.83 |

## Grid (full-sample Sharpe per configuration)

- entry_threshold=0.2, horizons=[168, 336, 720], return_scale=0.2: sharpe=1.79
- entry_threshold=0.2, horizons=[168, 336, 720], return_scale=0.3: sharpe=1.52
- entry_threshold=0.3, horizons=[168, 336, 720], return_scale=0.2: sharpe=1.29
- entry_threshold=0.3, horizons=[24, 72, 168], return_scale=0.3: sharpe=1.19
- entry_threshold=0.3, horizons=[168, 336, 720], return_scale=0.3: sharpe=1.11
- entry_threshold=0.3, horizons=[24, 72, 168], return_scale=0.2: sharpe=1.02
- entry_threshold=0.2, horizons=[24, 72, 168], return_scale=0.2: sharpe=0.89
- entry_threshold=0.2, horizons=[24, 72, 168], return_scale=0.3: sharpe=0.83
- entry_threshold=0.3, horizons=[5, 20, 50], return_scale=0.3: sharpe=0.62
- entry_threshold=0.3, horizons=[5, 20, 50], return_scale=0.2: sharpe=0.53
- entry_threshold=0.2, horizons=[336, 720, 1440], return_scale=0.3: sharpe=0.47
- entry_threshold=0.2, horizons=[336, 720, 1440], return_scale=0.2: sharpe=0.41
- entry_threshold=0.3, horizons=[336, 720, 1440], return_scale=0.3: sharpe=0.40
- entry_threshold=0.2, horizons=[5, 20, 50], return_scale=0.3: sharpe=0.40
- entry_threshold=0.3, horizons=[336, 720, 1440], return_scale=0.2: sharpe=0.36
- entry_threshold=0.2, horizons=[5, 20, 50], return_scale=0.2: sharpe=0.33

## Cost stress (Sharpe)

| key | value |
| --- | --- |
| x1 | 1.8319 |
| x1.5 | 1.7572 |
| x2 | 1.6825 |

## Verdict

| key | value |
| --- | --- |
| verdict | PASS |
| reasons | - |
