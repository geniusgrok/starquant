# Validation: mined_1ce07bec1af7a710 — FAIL

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
| expression | cs_rank(z(ret(7), 7)) |
| hash | 1ce07bec1af7a710 |

## Full sample

| key | value |
| --- | --- |
| bars | 2041 |
| gross_return | 7.4542 |
| net_return | 2.1431 |
| annualized_sharpe | 0.8836 |
| annualized_sharpe_gross | 1.5288 |
| max_drawdown | -0.3067 |
| average_absolute_exposure | 1.2216 |
| turnover_units | 1339.1 |
| nonzero_target_bars | 1976 |
| hit_rate | 0.5202 |
| cost_share_of_gross | 0.4222 |

## Walk-forward (out of sample)

| key | value |
| --- | --- |
| folds | 5 |
| oos_sharpe | 0.8802 |
| oos_return | 1.8605 |
| oos_max_drawdown | -0.3067 |
| oos_bars | 1874 |
| oos_t_stat | 1.9286 |
| oos_t_lags | 7 |
| fold_sharpes | 0.8171, 0.6633, 1.1582, -0.4420, 2.0731 |
| fold_consistency | 0.8000 |

## CPCV

| key | value |
| --- | --- |
| paths | 15 |
| oos_sharpe_mean | 0.8778 |
| oos_sharpe_q05 | 0.1933 |
| oos_sharpe_min | -0.0999 |
| fraction_negative | 0.0667 |

## Multiple testing

| key | value |
| --- | --- |
| n_trials | 239 |
| grid_trials | 1 |
| prior_trials | 238 |
| sharpe_variance_period | 0.0000 |
| candidate_sharpe_annual | 0.8836 |
| expected_max_sharpe_annual | 0.0000 |
| dsr | 0.9823 |
| dsr_p_value | 0.0177 |
| pbo | n/a |
| pbo_combinations | n/a |
| degradation_slope | n/a |
| prob_oos_loss | n/a |
| noise_null | sharpe_variance_period=0.0005; expected_max_sharpe_annual=1.1857; dsr_p_value=0.7640 |
| ledger_trials | 0 |

## Selection-deflated OOS threshold (D-028)

| key | value |
| --- | --- |
| n_obs | 1874 |
| n_trials | 239 |
| variance | 0.0005 |
| threshold_annual | 1.2369 |
| oos_sharpe_annual | 0.8802 |

## Stability

| key | value |
| --- | --- |
| time_split_sharpes | 1.6147, -0.0802, 0.2820, 1.7372 |
| worst_neighbour_degradation | 0.0000 |
| parameter_neighbourhood | entry_threshold=down=0.91 base=0.88 up=0.88 |

## Grid (full-sample Sharpe per configuration)

- single configuration: sharpe=0.88

## Cost stress (Sharpe)

| key | value |
| --- | --- |
| x1 | 0.8838 |
| x1.5 | 0.5781 |
| x2 | 0.2723 |

## Verdict

| key | value |
| --- | --- |
| verdict | FAIL |
| reasons | oos_sharpe 0.88 < the deflated threshold 1.24 at 239 trials |
