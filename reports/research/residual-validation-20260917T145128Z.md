# Validation: residual — FAIL

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
| exits | stop_loss=6.0000; trailing_stop=0.0000; trailing_activate=0.0000; take_profit=6.0000; cooldown_bars=24; vol_halflife=48; bars_per_day=24; min_unit=0.0050; unit_mode=entry; regime_window=0; regime_er_cut=0.0500; regime_tp_scale=0.5000; regime_side=low; stale_carry_bars=2 |
| margin_buffer | structural bound, not a measurement: buffer = (1 + r - c) / (gross * maintenance_margin_rate), and gross <= max_gross, so at mmr 0.005 and max_gross 2.0 it cannot fall below about 100.  Reaching the liquidation line at 1.0 would take one bar losing ~99%, so `liquidation_touches: 0` is arithmetic rather than evidence.  The channel that can actually liquidate this account is collateral repricing (52% non-USDT, KILL-AR-05) and this replay models zero collateral. |

## Best params (full sample)

| key | value |
| --- | --- |
| horizons | 168, 336, 720 |
| beta_window | 336 |
| scale | 0.1000 |
| benchmark | BTCUSDT |
| entry_threshold | 0.2000 |

## Full sample

| key | value |
| --- | --- |
| bars | 49312 |
| gross_return | 21.3912 |
| net_return | 13.6099 |
| annualized_sharpe | 1.1394 |
| annualized_sharpe_gross | 1.2768 |
| max_drawdown | -0.4044 |
| average_absolute_exposure | 1.3309 |
| turnover_units | 1101.5 |
| nonzero_target_bars | 49312 |
| hit_rate | 0.5025 |
| cost_share_of_gross | 0.1078 |
| guards | replayed=yes; gross_capped_bars=1234; daily_loss_pause_bars=528; bars=49312; min_margin_buffer=95.1992; liquidation_touches=0 |

## Walk-forward (out of sample)

| key | value |
| --- | --- |
| folds | 5 |
| oos_sharpe | 1.0484 |
| oos_windows | 62 |
| oos_window_sharpe_q10 | -3.6654 |
| oos_return | 7.9396 |
| oos_max_drawdown | -0.4044 |
| oos_bars | 45312 |
| oos_t_stat | 2.3567 |
| oos_t_lags | 15 |
| fold_sharpes | 1.6211, -0.1883, 1.3511, 0.6228, 1.8489 |
| fold_consistency | 0.8000 |
| selection_consistent | yes |
| oos_is_full_sample_tail | yes |
| best_key_oos_sharpe | 1.0484 |
| selection_exercised | NO fold had a choice to make (single configuration, or every fold picked the same one), so the OOS Sharpe above is the TAIL OF ONE FULL-SAMPLE SERIES, not a selection's out-of-sample record.  D-043 caps such a report at WEAK_PASS: the number stands, the claim that a selection survived out of sample does not.  `registry.py` still admits WEAK_PASS to live use. |

## CPCV

| key | value |
| --- | --- |
| paths | 15 |
| oos_sharpe_mean | 1.1364 |
| oos_sharpe_q05 | 0.6896 |
| oos_sharpe_min | 0.6475 |
| fraction_negative | 0.0000 |
| embargo | 50 bars, which is shorter than the model's feature lookback (tsmom max(horizons)=720, AlphaModel.warmup_bars 1442).  Training bars AFTER a test block are therefore computed from a window covering it, and `cpcv_evaluate` picks parameters on exactly those bars.  The returns stay causal, so this is selection contamination rather than look-ahead - it makes `fraction_negative`, one of D-020's hard gates, easier to pass than it should be.  Open boundary on the record: see `cpcv_splits`' docstring and docs/analysis/2026-09-13-full-repo-review.md. |

## Multiple testing

| key | value |
| --- | --- |
| n_trials | 17 |
| grid_trials | 1 |
| grid_effective_trials | 1.0000 |
| prior_trials | 0 |
| sharpe_variance_period | 0.0000 |
| candidate_sharpe_annual | 1.1394 |
| expected_max_sharpe_annual | 0.4398 |
| dsr | 0.9518 |
| dsr_p_value | 0.0482 |
| pbo | n/a |
| pbo_combinations | n/a |
| degradation_slope | n/a |
| prob_oos_loss | n/a |
| noise_null | sharpe_variance_period=0.0000; expected_max_sharpe_annual=0.7693; dsr_p_value=0.1896 |
| ledger_trials | 16 |
| pbo_is_informative | NOT informative and NOT enforced at grid_trials=1: CSCV ranks configurations against each other, and with fewer than four it only says that two curves traded places across sub-periods.  `verdict.decide` skips the gate below four, so a move in this number is not a cost or a gain either. |

## Selection-deflated OOS threshold (D-028)

| key | value |
| --- | --- |
| n_obs | 45312 |
| n_trials | 17 |
| alpha | 0.0500 |
| gate | max_sharpe_quantile |
| variance | 0.0000 |
| threshold_annual | 1.2046 |
| expected_max_annual | 0.8018 |
| p_family | 0.1338 |
| oos_sharpe_annual | 1.0484 |
| caliber | ENFORCED at N=17 (the per-strategy bucket): threshold 1.20, margin -0.16.  REPORTED and never enforced at N=21600 (the whole library): threshold 2.01, margin -0.96, p_family 1.0000.  Which N is the gate is R0 / KILL-AR-01, an operator ruling rather than a property of the arithmetic, and both numbers are printed so the ruling stays arguable from the artefact alone. |

## The other caliber (R0: reported, never enforced)

| key | value |
| --- | --- |
| n_obs | 45312 |
| n_trials | 21600 |
| alpha | 0.0500 |
| gate | max_sharpe_quantile |
| variance | 0.0000 |
| threshold_annual | 2.0069 |
| expected_max_annual | 1.7742 |
| p_family | 1.0000 |
| oos_sharpe_annual | 1.0484 |

## Cost stress against that gate (same folds, same N, best_key basis)

| key | value |
| --- | --- |
| x1 | oos=1.05 threshold=1.20 margin=-0.16 clears=0.00 |
| x1.5 | oos=0.92 threshold=1.20 margin=-0.28 clears=0.00 |
| x2 | oos=0.79 threshold=1.21 margin=-0.41 clears=0.00 |

## Stability

| key | value |
| --- | --- |
| time_split_sharpes | 1.3358, 0.1832, 1.0273, 1.5895 |
| worst_neighbour_degradation | 0.1396 |
| parameter_neighbourhood | beta_window=down=1.04 base=1.14 up=0.98; scale=down=1.02 base=1.14 up=1.12 |

## Grid (full-sample Sharpe per configuration)

- single configuration: sharpe=1.14

## Cost stress (Sharpe)

| key | value |
| --- | --- |
| x1 | 1.1394 |
| x1.5 | 1.0151 |
| x2 | 0.8915 |

## Slippage stress (Sharpe; fee fixed)

| key | value |
| --- | --- |
| slip2 | 1.1394 |
| slip5.5 | 1.0151 |
| slip9.2 | 0.8844 |

## Same book under close_to_close

| key | value |
| --- | --- |
| annualized_sharpe | 1.1100 |

## Verdict

| key | value |
| --- | --- |
| verdict | FAIL |
| reasons | oos_sharpe 1.05 < the deflated threshold 1.20 at 17 trials, p_family=0.1338 |
