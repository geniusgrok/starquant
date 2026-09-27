# Validation: tsmom — WEAK_PASS

## Range

| key | value |
| --- | --- |
| start | 2021-01-31 01:00:00+00:00 |
| end | 2026-09-13 23:00:00+00:00 |
| bars | 49247 |

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
| bars | 49247 |
| gross_return | 126.4 |
| net_return | 84.0876 |
| annualized_sharpe | 1.6665 |
| annualized_sharpe_gross | 1.7918 |
| max_drawdown | -0.4029 |
| average_absolute_exposure | 1.3444 |
| turnover_units | 540.0 |
| nonzero_target_bars | 49247 |
| hit_rate | 0.5123 |
| cost_share_of_gross | 0.0700 |
| guards | replayed=yes; gross_capped_bars=4033; daily_loss_pause_bars=491; bars=49247; min_margin_buffer=97.1690; liquidation_touches=0 |

## Walk-forward (out of sample)

| key | value |
| --- | --- |
| folds | 5 |
| oos_sharpe | 1.5854 |
| oos_windows | 62 |
| oos_window_sharpe_q10 | -1.5800 |
| oos_return | 44.3485 |
| oos_max_drawdown | -0.4029 |
| oos_bars | 45247 |
| oos_t_stat | 3.6276 |
| oos_t_lags | 15 |
| fold_sharpes | 1.7887, 0.0004, 2.5745, 1.2230, 2.2200 |
| fold_consistency | 1.0000 |
| selection_consistent | yes |
| oos_is_full_sample_tail | yes |
| best_key_oos_sharpe | 1.5854 |
| selection_exercised | NO fold had a choice to make (single configuration, or every fold picked the same one), so the OOS Sharpe above is the TAIL OF ONE FULL-SAMPLE SERIES, not a selection's out-of-sample record.  D-043 caps such a report at WEAK_PASS: the number stands, the claim that a selection survived out of sample does not.  `registry.py` still admits WEAK_PASS to live use. |

## CPCV

| key | value |
| --- | --- |
| paths | 15 |
| oos_sharpe_mean | 1.6150 |
| oos_sharpe_q05 | 1.1891 |
| oos_sharpe_min | 1.1278 |
| fraction_negative | 0.0000 |
| embargo | 50 bars, which is shorter than the model's feature lookback (tsmom max(horizons)=720, AlphaModel.warmup_bars 1442).  Training bars AFTER a test block are therefore computed from a window covering it, and `cpcv_evaluate` picks parameters on exactly those bars.  The returns stay causal, so this is selection contamination rather than look-ahead - it makes `fraction_negative`, one of D-020's hard gates, easier to pass than it should be.  Open boundary on the record: see `cpcv_splits`' docstring and docs/analysis/2026-09-13-full-repo-review.md. |

## Multiple testing

| key | value |
| --- | --- |
| n_trials | 259 |
| grid_trials | 2 |
| grid_effective_trials | 2.0000 |
| prior_trials | 152 |
| sharpe_variance_period | 0.0000 |
| candidate_sharpe_annual | 1.6665 |
| expected_max_sharpe_annual | 1.6560 |
| dsr | 0.5100 |
| dsr_p_value | 0.4900 |
| pbo | 0.2116 |
| pbo_combinations | 5000 |
| degradation_slope | -0.9924 |
| prob_oos_loss | 0.0000 |
| noise_null | sharpe_variance_period=0.0000; expected_max_sharpe_annual=1.2001; dsr_p_value=0.1341 |
| ledger_trials | 105 |
| pbo_is_informative | NOT informative and NOT enforced at grid_trials=2: CSCV ranks configurations against each other, and with fewer than four it only says that two curves traded places across sub-periods.  `verdict.decide` skips the gate below four, so a move in this number is not a cost or a gain either. |

## Selection-deflated OOS threshold (D-028)

| key | value |
| --- | --- |
| n_obs | 45247 |
| n_trials | 259 |
| alpha | 0.0500 |
| gate | max_sharpe_quantile |
| variance | 0.0000 |
| threshold_annual | 1.5571 |
| expected_max_annual | 1.2522 |
| p_family | 0.0393 |
| oos_sharpe_annual | 1.5854 |
| caliber | ENFORCED at N=259 (the per-strategy bucket): threshold 1.56, margin +0.03.  REPORTED and never enforced at N=1769 (the whole library): threshold 1.77, margin -0.18, p_family 0.2396.  Which N is the gate is R0 / KILL-AR-01, an operator ruling rather than a property of the arithmetic, and both numbers are printed so the ruling stays arguable from the artefact alone. |

## The other caliber (R0: reported, never enforced)

| key | value |
| --- | --- |
| n_obs | 45247 |
| n_trials | 1769 |
| alpha | 0.0500 |
| gate | max_sharpe_quantile |
| variance | 0.0000 |
| threshold_annual | 1.7672 |
| expected_max_annual | 1.5005 |
| p_family | 0.2396 |
| oos_sharpe_annual | 1.5854 |

## Cost stress against that gate (same folds, same N, best_key basis)

| key | value |
| --- | --- |
| x1 | oos=1.59 threshold=1.56 margin=0.03 clears=1.00 |
| x1.5 | oos=1.53 threshold=1.56 margin=-0.03 clears=0.00 |
| x2 | oos=1.47 threshold=1.56 margin=-0.09 clears=0.00 |

## Stability

| key | value |
| --- | --- |
| time_split_sharpes | 1.3266, 1.4465, 1.7019, 1.8804 |
| worst_neighbour_degradation | 0.0713 |
| parameter_neighbourhood | entry_threshold=down=1.56 base=1.67 up=1.55; return_scale=down=1.63 base=1.67 up=1.66; vol_window=down=1.67 base=1.67 up=1.67 |

## Grid (full-sample Sharpe per configuration)

- crowding_window=72: sharpe=1.67
- crowding_window=0: sharpe=1.59

## Cost stress (Sharpe)

| key | value |
| --- | --- |
| x1 | 1.6665 |
| x1.5 | 1.6078 |
| x2 | 1.5490 |

## Slippage stress (Sharpe; fee fixed)

| key | value |
| --- | --- |
| slip2 | 1.6665 |
| slip5.5 | 1.6078 |
| slip9.2 | 1.5457 |

## Same book under close_to_close

| key | value |
| --- | --- |
| annualized_sharpe | 1.6501 |

## Verdict

| key | value |
| --- | --- |
| verdict | WEAK_PASS |
| reasons | oos_is_full_sample_tail: no fold had a choice to make (single configuration, or every fold picked the same one), so this OOS is the tail of one full-sample series |
