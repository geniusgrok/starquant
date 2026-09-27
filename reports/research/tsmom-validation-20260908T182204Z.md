# Validation: tsmom — PASS

## Range

| key | value |
| --- | --- |
| start | 2021-01-31 01:00:00+00:00 |
| end | 2026-09-08 16:00:00+00:00 |
| bars | 49120 |

## Holdout (KILL-006)

| key | value |
| --- | --- |
| months | 0 |
| note | no tail reserved: every bar was available to this run |

## Book guards / exits (the layers the loop applies)

| key | value |
| --- | --- |
| guards | max_weight=0.1500; max_gross=2.0000; daily_loss_pause=-0.0500 |
| exits | stop_loss=6.0000; trailing_stop=0.0000; take_profit=6.0000; cooldown_bars=24; vol_halflife=48; bars_per_day=24; min_unit=0.0050; unit_mode=entry; regime_window=0; regime_er_cut=0.0500; regime_tp_scale=0.5000; regime_side=low |

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
| bars | 49120 |
| gross_return | 25.0048 |
| net_return | 18.4295 |
| annualized_sharpe | 1.8596 |
| annualized_sharpe_gross | 2.0269 |
| max_drawdown | -0.2145 |
| average_absolute_exposure | 0.8489 |
| turnover_units | 415.2 |
| nonzero_target_bars | 49120 |
| hit_rate | 0.5128 |
| cost_share_of_gross | 0.0826 |
| guards | replayed=yes; gross_capped_bars=390; daily_loss_pause_bars=31; bars=49120; min_margin_buffer=98.9903; liquidation_touches=0 |

## Walk-forward (out of sample)

| key | value |
| --- | --- |
| folds | 5 |
| oos_sharpe | 1.8087 |
| oos_windows | 62 |
| oos_window_sharpe_q10 | -1.5188 |
| oos_return | 13.0115 |
| oos_max_drawdown | -0.2145 |
| oos_bars | 45120 |
| oos_t_stat | 4.1203 |
| oos_t_lags | 15 |
| fold_sharpes | 1.8586, 0.5616, 2.7056, 1.3760, 2.5077 |
| fold_consistency | 1.0000 |
| selection_consistent | yes |
| oos_is_full_sample_tail | yes |
| best_key_oos_sharpe | 1.8087 |

## CPCV

| key | value |
| --- | --- |
| paths | 15 |
| oos_sharpe_mean | 1.8608 |
| oos_sharpe_q05 | 1.3121 |
| oos_sharpe_min | 1.1217 |
| fraction_negative | 0.0000 |

## Multiple testing

| key | value |
| --- | --- |
| n_trials | 183 |
| grid_trials | 2 |
| grid_effective_trials | 2.0000 |
| prior_trials | 95 |
| sharpe_variance_period | 0.0000 |
| candidate_sharpe_annual | 1.8596 |
| expected_max_sharpe_annual | 1.7046 |
| dsr | 0.6437 |
| dsr_p_value | 0.3563 |
| pbo | 0.0856 |
| pbo_combinations | 5000 |
| degradation_slope | -0.9608 |
| prob_oos_loss | 0.0000 |
| noise_null | sharpe_variance_period=0.0000; expected_max_sharpe_annual=1.1508; dsr_p_value=0.0460 |
| ledger_trials | 86 |

## Selection-deflated OOS threshold (D-028)

| key | value |
| --- | --- |
| n_obs | 45120 |
| n_trials | 183 |
| alpha | 0.0500 |
| gate | max_sharpe_quantile |
| variance | 0.0000 |
| threshold_annual | 1.5136 |
| expected_max_annual | 1.2005 |
| p_family | 0.0034 |
| oos_sharpe_annual | 1.8087 |

## Stability

| key | value |
| --- | --- |
| time_split_sharpes | 1.6200, 1.4962, 2.0356, 2.0785 |
| worst_neighbour_degradation | 0.1209 |
| parameter_neighbourhood | entry_threshold=down=1.71 base=1.86 up=1.63; return_scale=down=1.76 base=1.86 up=1.81; vol_window=down=1.86 base=1.86 up=1.86 |

## Grid (full-sample Sharpe per configuration)

- crowding_window=72: sharpe=1.86
- crowding_window=0: sharpe=1.72

## Cost stress (Sharpe)

| key | value |
| --- | --- |
| x1 | 1.8596 |
| x1.5 | 1.7760 |
| x2 | 1.6924 |

## Slippage stress (Sharpe; fee fixed)

| key | value |
| --- | --- |
| slip2 | 1.8596 |
| slip5.5 | 1.7760 |
| slip9.2 | 1.6877 |

## Same book under close_to_close

| key | value |
| --- | --- |
| annualized_sharpe | 1.8348 |

## Verdict

| key | value |
| --- | --- |
| verdict | PASS |
| reasons | - |
