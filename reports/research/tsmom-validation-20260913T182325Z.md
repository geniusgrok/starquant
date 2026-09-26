# Validation: tsmom — PASS

## Range

| key | value |
| --- | --- |
| start | 2021-01-31 01:00:00+00:00 |
| end | 2026-09-13 16:00:00+00:00 |
| bars | 49240 |

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
| bars | 49240 |
| gross_return | 128.7 |
| net_return | 85.6414 |
| annualized_sharpe | 1.6725 |
| annualized_sharpe_gross | 1.7977 |
| max_drawdown | -0.4029 |
| average_absolute_exposure | 1.3447 |
| turnover_units | 539.8 |
| nonzero_target_bars | 49240 |
| hit_rate | 0.5124 |
| cost_share_of_gross | 0.0698 |
| guards | replayed=yes; gross_capped_bars=4070; daily_loss_pause_bars=491; bars=49240; min_margin_buffer=97.1690; liquidation_touches=0 |

## Walk-forward (out of sample)

| key | value |
| --- | --- |
| folds | 5 |
| oos_sharpe | 1.5919 |
| oos_windows | 62 |
| oos_window_sharpe_q10 | -1.5800 |
| oos_return | 45.1766 |
| oos_max_drawdown | -0.4029 |
| oos_bars | 45240 |
| oos_t_stat | 3.6419 |
| oos_t_lags | 15 |
| fold_sharpes | 1.7690, 0.0310, 2.5835, 1.2217, 2.2400 |
| fold_consistency | 1.0000 |
| selection_consistent | yes |
| oos_is_full_sample_tail | yes |
| best_key_oos_sharpe | 1.5919 |

## CPCV

| key | value |
| --- | --- |
| paths | 15 |
| oos_sharpe_mean | 1.6057 |
| oos_sharpe_q05 | 1.1850 |
| oos_sharpe_min | 1.1434 |
| fraction_negative | 0.0000 |

## Multiple testing

| key | value |
| --- | --- |
| n_trials | 242 |
| grid_trials | 2 |
| grid_effective_trials | 2.0000 |
| prior_trials | 152 |
| sharpe_variance_period | 0.0000 |
| candidate_sharpe_annual | 1.6725 |
| expected_max_sharpe_annual | 1.7562 |
| dsr | 0.4212 |
| dsr_p_value | 0.5788 |
| pbo | 0.2082 |
| pbo_combinations | 5000 |
| degradation_slope | -0.9901 |
| prob_oos_loss | 0.0000 |
| noise_null | sharpe_variance_period=0.0000; expected_max_sharpe_annual=1.1910; dsr_p_value=0.1265 |
| ledger_trials | 88 |

## Selection-deflated OOS threshold (D-028)

| key | value |
| --- | --- |
| n_obs | 45240 |
| n_trials | 242 |
| alpha | 0.0500 |
| gate | max_sharpe_quantile |
| variance | 0.0000 |
| threshold_annual | 1.5493 |
| expected_max_annual | 1.2427 |
| p_family | 0.0348 |
| oos_sharpe_annual | 1.5919 |

## Stability

| key | value |
| --- | --- |
| time_split_sharpes | 1.3315, 1.3919, 1.7672, 1.8824 |
| worst_neighbour_degradation | 0.0681 |
| parameter_neighbourhood | entry_threshold=down=1.57 base=1.67 up=1.56; return_scale=down=1.63 base=1.67 up=1.67; vol_window=down=1.67 base=1.67 up=1.67 |

## Grid (full-sample Sharpe per configuration)

- crowding_window=72: sharpe=1.67
- crowding_window=0: sharpe=1.60

## Cost stress (Sharpe)

| key | value |
| --- | --- |
| x1 | 1.6725 |
| x1.5 | 1.6138 |
| x2 | 1.5550 |

## Slippage stress (Sharpe; fee fixed)

| key | value |
| --- | --- |
| slip2 | 1.6725 |
| slip5.5 | 1.6138 |
| slip9.2 | 1.5516 |

## Same book under close_to_close

| key | value |
| --- | --- |
| annualized_sharpe | 1.6560 |

## Verdict

| key | value |
| --- | --- |
| verdict | PASS |
| reasons | - |
