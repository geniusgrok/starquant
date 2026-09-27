# Validation: meanrev — FAIL

## Range

| key | value |
| --- | --- |
| start | 2021-01-31 01:00:00+00:00 |
| end | 2026-09-16 16:00:00+00:00 |
| bars | 49312 |

## Holdout (KILL-006)

| key | value |
| --- | --- |
| months | 0 |
| note | no tail reserved: every bar was available to this run |

## Book guards / exits (the layers the loop applies)

| key | value |
| --- | --- |
| guards | max_weight=0.1500; max_gross=2.0000; daily_loss_pause=-0.0500 |
| exits | stop_loss=6.0000; trailing_stop=0.0000; take_profit=6.0000; cooldown_bars=24; vol_halflife=48; bars_per_day=24; min_unit=0.0050; unit_mode=entry; regime_window=0; regime_er_cut=0.0500; regime_tp_scale=0.5000; regime_side=low; stale_carry_bars=2 |
| margin_buffer | structural bound, not a measurement: buffer = (1 + r - c) / (gross * maintenance_margin_rate), and gross <= max_gross, so at mmr 0.005 and max_gross 2.0 it cannot fall below about 100.  Reaching the liquidation line at 1.0 would take one bar losing ~99%, so `liquidation_touches: 0` is arithmetic rather than evidence.  The channel that can actually liquidate this account is collateral repricing (52% non-USDT, KILL-AR-05) and this replay models zero collateral. |

## Best params (full sample)

| key | value |
| --- | --- |
| window | 48 |
| z_entry | 1.5000 |
| z_exit | 0.5000 |
| z_max | 5.0000 |
| trend_gate_z | 2.0000 |
| vol_window | 48 |
| entry_threshold | 0.2000 |

## Full sample

| key | value |
| --- | --- |
| bars | 49312 |
| gross_return | -0.9901 |
| net_return | -0.9993 |
| annualized_sharpe | -2.3901 |
| annualized_sharpe_gross | -1.4385 |
| max_drawdown | -0.9994 |
| average_absolute_exposure | 0.5595 |
| turnover_units | 3918.1 |
| nonzero_target_bars | 45166 |
| hit_rate | 0.4937 |
| cost_share_of_gross | n/a |
| guards | replayed=yes; gross_capped_bars=4; daily_loss_pause_bars=739; bars=49312; min_margin_buffer=99.5817; liquidation_touches=0 |

## Walk-forward (out of sample)

| key | value |
| --- | --- |
| folds | 5 |
| oos_sharpe | -2.2908 |
| oos_windows | 62 |
| oos_window_sharpe_q10 | -5.7492 |
| oos_return | -0.9981 |
| oos_max_drawdown | -0.9983 |
| oos_bars | 45312 |
| oos_t_stat | -5.2454 |
| oos_t_lags | 15 |
| fold_sharpes | -3.5153, -1.4083, -2.0488, -2.2397, -2.1042 |
| fold_consistency | 0.0000 |
| selection_consistent | yes |
| oos_is_full_sample_tail | yes |
| best_key_oos_sharpe | -2.2908 |

## CPCV

| key | value |
| --- | --- |
| paths | 15 |
| oos_sharpe_mean | -2.3834 |
| oos_sharpe_q05 | -2.8032 |
| oos_sharpe_min | -2.8049 |
| fraction_negative | 1.0000 |
| embargo | 50 bars, which is shorter than the model's feature lookback (tsmom max(horizons)=720, AlphaModel.warmup_bars 1442).  Training bars AFTER a test block are therefore computed from a window covering it, and `cpcv_evaluate` picks parameters on exactly those bars.  The returns stay causal, so this is selection contamination rather than look-ahead - it makes `fraction_negative`, one of D-020's hard gates, easier to pass than it should be.  Open boundary on the record: see `cpcv_splits`' docstring and docs/analysis/2026-09-13-full-repo-review.md. |

## Multiple testing

| key | value |
| --- | --- |
| n_trials | 28 |
| grid_trials | 1 |
| grid_effective_trials | 1.0000 |
| prior_trials | 0 |
| sharpe_variance_period | 0.0001 |
| candidate_sharpe_annual | -2.3901 |
| expected_max_sharpe_annual | 1.7104 |
| dsr | 0.0000 |
| dsr_p_value | 1.0000 |
| pbo | n/a |
| pbo_combinations | n/a |
| degradation_slope | n/a |
| prob_oos_loss | n/a |
| noise_null | sharpe_variance_period=0.0000; expected_max_sharpe_annual=0.8498; dsr_p_value=1.0000 |
| ledger_trials | 27 |
| pbo_is_informative | NOT informative and NOT enforced at grid_trials=1: CSCV ranks configurations against each other, and with fewer than four it only says that two curves traded places across sub-periods.  `verdict.decide` skips the gate below four, so a move in this number is not a cost or a gain either. |

## Selection-deflated OOS threshold (D-028)

| key | value |
| --- | --- |
| n_obs | 45312 |
| n_trials | 28 |
| alpha | 0.0500 |
| gate | max_sharpe_quantile |
| variance | 0.0000 |
| threshold_annual | 1.2622 |
| expected_max_annual | 0.8881 |
| p_family | 1.0000 |
| oos_sharpe_annual | -2.2908 |

## Cost stress against that gate (same folds, same N, best_key basis)

| key | value |
| --- | --- |
| x1 | oos=-2.29 threshold=1.26 margin=-3.55 clears=0.00 |
| x1.5 | oos=-2.81 threshold=1.26 margin=-4.07 clears=0.00 |
| x2 | oos=-3.32 threshold=1.26 margin=-4.58 clears=0.00 |

## Stability

| key | value |
| --- | --- |
| time_split_sharpes | -2.4459, -2.3785, -1.9619, -2.4137 |
| worst_neighbour_degradation | 0.0757 |
| parameter_neighbourhood | trend_gate_z=down=-2.38 base=-2.39 up=-2.45; window=down=-2.57 base=-2.39 up=-2.25; z_entry=down=-2.51 base=-2.39 up=-2.10 |

## Grid (full-sample Sharpe per configuration)

- single configuration: sharpe=-2.39

## Cost stress (Sharpe)

| key | value |
| --- | --- |
| x1 | -2.3901 |
| x1.5 | -2.8892 |
| x2 | -3.3860 |

## Slippage stress (Sharpe; fee fixed)

| key | value |
| --- | --- |
| slip2 | -2.3901 |
| slip5.5 | -2.8892 |
| slip9.2 | -3.4145 |

## Same book under close_to_close

| key | value |
| --- | --- |
| annualized_sharpe | -2.3921 |

## Verdict

| key | value |
| --- | --- |
| verdict | FAIL |
| reasons | oos_sharpe -2.29 < 0.5, oos_sharpe -2.29 < the deflated threshold 1.26 at 28 trials, p_family=1.0000, fold_consistency 0.00 < 0.6, cpcv fraction_negative 1.00 > 0.1, cost stress x2 sharpe -3.39 < 0.0 |
