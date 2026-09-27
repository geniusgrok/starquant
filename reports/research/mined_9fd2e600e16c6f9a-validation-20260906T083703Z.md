# Validation: mined_9fd2e600e16c6f9a — FAIL

## Range

| key | value |
| --- | --- |
| start | 2021-02-04 23:00:00+00:00 |
| end | 2026-09-05 16:00:00+00:00 |
| bars | 48930 |

## Holdout (KILL-006)

| key | value |
| --- | --- |
| months | 0 |
| note | no tail reserved: every bar was available to this run |

## Best params (full sample)

| key | value |
| --- | --- |
| entry_threshold | 0.2000 |
| expression | cs_rank(rz(ret(168), 336)) |
| hash | 9fd2e600e16c6f9a |

## Full sample

| key | value |
| --- | --- |
| bars | 48930 |
| gross_return | 15.7864 |
| net_return | 2.1385 |
| annualized_sharpe | 0.8360 |
| annualized_sharpe_gross | 1.8432 |
| max_drawdown | -0.5351 |
| average_absolute_exposure | 1.1404 |
| turnover_units | 2460.8 |
| nonzero_target_bars | 48930 |
| hit_rate | 0.4981 |
| cost_share_of_gross | 0.5464 |

## Walk-forward (out of sample)

| key | value |
| --- | --- |
| folds | 5 |
| oos_sharpe | 0.6253 |
| oos_return | 1.0684 |
| oos_max_drawdown | -0.5351 |
| oos_bars | 44930 |
| oos_t_stat | 1.3797 |
| oos_t_lags | 15 |
| fold_sharpes | 1.3476, 1.0594, 0.2521, -1.6741, 2.1628 |
| fold_consistency | 0.8000 |

## CPCV

| key | value |
| --- | --- |
| paths | 15 |
| oos_sharpe_mean | 0.8331 |
| oos_sharpe_q05 | -0.4236 |
| oos_sharpe_min | -0.6257 |
| fraction_negative | 0.2000 |

## Multiple testing

| key | value |
| --- | --- |
| n_trials | 268 |
| grid_trials | 1 |
| prior_trials | 267 |
| sharpe_variance_period | 0.0000 |
| candidate_sharpe_annual | 0.8360 |
| expected_max_sharpe_annual | 0.0000 |
| dsr | 0.9758 |
| dsr_p_value | 0.0242 |
| pbo | n/a |
| pbo_combinations | n/a |
| degradation_slope | n/a |
| prob_oos_loss | n/a |
| noise_null | sharpe_variance_period=0.0000; expected_max_sharpe_annual=1.2108; dsr_p_value=0.8120 |
| ledger_trials | 0 |

## Selection-deflated OOS threshold (D-028)

| key | value |
| --- | --- |
| n_obs | 44930 |
| n_trials | 268 |
| variance | 0.0000 |
| threshold_annual | 1.2635 |
| oos_sharpe_annual | 0.6253 |

## Stability

| key | value |
| --- | --- |
| time_split_sharpes | 1.2305, 0.9631, -0.7849, 1.1338 |
| worst_neighbour_degradation | 0.0552 |
| parameter_neighbourhood | entry_threshold=down=0.79 base=0.84 up=0.96 |

## Grid (full-sample Sharpe per configuration)

- single configuration: sharpe=0.84

## Cost stress (Sharpe)

| key | value |
| --- | --- |
| x1 | 0.8362 |
| x1.5 | 0.3189 |
| x2 | -0.1982 |

## Verdict

| key | value |
| --- | --- |
| verdict | FAIL |
| reasons | oos_t_stat 1.379683689571888 < 1.5, oos_sharpe 0.63 < the deflated threshold 1.26 at 268 trials, cpcv fraction_negative 0.20 > 0.1, cost stress x2 sharpe -0.20 < 0.0 |
