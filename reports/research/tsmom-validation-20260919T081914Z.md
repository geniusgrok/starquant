# Validation: tsmom — FAIL

## Range

| key | value |
| --- | --- |
| start | 2021-03-02 01:00:00+00:00 |
| end | 2026-09-18 16:00:00+00:00 |
| bars | 48640 |

## Holdout (KILL-006)

| key | value |
| --- | --- |
| months | 0 |
| note | no tail reserved: every bar was available to this run |

## Book guards / exits (the layers the loop applies)

| key | value |
| --- | --- |
| guards | max_weight=0.1500; max_gross=2.0000; daily_loss_pause=-0.0500 |
| exits | stop_loss=6.0000; stop_loss_price_cap=0.0000; trailing_stop=0.0000; trailing_activate=0.0000; take_profit=6.0000; cooldown_bars=24; vol_halflife=48; bars_per_day=24; min_unit=0.0050; unit_mode=entry; regime_window=0; regime_er_cut=0.0500; regime_tp_scale=0.5000; regime_side=low; stale_carry_bars=2 |
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
| bars | 49360 |
| gross_return | 128.7 |
| net_return | 84.6156 |
| annualized_sharpe | 1.6670 |
| annualized_sharpe_gross | 1.7958 |
| max_drawdown | -0.4029 |
| average_absolute_exposure | 1.3435 |
| turnover_units | 541.5 |
| nonzero_target_bars | 49360 |
| hit_rate | 0.5119 |
| cost_share_of_gross | 0.0718 |
| guards | replayed=yes; gross_capped_bars=4043; daily_loss_pause_bars=481; bars=49360; min_margin_buffer=97.1690; liquidation_touches=0 |

## Walk-forward (out of sample)

| key | value |
| --- | --- |
| folds | 5 |
| oos_sharpe | 1.2306 |
| oos_windows | 62 |
| oos_window_sharpe_q10 | -1.8243 |
| oos_return | 15.2787 |
| oos_max_drawdown | -0.4068 |
| oos_bars | 44640 |
| oos_t_stat | 2.7621 |
| oos_t_lags | 15 |
| fold_sharpes | 1.5548, 0.2727, 1.0710, 1.3471, 1.9030 |
| fold_consistency | 1.0000 |
| selection_consistent | no |
| oos_is_full_sample_tail | no |
| best_key_oos_sharpe | 1.5292 |
| selection_exercised | folds exercised a choice: this OOS is a selection procedure's out-of-sample record |

## CPCV

| key | value |
| --- | --- |
| paths | 15 |
| oos_sharpe_mean | 1.5974 |
| oos_sharpe_q05 | 1.2018 |
| oos_sharpe_min | 1.0923 |
| fraction_negative | 0.0000 |
| embargo | 50 bars, which is shorter than the model's feature lookback (tsmom max(horizons)=720, AlphaModel.warmup_bars 1442).  Training bars AFTER a test block are therefore computed from a window covering it, and `cpcv_evaluate` picks parameters on exactly those bars.  The returns stay causal, so this is selection contamination rather than look-ahead - it makes `fraction_negative`, one of D-020's hard gates, easier to pass than it should be.  Open boundary on the record: see `cpcv_splits`' docstring and docs/analysis/2026-09-13-full-repo-review.md. |

## Multiple testing

| key | value |
| --- | --- |
| n_trials | 167 |
| grid_trials | 16 |
| grid_effective_trials | 6.0000 |
| prior_trials | 0 |
| sharpe_variance_period | 0.0000 |
| candidate_sharpe_annual | 1.6273 |
| expected_max_sharpe_annual | 1.4860 |
| dsr | 0.6306 |
| dsr_p_value | 0.3694 |
| pbo | 0.0454 |
| pbo_combinations | 5000 |
| degradation_slope | -0.8780 |
| prob_oos_loss | 0.0004 |
| noise_null | sharpe_variance_period=0.0000; expected_max_sharpe_annual=1.1464; dsr_p_value=0.1282 |
| ledger_trials | 151 |
| pbo_is_informative | enforced: grid_trials=16 >= 4 |

## Selection-deflated OOS threshold (D-028)

| key | value |
| --- | --- |
| n_obs | 44640 |
| n_trials | 167 |
| alpha | 0.0500 |
| gate | max_sharpe_quantile |
| variance | 0.0000 |
| threshold_annual | 1.5129 |
| expected_max_annual | 1.1952 |
| p_family | 0.3597 |
| oos_sharpe_annual | 1.2306 |
| caliber | ENFORCED at N=167 (the per-strategy bucket): threshold 1.51, margin -0.28.  REPORTED and never enforced at N=21622 (the whole library): threshold 2.02, margin -0.79, p_family 1.0000.  Which N is the gate is R0 / KILL-AR-01, an operator ruling rather than a property of the arithmetic, and both numbers are printed so the ruling stays arguable from the artefact alone. |

## Power of that gate (D-020 + D-028): what it would have detected

| key | value |
| --- | --- |
| standard error of the OOS Sharpe (annual) | 0.4417 |
| gate (max of the two halves) | 1.5129  [selection binds] |
|   D-028 selection threshold | 1.5129 at N=167, alpha=0.05 |
|   D-020 pass line | 1.0000 |
| P(clear | true annual Sharpe = 1.0) | 12.3% |
| P(clear | true annual Sharpe = 1.2) | 23.9% |
| P(clear | true annual Sharpe = 1.5) | 48.8% |
| P(clear | true annual Sharpe = 2.0) | 86.5% |
| not included in the above | cpcv_fraction_negative, pbo, fold_consistency, cost_stress_x2 (so the true joint power is LOWER) |

## The other caliber (R0: reported, never enforced)

| key | value |
| --- | --- |
| n_obs | 44640 |
| n_trials | 21622 |
| alpha | 0.0500 |
| gate | max_sharpe_quantile |
| variance | 0.0000 |
| threshold_annual | 2.0211 |
| expected_max_annual | 1.7867 |
| p_family | 1.0000 |
| oos_sharpe_annual | 1.2306 |
| power | n_trials=21622; alpha=0.0500; se_annual=0.4417; pass_line_annual=1.0000; selection_threshold_annual=2.0211; gate_annual=2.0211; binding=selection; detects=true_sharpe_annual=1.0000; power=0.0104, true_sharpe_annual=1.2000; power=0.0315, true_sharpe_annual=1.5000; power=0.1191, true_sharpe_annual=2.0000; power=0.4810; excludes=cpcv_fraction_negative, pbo, fold_consistency, cost_stress_x2 |

## Cost stress against that gate (same folds, same N, best_key basis)

| key | value |
| --- | --- |
| x1 | oos=1.53 threshold=1.52 margin=0.01 clears=1.00 |
| x1.5 | oos=1.47 threshold=1.52 margin=-0.05 clears=0.00 |
| x2 | oos=1.41 threshold=1.52 margin=-0.11 clears=0.00 |

## Slippage stress against that gate (fee held fixed - the grid the question is about)

| key | value |
| --- | --- |
| slip2 | oos=1.53 threshold=1.52 margin=0.01 clears=1.00 |
| slip4.43 | oos=1.49 threshold=1.52 margin=-0.03 clears=0.00 |
| slip5.5 | oos=1.47 threshold=1.52 margin=-0.05 clears=0.00 |
| slip9.2 | oos=1.41 threshold=1.52 margin=-0.11 clears=0.00 |

## Stability

| key | value |
| --- | --- |
| time_split_sharpes | 0.9784, 0.7639, 1.2850, 1.9252 |
| worst_neighbour_degradation | 0.0627 |
| parameter_neighbourhood | entry_threshold=down=1.58 base=1.67 up=1.56; return_scale=down=1.63 base=1.67 up=1.67; vol_window=down=1.67 base=1.67 up=1.67 |

## Grid (full-sample Sharpe per configuration)

- entry_threshold=0.2, horizons=[168, 336, 720], return_scale=0.2: sharpe=1.63
- entry_threshold=0.2, horizons=[168, 336, 720], return_scale=0.3: sharpe=1.58
- entry_threshold=0.3, horizons=[168, 336, 720], return_scale=0.2: sharpe=1.36
- entry_threshold=0.3, horizons=[24, 72, 168], return_scale=0.2: sharpe=1.13
- entry_threshold=0.3, horizons=[168, 336, 720], return_scale=0.3: sharpe=1.09
- entry_threshold=0.3, horizons=[24, 72, 168], return_scale=0.3: sharpe=1.04
- entry_threshold=0.2, horizons=[24, 72, 168], return_scale=0.3: sharpe=0.99
- entry_threshold=0.2, horizons=[24, 72, 168], return_scale=0.2: sharpe=0.97
- entry_threshold=0.3, horizons=[5, 20, 50], return_scale=0.3: sharpe=0.69
- entry_threshold=0.2, horizons=[5, 20, 50], return_scale=0.3: sharpe=0.54
- entry_threshold=0.3, horizons=[5, 20, 50], return_scale=0.2: sharpe=0.53
- entry_threshold=0.2, horizons=[336, 720, 1440], return_scale=0.3: sharpe=0.53
- entry_threshold=0.2, horizons=[336, 720, 1440], return_scale=0.2: sharpe=0.45
- entry_threshold=0.3, horizons=[336, 720, 1440], return_scale=0.2: sharpe=0.41
- entry_threshold=0.2, horizons=[5, 20, 50], return_scale=0.2: sharpe=0.41
- entry_threshold=0.3, horizons=[336, 720, 1440], return_scale=0.3: sharpe=0.38

## Cost stress (Sharpe)

| key | value |
| --- | --- |
| x1 | 1.6670 |
| x1.5 | 1.6082 |
| x2 | 1.5493 |

## Slippage stress (Sharpe; fee fixed)

| key | value |
| --- | --- |
| slip2 | 1.6670 |
| slip4.43 | 1.6262 |
| slip5.5 | 1.6082 |
| slip9.2 | 1.5459 |

## Same book under close_to_close

| key | value |
| --- | --- |
| annualized_sharpe | 1.6504 |

## Verdict

| key | value |
| --- | --- |
| verdict | FAIL |
| reasons | oos_sharpe 1.23 < the deflated threshold 1.51 at 167 trials, p_family=0.3597 |
