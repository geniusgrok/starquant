# Validation: tsmom — FAIL

## Range

| key | value |
| --- | --- |
| start | 2021-03-02 01:00:00+00:00 |
| end | 2026-09-16 16:00:00+00:00 |
| bars | 48592 |

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
| bars | 49312 |
| gross_return | 125.0 |
| net_return | 83.1275 |
| annualized_sharpe | 1.6621 |
| annualized_sharpe_gross | 1.7873 |
| max_drawdown | -0.4029 |
| average_absolute_exposure | 1.3440 |
| turnover_units | 540.0 |
| nonzero_target_bars | 49312 |
| hit_rate | 0.5122 |
| cost_share_of_gross | 0.0701 |
| guards | replayed=yes; gross_capped_bars=4032; daily_loss_pause_bars=492; bars=49312; min_margin_buffer=97.1690; liquidation_touches=0 |

## Walk-forward (out of sample)

| key | value |
| --- | --- |
| folds | 5 |
| oos_sharpe | 1.2746 |
| oos_windows | 61 |
| oos_window_sharpe_q10 | -1.9483 |
| oos_return | 17.4818 |
| oos_max_drawdown | -0.4077 |
| oos_bars | 44592 |
| oos_t_stat | 2.8470 |
| oos_t_lags | 15 |
| fold_sharpes | 1.5562, 0.3322, 0.9906, 1.3611, 2.1375 |
| fold_consistency | 1.0000 |
| selection_consistent | no |
| oos_is_full_sample_tail | no |
| best_key_oos_sharpe | 1.5230 |
| selection_exercised | folds exercised a choice: this OOS is a selection procedure's out-of-sample record |

## CPCV

| key | value |
| --- | --- |
| paths | 15 |
| oos_sharpe_mean | 1.5856 |
| oos_sharpe_q05 | 1.1910 |
| oos_sharpe_min | 1.0581 |
| fraction_negative | 0.0000 |
| embargo | 50 bars, which is shorter than the model's feature lookback (tsmom max(horizons)=720, AlphaModel.warmup_bars 1442).  Training bars AFTER a test block are therefore computed from a window covering it, and `cpcv_evaluate` picks parameters on exactly those bars.  The returns stay causal, so this is selection contamination rather than look-ahead - it makes `fraction_negative`, one of D-020's hard gates, easier to pass than it should be.  Open boundary on the record: see `cpcv_splits`' docstring and docs/analysis/2026-09-13-full-repo-review.md. |

## Multiple testing

| key | value |
| --- | --- |
| n_trials | 291 |
| grid_trials | 16 |
| grid_effective_trials | 6.0000 |
| prior_trials | 152 |
| sharpe_variance_period | 0.0000 |
| candidate_sharpe_annual | 1.6213 |
| expected_max_sharpe_annual | 1.6103 |
| dsr | 0.5104 |
| dsr_p_value | 0.4896 |
| pbo | 0.0446 |
| pbo_combinations | 5000 |
| degradation_slope | -0.8758 |
| prob_oos_loss | 0.0000 |
| noise_null | sharpe_variance_period=0.0000; expected_max_sharpe_annual=1.2232; dsr_p_value=0.1738 |
| ledger_trials | 123 |
| pbo_is_informative | enforced: grid_trials=16 >= 4 |

## Selection-deflated OOS threshold (D-028)

| key | value |
| --- | --- |
| n_obs | 44592 |
| n_trials | 291 |
| alpha | 0.0500 |
| gate | max_sharpe_quantile |
| variance | 0.0000 |
| threshold_annual | 1.5790 |
| expected_max_annual | 1.2752 |
| p_family | 0.4350 |
| oos_sharpe_annual | 1.2746 |
| caliber | ENFORCED at N=291 (the per-strategy bucket): threshold 1.58, margin -0.30.  REPORTED and never enforced at N=1787 (the whole library): threshold 1.78, margin -0.50, p_family 0.9700.  Which N is the gate is R0 / KILL-AR-01, an operator ruling rather than a property of the arithmetic, and both numbers are printed so the ruling stays arguable from the artefact alone. |

## The other caliber (R0: reported, never enforced)

| key | value |
| --- | --- |
| n_obs | 44592 |
| n_trials | 1787 |
| alpha | 0.0500 |
| gate | max_sharpe_quantile |
| variance | 0.0000 |
| threshold_annual | 1.7778 |
| expected_max_annual | 1.5098 |
| p_family | 0.9700 |
| oos_sharpe_annual | 1.2746 |

## Cost stress against that gate (same folds, same N, best_key basis)

| key | value |
| --- | --- |
| x1 | oos=1.52 threshold=1.58 margin=-0.06 clears=0.00 |
| x1.5 | oos=1.46 threshold=1.58 margin=-0.12 clears=0.00 |
| x2 | oos=1.40 threshold=1.58 margin=-0.18 clears=0.00 |

## Stability

| key | value |
| --- | --- |
| time_split_sharpes | 0.9796, 0.7131, 1.4876, 1.9378 |
| worst_neighbour_degradation | 0.0687 |
| parameter_neighbourhood | entry_threshold=down=1.56 base=1.66 up=1.55; return_scale=down=1.62 base=1.66 up=1.66; vol_window=down=1.66 base=1.66 up=1.66 |

## Grid (full-sample Sharpe per configuration)

- entry_threshold=0.2, horizons=[168, 336, 720], return_scale=0.2: sharpe=1.62
- entry_threshold=0.2, horizons=[168, 336, 720], return_scale=0.3: sharpe=1.56
- entry_threshold=0.3, horizons=[168, 336, 720], return_scale=0.2: sharpe=1.35
- entry_threshold=0.3, horizons=[24, 72, 168], return_scale=0.2: sharpe=1.14
- entry_threshold=0.3, horizons=[168, 336, 720], return_scale=0.3: sharpe=1.07
- entry_threshold=0.3, horizons=[24, 72, 168], return_scale=0.3: sharpe=1.04
- entry_threshold=0.2, horizons=[24, 72, 168], return_scale=0.3: sharpe=1.01
- entry_threshold=0.2, horizons=[24, 72, 168], return_scale=0.2: sharpe=0.97
- entry_threshold=0.3, horizons=[5, 20, 50], return_scale=0.3: sharpe=0.67
- entry_threshold=0.2, horizons=[336, 720, 1440], return_scale=0.3: sharpe=0.54
- entry_threshold=0.3, horizons=[5, 20, 50], return_scale=0.2: sharpe=0.53
- entry_threshold=0.2, horizons=[5, 20, 50], return_scale=0.3: sharpe=0.51
- entry_threshold=0.2, horizons=[336, 720, 1440], return_scale=0.2: sharpe=0.46
- entry_threshold=0.3, horizons=[336, 720, 1440], return_scale=0.2: sharpe=0.42
- entry_threshold=0.2, horizons=[5, 20, 50], return_scale=0.2: sharpe=0.38
- entry_threshold=0.3, horizons=[336, 720, 1440], return_scale=0.3: sharpe=0.36

## Cost stress (Sharpe)

| key | value |
| --- | --- |
| x1 | 1.6621 |
| x1.5 | 1.6034 |
| x2 | 1.5447 |

## Slippage stress (Sharpe; fee fixed)

| key | value |
| --- | --- |
| slip2 | 1.6621 |
| slip5.5 | 1.6034 |
| slip9.2 | 1.5413 |

## Same book under close_to_close

| key | value |
| --- | --- |
| annualized_sharpe | 1.6460 |

## Verdict

| key | value |
| --- | --- |
| verdict | FAIL |
| reasons | oos_sharpe 1.27 < the deflated threshold 1.58 at 291 trials, p_family=0.4350 |
