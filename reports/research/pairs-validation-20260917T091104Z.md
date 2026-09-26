# Validation: pairs — FAIL

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
| bars | 49312 |
| gross_return | 0.8250 |
| net_return | 0.3941 |
| annualized_sharpe | 0.3437 |
| annualized_sharpe_gross | 0.4794 |
| max_drawdown | -0.5689 |
| average_absolute_exposure | 1.2133 |
| turnover_units | 291.4 |
| nonzero_target_bars | 49148 |
| hit_rate | 0.4991 |
| cost_share_of_gross | 0.2832 |
| guards | replayed=yes; gross_capped_bars=0; daily_loss_pause_bars=160; bars=49312; min_margin_buffer=99.3692; liquidation_touches=0 |

## Walk-forward (out of sample)

| key | value |
| --- | --- |
| folds | 5 |
| oos_sharpe | 0.5830 |
| oos_windows | 62 |
| oos_window_sharpe_q10 | -3.3188 |
| oos_return | 1.0801 |
| oos_max_drawdown | -0.5170 |
| oos_bars | 45312 |
| oos_t_stat | 1.3303 |
| oos_t_lags | 15 |
| fold_sharpes | 0.2286, 0.4030, -0.3060, 0.7283, 1.5248 |
| fold_consistency | 0.8000 |
| selection_consistent | yes |
| oos_is_full_sample_tail | yes |
| best_key_oos_sharpe | 0.5830 |

## CPCV

| key | value |
| --- | --- |
| paths | 15 |
| oos_sharpe_mean | 0.3233 |
| oos_sharpe_q05 | -0.3679 |
| oos_sharpe_min | -0.5142 |
| fraction_negative | 0.3333 |
| embargo | 50 bars, which is shorter than the model's feature lookback (tsmom max(horizons)=720, AlphaModel.warmup_bars 1442).  Training bars AFTER a test block are therefore computed from a window covering it, and `cpcv_evaluate` picks parameters on exactly those bars.  The returns stay causal, so this is selection contamination rather than look-ahead - it makes `fraction_negative`, one of D-020's hard gates, easier to pass than it should be.  Open boundary on the record: see `cpcv_splits`' docstring and docs/analysis/2026-09-13-full-repo-review.md. |

## Multiple testing

| key | value |
| --- | --- |
| n_trials | 19777 |
| grid_trials | 1 |
| grid_effective_trials | 1.0000 |
| prior_trials | 0 |
| sharpe_variance_period | 0.0000 |
| candidate_sharpe_annual | 0.3437 |
| expected_max_sharpe_annual | 0.8146 |
| dsr | 0.1319 |
| dsr_p_value | 0.8681 |
| pbo | n/a |
| pbo_combinations | n/a |
| degradation_slope | n/a |
| prob_oos_loss | n/a |
| noise_null | sharpe_variance_period=0.0000; expected_max_sharpe_annual=1.6959; dsr_p_value=0.9993 |
| ledger_trials | 19776 |
| pbo_is_informative | NOT informative and NOT enforced at grid_trials=1: CSCV ranks configurations against each other, and with fewer than four it only says that two curves traded places across sub-periods.  `verdict.decide` skips the gate below four, so a move in this number is not a cost or a gain either. |

## Signal's own search (DL-K2)

| key | value |
| --- | --- |
| bucket | pairs_search |
| charged | 19772 |
| candidates | 19772 |
| selected | 152 |
| family_prior | strategy=pairs_search; before=0; after=19772 |

## Selection-deflated OOS threshold (D-028)

| key | value |
| --- | --- |
| n_obs | 45312 |
| n_trials | 19777 |
| alpha | 0.0500 |
| gate | max_sharpe_quantile |
| variance | 0.0000 |
| threshold_annual | 2.0019 |
| expected_max_annual | 1.7679 |
| p_family | 1.0000 |
| oos_sharpe_annual | 0.5830 |

## Cost stress against that gate (same folds, same N, best_key basis)

| key | value |
| --- | --- |
| x1 | oos=0.58 threshold=2.00 margin=-1.42 clears=0.00 |
| x1.5 | oos=0.53 threshold=2.00 margin=-1.47 clears=0.00 |
| x2 | oos=0.48 threshold=2.00 margin=-1.52 clears=0.00 |

## Stability

| key | value |
| --- | --- |
| time_split_sharpes | 0.2087, 0.0192, 0.5933, 1.2773 |
| worst_neighbour_degradation | 1.9496 |
| parameter_neighbourhood | formation_bars=down=0.05 base=0.34 up=0.26; refit_bars=down=0.48 base=0.34 up=-0.33; z_window=down=0.29 base=0.34 up=0.30; entry_z=down=0.33 base=0.34 up=0.29; exit_z=down=0.35 base=0.34 up=0.34; z_scale=down=0.30 base=0.34 up=0.33; min_corr=down=0.35 base=0.34 up=0.35; entry_threshold=down=0.34 base=0.34 up=0.34 |

## Grid (full-sample Sharpe per configuration)

- single configuration: sharpe=0.34

## Cost stress (Sharpe)

| key | value |
| --- | --- |
| x1 | 0.3437 |
| x1.5 | 0.2922 |
| x2 | 0.2408 |

## Slippage stress (Sharpe; fee fixed)

| key | value |
| --- | --- |
| slip2 | 0.3437 |
| slip5.5 | 0.2922 |
| slip9.2 | 0.2378 |

## Same book under close_to_close

| key | value |
| --- | --- |
| annualized_sharpe | 0.3860 |

## Verdict

| key | value |
| --- | --- |
| verdict | FAIL |
| reasons | oos_sharpe 0.58 < the deflated threshold 2.00 at 19777 trials, p_family=1.0000, cpcv fraction_negative 0.33 > 0.1 |
