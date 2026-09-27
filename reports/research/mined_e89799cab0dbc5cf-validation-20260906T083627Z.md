# Validation: mined_e89799cab0dbc5cf — FAIL

## Range

| key | value |
| --- | --- |
| start | 2021-02-27 23:00:00+00:00 |
| end | 2026-09-05 16:00:00+00:00 |
| bars | 48378 |

## Holdout (KILL-006)

| key | value |
| --- | --- |
| months | 0 |
| note | no tail reserved: every bar was available to this run |

## Best params (full sample)

| key | value |
| --- | --- |
| entry_threshold | 0.2000 |
| expression | cs_rank(rz(ret(720), 336)) |
| hash | e89799cab0dbc5cf |

## Full sample

| key | value |
| --- | --- |
| bars | 48378 |
| gross_return | 15.0951 |
| net_return | 3.5284 |
| annualized_sharpe | 1.0746 |
| annualized_sharpe_gross | 1.8532 |
| max_drawdown | -0.4174 |
| average_absolute_exposure | 1.1353 |
| turnover_units | 1876.1 |
| nonzero_target_bars | 48378 |
| hit_rate | 0.4968 |
| cost_share_of_gross | 0.4201 |

## Walk-forward (out of sample)

| key | value |
| --- | --- |
| folds | 5 |
| oos_sharpe | 0.8577 |
| oos_return | 1.8834 |
| oos_max_drawdown | -0.4174 |
| oos_bars | 44378 |
| oos_t_stat | 1.9403 |
| oos_t_lags | 15 |
| fold_sharpes | 1.7225, 1.0919, 0.6768, -0.3993, 1.1316 |
| fold_consistency | 0.8000 |

## CPCV

| key | value |
| --- | --- |
| paths | 15 |
| oos_sharpe_mean | 1.0670 |
| oos_sharpe_q05 | 0.2439 |
| oos_sharpe_min | -0.0255 |
| fraction_negative | 0.0667 |

## Multiple testing

| key | value |
| --- | --- |
| n_trials | 268 |
| grid_trials | 1 |
| prior_trials | 267 |
| sharpe_variance_period | 0.0000 |
| candidate_sharpe_annual | 1.0746 |
| expected_max_sharpe_annual | 0.0000 |
| dsr | 0.9942 |
| dsr_p_value | 0.0058 |
| pbo | n/a |
| pbo_combinations | n/a |
| degradation_slope | n/a |
| prob_oos_loss | n/a |
| noise_null | sharpe_variance_period=0.0000; expected_max_sharpe_annual=1.2167; dsr_p_value=0.6308 |
| ledger_trials | 0 |

## Selection-deflated OOS threshold (D-028)

| key | value |
| --- | --- |
| n_obs | 44378 |
| n_trials | 268 |
| variance | 0.0000 |
| threshold_annual | 1.2702 |
| oos_sharpe_annual | 0.8577 |

## Stability

| key | value |
| --- | --- |
| time_split_sharpes | 1.7282, 1.1196, 0.1336, 0.4294 |
| worst_neighbour_degradation | 0.0572 |
| parameter_neighbourhood | entry_threshold=down=1.01 base=1.07 up=1.09 |

## Grid (full-sample Sharpe per configuration)

- single configuration: sharpe=1.07

## Cost stress (Sharpe)

| key | value |
| --- | --- |
| x1 | 1.0739 |
| x1.5 | 0.6706 |
| x2 | 0.2675 |

## Verdict

| key | value |
| --- | --- |
| verdict | FAIL |
| reasons | oos_sharpe 0.86 < the deflated threshold 1.27 at 268 trials |
