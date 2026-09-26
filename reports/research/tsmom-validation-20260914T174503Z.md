# Validation: tsmom — PASS

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
| gross_return | 126.2 |
| net_return | 84.0126 |
| annualized_sharpe | 1.6672 |
| annualized_sharpe_gross | 1.7923 |
| max_drawdown | -0.4029 |
| average_absolute_exposure | 1.3447 |
| turnover_units | 539.7 |
| nonzero_target_bars | 49247 |
| hit_rate | 0.5123 |
| cost_share_of_gross | 0.0699 |
| guards | replayed=yes; gross_capped_bars=4069; daily_loss_pause_bars=491; bars=49247; min_margin_buffer=97.1690; liquidation_touches=0 |

## Walk-forward (out of sample)

| key | value |
| --- | --- |
| folds | 5 |
| oos_sharpe | 1.5861 |
| oos_windows | 62 |
| oos_window_sharpe_q10 | -1.5800 |
| oos_return | 44.3085 |
| oos_max_drawdown | -0.4029 |
| oos_bars | 45247 |
| oos_t_stat | 3.6230 |
| oos_t_lags | 15 |
| fold_sharpes | 1.8283, 0.0004, 2.5745, 1.2050, 2.2001 |
| fold_consistency | 1.0000 |
| selection_consistent | yes |
| oos_is_full_sample_tail | yes |
| best_key_oos_sharpe | 1.5861 |

## CPCV

| key | value |
| --- | --- |
| paths | 15 |
| oos_sharpe_mean | 1.5996 |
| oos_sharpe_q05 | 1.2076 |
| oos_sharpe_min | 1.1389 |
| fraction_negative | 0.0000 |
| embargo | 50 bars, which is shorter than the model's feature lookback (tsmom max(horizons)=720, AlphaModel.warmup_bars 1442).  Training bars AFTER a test block are therefore computed from a window covering it, and `cpcv_evaluate` picks parameters on exactly those bars.  The returns stay causal, so this is selection contamination rather than look-ahead - it makes `fraction_negative`, one of D-020's hard gates, easier to pass than it should be.  Open boundary on the record: see `cpcv_splits`' docstring and docs/analysis/2026-09-13-full-repo-review.md. |

## Multiple testing

| key | value |
| --- | --- |
| n_trials | 111 |
| grid_trials | 2 |
| grid_effective_trials | 2.0000 |
| prior_trials | 0 |
| sharpe_variance_period | 0.0000 |
| candidate_sharpe_annual | 1.6672 |
| expected_max_sharpe_annual | 1.5014 |
| dsr | 0.6531 |
| dsr_p_value | 0.3469 |
| pbo | 0.2182 |
| pbo_combinations | 5000 |
| degradation_slope | -0.9940 |
| prob_oos_loss | 0.0000 |
| noise_null | sharpe_variance_period=0.0000; expected_max_sharpe_annual=1.0813; dsr_p_value=0.0821 |
| ledger_trials | 109 |
| pbo_is_informative | NOT informative and NOT enforced at grid_trials=2: CSCV ranks configurations against each other, and with fewer than four it only says that two curves traded places across sub-periods.  `verdict.decide` skips the gate below four, so a move in this number is not a cost or a gain either. |

## Selection-deflated OOS threshold (D-028)

| key | value |
| --- | --- |
| n_obs | 45247 |
| n_trials | 111 |
| alpha | 0.0500 |
| gate | max_sharpe_quantile |
| variance | 0.0000 |
| threshold_annual | 1.4559 |
| expected_max_annual | 1.1282 |
| p_family | 0.0169 |
| oos_sharpe_annual | 1.5861 |

## Cost stress against that gate (same folds, same N, best_key basis)

| key | value |
| --- | --- |
| x1 | oos=1.59 threshold=1.46 margin=0.13 clears=1.00 |
| x1.5 | oos=1.53 threshold=1.46 margin=0.07 clears=1.00 |
| x2 | oos=1.47 threshold=1.46 margin=0.01 clears=1.00 |

## Stability

| key | value |
| --- | --- |
| time_split_sharpes | 1.3574, 1.4465, 1.6876, 1.8644 |
| worst_neighbour_degradation | 0.0658 |
| parameter_neighbourhood | entry_threshold=down=1.56 base=1.67 up=1.56; return_scale=down=1.63 base=1.67 up=1.67; vol_window=down=1.67 base=1.67 up=1.67 |

## Grid (full-sample Sharpe per configuration)

- crowding_window=72: sharpe=1.67
- crowding_window=0: sharpe=1.59

## Cost stress (Sharpe)

| key | value |
| --- | --- |
| x1 | 1.6672 |
| x1.5 | 1.6084 |
| x2 | 1.5497 |

## Slippage stress (Sharpe; fee fixed)

| key | value |
| --- | --- |
| slip2 | 1.6672 |
| slip5.5 | 1.6084 |
| slip9.2 | 1.5463 |

## Same book under close_to_close

| key | value |
| --- | --- |
| annualized_sharpe | 1.6508 |

## Verdict

| key | value |
| --- | --- |
| verdict | PASS |
| reasons | - |
