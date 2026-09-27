# Validation: carry — FAIL

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
| window_bars | 72 |
| mode | rank |
| scale | 0.0001 |
| cross_sectional | yes |
| winsor_pct | 0.1000 |
| entry_threshold | 0.2000 |
| min_symbols | 5 |

## Full sample

| key | value |
| --- | --- |
| bars | 49312 |
| gross_return | 1.1597 |
| net_return | 3.7454 |
| annualized_sharpe | 0.8761 |
| annualized_sharpe_gross | 0.5376 |
| max_drawdown | -0.5426 |
| average_absolute_exposure | 1.8242 |
| turnover_units | 1440.8 |
| nonzero_target_bars | 49312 |
| hit_rate | 0.5046 |
| cost_share_of_gross | -0.6291 |
| guards | replayed=yes; gross_capped_bars=11940; daily_loss_pause_bars=284; bars=49312; min_margin_buffer=94.4219; liquidation_touches=0 |

## Walk-forward (out of sample)

| key | value |
| --- | --- |
| folds | 5 |
| oos_sharpe | 0.4576 |
| oos_windows | 62 |
| oos_window_sharpe_q10 | -3.5390 |
| oos_return | 0.7080 |
| oos_max_drawdown | -0.5426 |
| oos_bars | 45312 |
| oos_t_stat | 1.0359 |
| oos_t_lags | 15 |
| fold_sharpes | 0.4631, -0.2858, 0.5867, 1.3791, -0.0225 |
| fold_consistency | 0.6000 |
| selection_consistent | yes |
| oos_is_full_sample_tail | yes |
| best_key_oos_sharpe | 0.4576 |

## CPCV

| key | value |
| --- | --- |
| paths | 15 |
| oos_sharpe_mean | 0.8603 |
| oos_sharpe_q05 | -0.3775 |
| oos_sharpe_min | -0.3776 |
| fraction_negative | 0.2667 |
| embargo | 50 bars, which is shorter than the model's feature lookback (tsmom max(horizons)=720, AlphaModel.warmup_bars 1442).  Training bars AFTER a test block are therefore computed from a window covering it, and `cpcv_evaluate` picks parameters on exactly those bars.  The returns stay causal, so this is selection contamination rather than look-ahead - it makes `fraction_negative`, one of D-020's hard gates, easier to pass than it should be.  Open boundary on the record: see `cpcv_splits`' docstring and docs/analysis/2026-09-13-full-repo-review.md. |

## Multiple testing

| key | value |
| --- | --- |
| n_trials | 5 |
| grid_trials | 1 |
| grid_effective_trials | 1.0000 |
| prior_trials | 0 |
| sharpe_variance_period | 0.0000 |
| candidate_sharpe_annual | 0.8761 |
| expected_max_sharpe_annual | 0.2345 |
| dsr | 0.9361 |
| dsr_p_value | 0.0639 |
| pbo | n/a |
| pbo_combinations | n/a |
| degradation_slope | n/a |
| prob_oos_loss | n/a |
| noise_null | sharpe_variance_period=0.0000; expected_max_sharpe_annual=0.5025; dsr_p_value=0.1876 |
| ledger_trials | 4 |
| pbo_is_informative | NOT informative and NOT enforced at grid_trials=1: CSCV ranks configurations against each other, and with fewer than four it only says that two curves traded places across sub-periods.  `verdict.decide` skips the gate below four, so a move in this number is not a cost or a gain either. |

## Selection-deflated OOS threshold (D-028)

| key | value |
| --- | --- |
| n_obs | 45312 |
| n_trials | 5 |
| alpha | 0.0500 |
| gate | max_sharpe_quantile |
| variance | 0.0000 |
| threshold_annual | 1.0195 |
| expected_max_annual | 0.5244 |
| p_family | 0.5537 |
| oos_sharpe_annual | 0.4576 |

## Cost stress against that gate (same folds, same N, best_key basis)

| key | value |
| --- | --- |
| x1 | oos=0.46 threshold=1.02 margin=-0.56 clears=0.00 |
| x1.5 | oos=0.24 threshold=1.02 margin=-0.78 clears=0.00 |
| x2 | oos=0.01 threshold=1.02 margin=-1.00 clears=0.00 |

## Stability

| key | value |
| --- | --- |
| time_split_sharpes | 0.0960, 0.9924, 0.9113, -0.0831 |
| worst_neighbour_degradation | 0.3174 |
| parameter_neighbourhood | entry_threshold=down=0.85 base=0.88 up=0.88; window_bars=down=0.60 base=0.88 up=0.72 |

## Grid (full-sample Sharpe per configuration)

- single configuration: sharpe=0.88

## Cost stress (Sharpe)

| key | value |
| --- | --- |
| x1 | 0.8761 |
| x1.5 | 0.6588 |
| x2 | 0.4419 |

## Slippage stress (Sharpe; fee fixed)

| key | value |
| --- | --- |
| slip2 | 0.8761 |
| slip5.5 | 0.6588 |
| slip9.2 | 0.4295 |

## Same book under close_to_close

| key | value |
| --- | --- |
| annualized_sharpe | 0.8552 |

## Verdict

| key | value |
| --- | --- |
| verdict | FAIL |
| reasons | oos_sharpe 0.46 < 0.5, oos_sharpe 0.46 < the deflated threshold 1.02 at 5 trials, p_family=0.5537, cpcv fraction_negative 0.27 > 0.1 |
