# Validation: xsmom — FAIL

## Range

| key | value |
| --- | --- |
| start | 2021-02-01 01:00:00+00:00 |
| end | 2026-09-16 16:00:00+00:00 |
| bars | 49288 |

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
| horizons | 24, 72, 168 |
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
| gross_return | 2.2078 |
| net_return | 1.1434 |
| annualized_sharpe | 0.5211 |
| annualized_sharpe_gross | 0.6660 |
| max_drawdown | -0.7597 |
| average_absolute_exposure | 1.7678 |
| turnover_units | 1242.8 |
| nonzero_target_bars | 49312 |
| hit_rate | 0.5010 |
| cost_share_of_gross | 0.2177 |
| guards | replayed=yes; gross_capped_bars=11920; daily_loss_pause_bars=429; bars=49312; min_margin_buffer=95.6172; liquidation_touches=0 |

## Walk-forward (out of sample)

| key | value |
| --- | --- |
| folds | 5 |
| oos_sharpe | 0.1449 |
| oos_windows | 62 |
| oos_window_sharpe_q10 | -4.9037 |
| oos_return | -0.2113 |
| oos_max_drawdown | -0.7908 |
| oos_bars | 45288 |
| oos_t_stat | 0.3260 |
| oos_t_lags | 15 |
| fold_sharpes | 0.2720, -0.5056, 1.4201, -1.5930, 1.1353 |
| fold_consistency | 0.6000 |
| selection_consistent | no |
| oos_is_full_sample_tail | no |
| best_key_oos_sharpe | 0.4704 |

## CPCV

| key | value |
| --- | --- |
| paths | 15 |
| oos_sharpe_mean | 0.2954 |
| oos_sharpe_q05 | -0.5547 |
| oos_sharpe_min | -0.5625 |
| fraction_negative | 0.2667 |
| embargo | 50 bars, which is shorter than the model's feature lookback (tsmom max(horizons)=720, AlphaModel.warmup_bars 1442).  Training bars AFTER a test block are therefore computed from a window covering it, and `cpcv_evaluate` picks parameters on exactly those bars.  The returns stay causal, so this is selection contamination rather than look-ahead - it makes `fraction_negative`, one of D-020's hard gates, easier to pass than it should be.  Open boundary on the record: see `cpcv_splits`' docstring and docs/analysis/2026-09-13-full-repo-review.md. |

## Multiple testing

| key | value |
| --- | --- |
| n_trials | 9 |
| grid_trials | 8 |
| grid_effective_trials | 4.0000 |
| prior_trials | 0 |
| sharpe_variance_period | 0.0000 |
| candidate_sharpe_annual | 0.5093 |
| expected_max_sharpe_annual | 0.2868 |
| dsr | 0.7012 |
| dsr_p_value | 0.2988 |
| pbo | 0.5758 |
| pbo_combinations | 5000 |
| degradation_slope | -0.9387 |
| prob_oos_loss | 0.3576 |
| noise_null | sharpe_variance_period=0.0000; expected_max_sharpe_annual=0.6410; dsr_p_value=0.6227 |
| ledger_trials | 1 |
| pbo_is_informative | enforced: grid_trials=8 >= 4 |

## Selection-deflated OOS threshold (D-028)

| key | value |
| --- | --- |
| n_obs | 45288 |
| n_trials | 9 |
| alpha | 0.0500 |
| gate | max_sharpe_quantile |
| variance | 0.0000 |
| threshold_annual | 1.1132 |
| expected_max_annual | 0.6688 |
| p_family | 0.9846 |
| oos_sharpe_annual | 0.1449 |

## Cost stress against that gate (same folds, same N, best_key basis)

| key | value |
| --- | --- |
| x1 | oos=0.47 threshold=1.11 margin=-0.64 clears=0.00 |
| x1.5 | oos=0.31 threshold=1.11 margin=-0.80 clears=0.00 |
| x2 | oos=0.15 threshold=1.11 margin=-0.96 clears=0.00 |

## Stability

| key | value |
| --- | --- |
| time_split_sharpes | 0.1354, 0.6435, -0.3614, 0.2809 |
| worst_neighbour_degradation | 0.1528 |
| parameter_neighbourhood | entry_threshold=down=0.46 base=0.52 up=0.44; skip_bars=down=n/a base=0.52 up=0.51; z_scale=down=0.52 base=0.52 up=0.52 |

## Grid (full-sample Sharpe per configuration)

- horizons=[24, 72, 168], risk_adjusted=False, skip_bars=0: sharpe=0.51
- horizons=[24, 72, 168], risk_adjusted=True, skip_bars=0: sharpe=0.50
- horizons=[168, 336, 720], risk_adjusted=False, skip_bars=0: sharpe=0.36
- horizons=[168, 336, 720], risk_adjusted=True, skip_bars=0: sharpe=0.20
- horizons=[168, 336, 720], risk_adjusted=True, skip_bars=24: sharpe=0.19
- horizons=[168, 336, 720], risk_adjusted=False, skip_bars=24: sharpe=0.17
- horizons=[24, 72, 168], risk_adjusted=False, skip_bars=24: sharpe=0.14
- horizons=[24, 72, 168], risk_adjusted=True, skip_bars=24: sharpe=-0.08

## Cost stress (Sharpe)

| key | value |
| --- | --- |
| x1 | 0.5211 |
| x1.5 | 0.3624 |
| x2 | 0.2061 |

## Slippage stress (Sharpe; fee fixed)

| key | value |
| --- | --- |
| slip2 | 0.5211 |
| slip5.5 | 0.3624 |
| slip9.2 | 0.1972 |

## Same book under close_to_close

| key | value |
| --- | --- |
| annualized_sharpe | 0.5002 |

## Verdict

| key | value |
| --- | --- |
| verdict | FAIL |
| reasons | oos_sharpe 0.14 < 0.5, oos_sharpe 0.14 < the deflated threshold 1.11 at 9 trials, p_family=0.9846, cpcv fraction_negative 0.27 > 0.1, pbo 0.58 > 0.3 |
