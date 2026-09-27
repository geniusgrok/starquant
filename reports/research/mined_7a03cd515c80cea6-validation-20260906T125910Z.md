# Validation: mined_7a03cd515c80cea6 — FAIL

## Range

| key | value |
| --- | --- |
| start | 2021-02-01 00:00:00+00:00 |
| end | 2026-09-03 00:00:00+00:00 |
| bars | 2041 |

## Holdout (KILL-006)

| key | value |
| --- | --- |
| months | 0 |
| note | no tail reserved: every bar was available to this run |

## Best params (full sample)

| key | value |
| --- | --- |
| entry_threshold | 0.2000 |
| expression | cs_rank(rz(ret(7), 7)) |
| hash | 7a03cd515c80cea6 |

## Full sample

| key | value |
| --- | --- |
| bars | 2041 |
| gross_return | 5.7607 |
| net_return | 1.4937 |
| annualized_sharpe | 0.7316 |
| annualized_sharpe_gross | 1.3799 |
| max_drawdown | -0.3519 |
| average_absolute_exposure | 1.2312 |
| turnover_units | 1310.7 |
| nonzero_target_bars | 1976 |
| hit_rate | 0.4899 |
| cost_share_of_gross | 0.4708 |

## Walk-forward (out of sample)

| key | value |
| --- | --- |
| folds | 5 |
| oos_sharpe | 0.7082 |
| oos_return | 1.2391 |
| oos_max_drawdown | -0.3519 |
| oos_bars | 1874 |
| oos_t_stat | 1.5445 |
| oos_t_lags | 7 |
| fold_sharpes | 0.8261, -0.0742, 1.2778, -0.4132, 1.8424 |
| fold_consistency | 0.6000 |

## CPCV

| key | value |
| --- | --- |
| paths | 15 |
| oos_sharpe_mean | 0.7261 |
| oos_sharpe_q05 | -0.1069 |
| oos_sharpe_min | -0.4427 |
| fraction_negative | 0.0667 |

## Multiple testing

| key | value |
| --- | --- |
| n_trials | 239 |
| grid_trials | 1 |
| prior_trials | 238 |
| sharpe_variance_period | 0.0000 |
| candidate_sharpe_annual | 0.7316 |
| expected_max_sharpe_annual | 0.0000 |
| dsr | 0.9607 |
| dsr_p_value | 0.0393 |
| pbo | n/a |
| pbo_combinations | n/a |
| degradation_slope | n/a |
| prob_oos_loss | n/a |
| noise_null | sharpe_variance_period=0.0005; expected_max_sharpe_annual=1.1743; dsr_p_value=0.8564 |
| ledger_trials | 0 |

## Selection-deflated OOS threshold (D-028)

| key | value |
| --- | --- |
| n_obs | 1874 |
| n_trials | 239 |
| variance | 0.0005 |
| threshold_annual | 1.2286 |
| oos_sharpe_annual | 0.7082 |

## Stability

| key | value |
| --- | --- |
| time_split_sharpes | 1.4860, -0.7371, 0.7154, 1.2769 |
| worst_neighbour_degradation | 0.0064 |
| parameter_neighbourhood | entry_threshold=down=0.82 base=0.73 up=0.73 |

## Grid (full-sample Sharpe per configuration)

- single configuration: sharpe=0.73

## Cost stress (Sharpe)

| key | value |
| --- | --- |
| x1 | 0.7317 |
| x1.5 | 0.4327 |
| x2 | 0.1337 |

## Verdict

| key | value |
| --- | --- |
| verdict | FAIL |
| reasons | oos_sharpe 0.71 < the deflated threshold 1.23 at 239 trials |
