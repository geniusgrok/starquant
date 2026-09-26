# Validation: breakout — FAIL

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
| atr_window | 14 |
| distance_scale | 2.0000 |
| volume_window | 20 |
| entry_threshold | 0.2000 |

## Full sample

| key | value |
| --- | --- |
| bars | 49312 |
| gross_return | -0.9290 |
| net_return | -1.0000 |
| annualized_sharpe | -4.5014 |
| annualized_sharpe_gross | -0.5457 |
| max_drawdown | -1.0000 |
| average_absolute_exposure | 1.4832 |
| turnover_units | 18237.1 |
| nonzero_target_bars | 49213 |
| hit_rate | 0.4796 |
| cost_share_of_gross | n/a |
| guards | replayed=yes; gross_capped_bars=7306; daily_loss_pause_bars=1254; bars=49312; min_margin_buffer=95.1036; liquidation_touches=0 |

## Walk-forward (out of sample)

| key | value |
| --- | --- |
| folds | 5 |
| oos_sharpe | -4.3021 |
| oos_windows | 62 |
| oos_window_sharpe_q10 | -8.2670 |
| oos_return | -1.0000 |
| oos_max_drawdown | -1.0000 |
| oos_bars | 45312 |
| oos_t_stat | -10.0357 |
| oos_t_lags | 15 |
| fold_sharpes | -4.2978, -3.0575, -5.0276, -5.5302, -3.5168 |
| fold_consistency | 0.0000 |
| selection_consistent | yes |
| oos_is_full_sample_tail | yes |
| best_key_oos_sharpe | -4.3021 |

## CPCV

| key | value |
| --- | --- |
| paths | 15 |
| oos_sharpe_mean | -4.4993 |
| oos_sharpe_q05 | -5.1463 |
| oos_sharpe_min | -5.2557 |
| fraction_negative | 1.0000 |
| embargo | 50 bars, which is shorter than the model's feature lookback (tsmom max(horizons)=720, AlphaModel.warmup_bars 1442).  Training bars AFTER a test block are therefore computed from a window covering it, and `cpcv_evaluate` picks parameters on exactly those bars.  The returns stay causal, so this is selection contamination rather than look-ahead - it makes `fraction_negative`, one of D-020's hard gates, easier to pass than it should be.  Open boundary on the record: see `cpcv_splits`' docstring and docs/analysis/2026-09-13-full-repo-review.md. |

## Multiple testing

| key | value |
| --- | --- |
| n_trials | 10 |
| grid_trials | 1 |
| grid_effective_trials | 1.0000 |
| prior_trials | 0 |
| sharpe_variance_period | 0.0004 |
| candidate_sharpe_annual | -4.5014 |
| expected_max_sharpe_annual | 3.0510 |
| dsr | 0.0000 |
| dsr_p_value | 1.0000 |
| pbo | n/a |
| pbo_combinations | n/a |
| degradation_slope | n/a |
| prob_oos_loss | n/a |
| noise_null | sharpe_variance_period=0.0000; expected_max_sharpe_annual=0.6560; dsr_p_value=1.0000 |
| ledger_trials | 9 |
| pbo_is_informative | NOT informative and NOT enforced at grid_trials=1: CSCV ranks configurations against each other, and with fewer than four it only says that two curves traded places across sub-periods.  `verdict.decide` skips the gate below four, so a move in this number is not a cost or a gain either. |

## Selection-deflated OOS threshold (D-028)

| key | value |
| --- | --- |
| n_obs | 45312 |
| n_trials | 10 |
| alpha | 0.0500 |
| gate | max_sharpe_quantile |
| variance | 0.0000 |
| threshold_annual | 1.1167 |
| expected_max_annual | 0.6848 |
| p_family | 1.0000 |
| oos_sharpe_annual | -4.3021 |

## Cost stress against that gate (same folds, same N, best_key basis)

| key | value |
| --- | --- |
| x1 | oos=-4.30 threshold=1.12 margin=-5.42 clears=0.00 |
| x1.5 | oos=-6.28 threshold=1.12 margin=-7.40 clears=0.00 |
| x2 | oos=-8.33 threshold=1.12 margin=-9.44 clears=0.00 |

## Stability

| key | value |
| --- | --- |
| time_split_sharpes | -3.4835, -4.7138, -5.0957, -3.9677 |
| worst_neighbour_degradation | 0.0445 |
| parameter_neighbourhood | distance_scale=down=-4.70 base=-4.50 up=-4.39; window=down=-4.46 base=-4.50 up=-4.47 |

## Grid (full-sample Sharpe per configuration)

- single configuration: sharpe=-4.50

## Cost stress (Sharpe)

| key | value |
| --- | --- |
| x1 | -4.5014 |
| x1.5 | -6.4476 |
| x2 | -8.4690 |

## Slippage stress (Sharpe; fee fixed)

| key | value |
| --- | --- |
| slip2 | -4.5014 |
| slip5.5 | -6.4476 |
| slip9.2 | -8.5824 |

## Same book under close_to_close

| key | value |
| --- | --- |
| annualized_sharpe | -4.5064 |

## Verdict

| key | value |
| --- | --- |
| verdict | FAIL |
| reasons | oos_sharpe -4.30 < 0.5, oos_sharpe -4.30 < the deflated threshold 1.12 at 10 trials, p_family=1.0000, fold_consistency 0.00 < 0.6, cpcv fraction_negative 1.00 > 0.1, cost stress x2 sharpe -8.47 < 0.0 |
