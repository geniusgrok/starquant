# Validation: xsmom — FAIL

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
| horizons | 168, 336, 720 |
| horizon_weights | 0.2000, 0.3000, 0.5000 |
| skip_bars | 0 |
| risk_adjusted | no |
| score_scale | 0.1500 |
| z_scale | 1.5000 |
| vol_window | 336 |
| relative_weight | 0.7500 |
| rank_weight | 0.2500 |
| entry_threshold | 0.3000 |
| min_symbols | 3 |

## Full sample

| key | value |
| --- | --- |
| bars | 49312 |
| gross_return | 0.1368 |
| net_return | 0.3839 |
| annualized_sharpe | 0.3713 |
| annualized_sharpe_gross | 0.3045 |
| max_drawdown | -0.7101 |
| average_absolute_exposure | 1.5173 |
| turnover_units | 546.4 |
| nonzero_target_bars | 49312 |
| hit_rate | 0.4948 |
| cost_share_of_gross | -0.2192 |
| guards | replayed=yes; gross_capped_bars=5628; daily_loss_pause_bars=494; bars=49312; min_margin_buffer=95.6227; liquidation_touches=0 |

## Walk-forward (out of sample)

| key | value |
| --- | --- |
| folds | 5 |
| oos_sharpe | 0.3976 |
| oos_windows | 62 |
| oos_window_sharpe_q10 | -3.8530 |
| oos_return | 0.4505 |
| oos_max_drawdown | -0.7101 |
| oos_bars | 45312 |
| oos_t_stat | 0.8837 |
| oos_t_lags | 15 |
| fold_sharpes | 1.1350, -0.9790, 0.1577, -0.3259, 1.5474 |
| fold_consistency | 0.6000 |
| selection_consistent | yes |
| oos_is_full_sample_tail | yes |
| best_key_oos_sharpe | 0.3976 |

## CPCV

| key | value |
| --- | --- |
| paths | 15 |
| oos_sharpe_mean | 0.3621 |
| oos_sharpe_q05 | -0.4835 |
| oos_sharpe_min | -0.5203 |
| fraction_negative | 0.2667 |
| embargo | 50 bars, which is shorter than the model's feature lookback (tsmom max(horizons)=720, AlphaModel.warmup_bars 1442).  Training bars AFTER a test block are therefore computed from a window covering it, and `cpcv_evaluate` picks parameters on exactly those bars.  The returns stay causal, so this is selection contamination rather than look-ahead - it makes `fraction_negative`, one of D-020's hard gates, easier to pass than it should be.  Open boundary on the record: see `cpcv_splits`' docstring and docs/analysis/2026-09-13-full-repo-review.md. |

## Multiple testing

| key | value |
| --- | --- |
| n_trials | 1 |
| grid_trials | 1 |
| grid_effective_trials | 1.0000 |
| prior_trials | 0 |
| sharpe_variance_period | 0.0000 |
| candidate_sharpe_annual | 0.3713 |
| expected_max_sharpe_annual | 0.0000 |
| dsr | 0.8111 |
| dsr_p_value | 0.1889 |
| pbo | n/a |
| pbo_combinations | n/a |
| degradation_slope | n/a |
| prob_oos_loss | n/a |
| noise_null | sharpe_variance_period=0.0000; expected_max_sharpe_annual=0.0000; dsr_p_value=0.1889 |
| ledger_trials | 0 |
| pbo_is_informative | NOT informative and NOT enforced at grid_trials=1: CSCV ranks configurations against each other, and with fewer than four it only says that two curves traded places across sub-periods.  `verdict.decide` skips the gate below four, so a move in this number is not a cost or a gain either. |

## Selection-deflated OOS threshold (D-028)

| key | value |
| --- | --- |
| n_obs | 45312 |
| n_trials | 1 |
| alpha | 0.0500 |
| gate | max_sharpe_quantile |
| variance | 0.0000 |
| threshold_annual | 0.0000 |
| expected_max_annual | 0.0000 |
| p_family | 0.1828 |
| oos_sharpe_annual | 0.3976 |

## Cost stress against that gate (same folds, same N, best_key basis)

| key | value |
| --- | --- |
| x1 | oos=0.40 threshold=0.00 margin=0.40 clears=1.00 |
| x1.5 | oos=0.33 threshold=0.00 margin=0.33 clears=1.00 |
| x2 | oos=0.27 threshold=0.00 margin=0.27 clears=1.00 |

## Stability

| key | value |
| --- | --- |
| time_split_sharpes | 0.7882, -0.3241, -0.1544, 1.1089 |
| worst_neighbour_degradation | 0.0394 |
| parameter_neighbourhood | entry_threshold=down=0.46 base=0.37 up=0.38; skip_bars=down=n/a base=0.37 up=0.36; z_scale=down=0.37 base=0.37 up=0.37 |

## Grid (full-sample Sharpe per configuration)

- single configuration: sharpe=0.37

## Cost stress (Sharpe)

| key | value |
| --- | --- |
| x1 | 0.3713 |
| x1.5 | 0.3061 |
| x2 | 0.2413 |

## Slippage stress (Sharpe; fee fixed)

| key | value |
| --- | --- |
| slip2 | 0.3713 |
| slip5.5 | 0.3061 |
| slip9.2 | 0.2376 |

## Same book under close_to_close

| key | value |
| --- | --- |
| annualized_sharpe | 0.3296 |

## Verdict

| key | value |
| --- | --- |
| verdict | FAIL |
| reasons | oos_sharpe 0.40 < 0.5, cpcv fraction_negative 0.27 > 0.1 |
