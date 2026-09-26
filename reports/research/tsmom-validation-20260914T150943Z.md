# Validation: tsmom — FAIL

## Range

| key | value |
| --- | --- |
| start | 2021-01-31 01:00:00+00:00 |
| end | 2026-09-13 19:00:00+00:00 |
| bars | 49243 |

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
| bars | 49243 |
| gross_return | 128.6 |
| net_return | 85.5723 |
| annualized_sharpe | 1.6722 |
| annualized_sharpe_gross | 1.7974 |
| max_drawdown | -0.4029 |
| average_absolute_exposure | 1.3447 |
| turnover_units | 539.8 |
| nonzero_target_bars | 49243 |
| hit_rate | 0.5124 |
| cost_share_of_gross | 0.0698 |
| guards | replayed=yes; gross_capped_bars=4070; daily_loss_pause_bars=491; bars=49243; min_margin_buffer=97.1690; liquidation_touches=0 |

## Walk-forward (out of sample)

| key | value |
| --- | --- |
| folds | 5 |
| oos_sharpe | 1.4006 |
| oos_windows | 62 |
| oos_window_sharpe_q10 | -2.0764 |
| oos_return | 25.2747 |
| oos_max_drawdown | -0.3615 |
| oos_bars | 45243 |
| oos_t_stat | 3.2078 |
| oos_t_lags | 15 |
| fold_sharpes | 1.2068, 0.1173, 2.3435, 1.2364, 2.0277 |
| fold_consistency | 1.0000 |
| selection_consistent | no |
| oos_is_full_sample_tail | no |
| best_key_oos_sharpe | 1.5916 |

## CPCV

| key | value |
| --- | --- |
| paths | 15 |
| oos_sharpe_mean | 1.6330 |
| oos_sharpe_q05 | 1.1883 |
| oos_sharpe_min | 1.1501 |
| fraction_negative | 0.0000 |
| embargo | 50 bars, which is shorter than the model's feature lookback (tsmom max(horizons)=720, AlphaModel.warmup_bars 1442).  Training bars AFTER a test block are therefore computed from a window covering it, and `cpcv_evaluate` picks parameters on exactly those bars.  The returns stay causal, so this is selection contamination rather than look-ahead - it makes `fraction_negative`, one of D-020's hard gates, easier to pass than it should be.  Open boundary on the record: see `cpcv_splits`' docstring and docs/analysis/2026-09-13-full-repo-review.md. |

## Multiple testing

| key | value |
| --- | --- |
| n_trials | 259 |
| grid_trials | 5 |
| grid_effective_trials | 2.0000 |
| prior_trials | 152 |
| sharpe_variance_period | 0.0000 |
| candidate_sharpe_annual | 1.6722 |
| expected_max_sharpe_annual | 1.6751 |
| dsr | 0.4972 |
| dsr_p_value | 0.5028 |
| pbo | 0.3662 |
| pbo_combinations | 5000 |
| degradation_slope | -0.9768 |
| prob_oos_loss | 0.0000 |
| noise_null | sharpe_variance_period=0.0000; expected_max_sharpe_annual=1.2001; dsr_p_value=0.1312 |
| ledger_trials | 102 |
| pbo_is_informative | enforced: grid_trials=5 >= 4 |

## Selection-deflated OOS threshold (D-028)

| key | value |
| --- | --- |
| n_obs | 45243 |
| n_trials | 259 |
| alpha | 0.0500 |
| gate | max_sharpe_quantile |
| variance | 0.0000 |
| threshold_annual | 1.5571 |
| expected_max_annual | 1.2522 |
| p_family | 0.1702 |
| oos_sharpe_annual | 1.4006 |

## Cost stress against that gate (same folds, same N, best_key basis)

| key | value |
| --- | --- |
| x1 | oos=1.59 threshold=1.56 margin=0.03 clears=1.00 |
| x1.5 | oos=1.53 threshold=1.56 margin=-0.03 clears=0.00 |
| x2 | oos=1.47 threshold=1.56 margin=-0.09 clears=0.00 |

## Stability

| key | value |
| --- | --- |
| time_split_sharpes | 0.8905, 1.3339, 1.7019, 1.6986 |
| worst_neighbour_degradation | 0.0682 |
| parameter_neighbourhood | entry_threshold=down=1.57 base=1.67 up=1.56; return_scale=down=1.63 base=1.67 up=1.67; vol_window=down=1.67 base=1.67 up=1.67 |

## Grid (full-sample Sharpe per configuration)

- entry_threshold=0.2: sharpe=1.67
- entry_threshold=0.24: sharpe=1.65
- entry_threshold=0.18: sharpe=1.57
- entry_threshold=0.22: sharpe=1.56
- entry_threshold=0.16: sharpe=1.44

## Cost stress (Sharpe)

| key | value |
| --- | --- |
| x1 | 1.6722 |
| x1.5 | 1.6134 |
| x2 | 1.5547 |

## Slippage stress (Sharpe; fee fixed)

| key | value |
| --- | --- |
| slip2 | 1.6722 |
| slip5.5 | 1.6134 |
| slip9.2 | 1.5513 |

## Same book under close_to_close

| key | value |
| --- | --- |
| annualized_sharpe | 1.6557 |

## Verdict

| key | value |
| --- | --- |
| verdict | FAIL |
| reasons | oos_sharpe 1.40 < the deflated threshold 1.56 at 259 trials, p_family=0.1702, pbo 0.37 > 0.3 |
