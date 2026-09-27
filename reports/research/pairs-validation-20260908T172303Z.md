# Validation: pairs — FAIL

## Range

| key | value |
| --- | --- |
| start | 2021-01-31 01:00:00+00:00 |
| end | 2026-09-07 16:00:00+00:00 |
| bars | 49096 |

## Holdout (KILL-006)

| key | value |
| --- | --- |
| months | 0 |
| note | no tail reserved: every bar was available to this run |

## Book guards / exits (the layers the loop applies)

| key | value |
| --- | --- |
| guards | max_weight=0.1500; max_gross=2.0000; daily_loss_pause=-0.0500 |
| exits | stop_loss=6.0000; trailing_stop=0.0000; take_profit=6.0000; cooldown_bars=24; vol_halflife=48; bars_per_day=24; min_unit=0.0050; unit_mode=entry; regime_window=0; regime_er_cut=0.0500; regime_tp_scale=0.5000; regime_side=low |

## Best params (full sample)

| key | value |
| --- | --- |
| formation_bars | 720 |
| refit_bars | 720 |
| z_window | 168 |
| entry_z | 2.0000 |
| exit_z | 0.5000 |
| z_scale | 3.0000 |
| min_corr | 0.5000 |
| entry_threshold | 0.2000 |

## Full sample

| key | value |
| --- | --- |
| bars | 49096 |
| gross_return | 0.2607 |
| net_return | -0.0159 |
| annualized_sharpe | 0.1141 |
| annualized_sharpe_gross | 0.2902 |
| max_drawdown | -0.4949 |
| average_absolute_exposure | 0.9727 |
| turnover_units | 260.3 |
| nonzero_target_bars | 48932 |
| hit_rate | 0.4977 |
| cost_share_of_gross | 0.6069 |
| guards | replayed=yes; gross_capped_bars=0; daily_loss_pause_bars=23; bars=49096; min_margin_buffer=110.8; liquidation_touches=0 |

## Walk-forward (out of sample)

| key | value |
| --- | --- |
| folds | 5 |
| oos_sharpe | 0.1707 |
| oos_windows | 62 |
| oos_window_sharpe_q10 | -4.6393 |
| oos_return | 0.0579 |
| oos_max_drawdown | -0.5010 |
| oos_bars | 45096 |
| oos_t_stat | 0.3882 |
| oos_t_lags | 15 |
| fold_sharpes | 0.5446, -0.5991, -0.6629, 0.0736, 1.4642 |
| fold_consistency | 0.6000 |
| selection_consistent | no |
| oos_is_full_sample_tail | no |
| best_key_oos_sharpe | 0.2279 |

## CPCV

| key | value |
| --- | --- |
| paths | 15 |
| oos_sharpe_mean | -0.0418 |
| oos_sharpe_q05 | -0.7659 |
| oos_sharpe_min | -0.8847 |
| fraction_negative | 0.6000 |

## Multiple testing

| key | value |
| --- | --- |
| n_trials | 4 |
| grid_trials | 4 |
| grid_effective_trials | 2.0000 |
| prior_trials | 0 |
| sharpe_variance_period | 0.0000 |
| candidate_sharpe_annual | 0.1141 |
| expected_max_sharpe_annual | 0.1471 |
| dsr | 0.4689 |
| dsr_p_value | 0.5311 |
| pbo | 0.6264 |
| pbo_combinations | 5000 |
| degradation_slope | -0.8541 |
| prob_oos_loss | 0.6380 |
| noise_null | sharpe_variance_period=0.0000; expected_max_sharpe_annual=0.4444; dsr_p_value=0.7829 |
| ledger_trials | 0 |

## Selection-deflated OOS threshold (D-028)

| key | value |
| --- | --- |
| n_obs | 45096 |
| n_trials | 4 |
| alpha | 0.0500 |
| gate | max_sharpe_quantile |
| variance | 0.0000 |
| threshold_annual | 0.9842 |
| expected_max_annual | 0.4635 |
| p_family | 0.8206 |
| oos_sharpe_annual | 0.1707 |

## Stability

| key | value |
| --- | --- |
| time_split_sharpes | 0.3725, -0.9349, 0.0117, 1.1457 |
| worst_neighbour_degradation | 6.8430 |
| parameter_neighbourhood | formation_bars=down=-0.01 base=0.11 up=-0.07; refit_bars=down=0.25 base=0.11 up=-0.67; z_window=down=0.05 base=0.11 up=0.14; entry_z=down=0.12 base=0.11 up=0.13; exit_z=down=0.13 base=0.11 up=0.12; z_scale=down=0.14 base=0.11 up=0.18; min_corr=down=0.10 base=0.11 up=0.12; entry_threshold=down=0.11 base=0.11 up=0.11 |

## Grid (full-sample Sharpe per configuration)

- entry_z=2.0, z_window=168: sharpe=0.11
- entry_z=1.5, z_window=168: sharpe=0.09
- entry_z=1.5, z_window=336: sharpe=-0.12
- entry_z=2.0, z_window=336: sharpe=-0.16

## Cost stress (Sharpe)

| key | value |
| --- | --- |
| x1 | 0.1141 |
| x1.5 | 0.0493 |
| x2 | -0.0155 |

## Slippage stress (Sharpe; fee fixed)

| key | value |
| --- | --- |
| slip2 | 0.1141 |
| slip5.5 | 0.0493 |
| slip9.2 | -0.0192 |

## Same book under close_to_close

| key | value |
| --- | --- |
| annualized_sharpe | 0.1432 |

## Verdict

| key | value |
| --- | --- |
| verdict | FAIL |
| reasons | oos_sharpe 0.17 < 0.5, oos_sharpe 0.17 < the deflated threshold 0.98 at 4 trials, p_family=0.8206, cpcv fraction_negative 0.60 > 0.1, pbo 0.63 > 0.3, cost stress x2 sharpe -0.02 < 0.0 |
