# Validation: residual — FAIL

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
| beta_window | 336 |
| scale | 0.1000 |
| benchmark | BTCUSDT |
| entry_threshold | 0.2000 |

## Full sample

| key | value |
| --- | --- |
| bars | 49120 |
| gross_return | 6.7362 |
| net_return | 4.7233 |
| annualized_sharpe | 1.1846 |
| annualized_sharpe_gross | 1.3632 |
| max_drawdown | -0.2794 |
| average_absolute_exposure | 0.7789 |
| turnover_units | 721.8 |
| nonzero_target_bars | 49120 |
| hit_rate | 0.5023 |
| cost_share_of_gross | 0.1311 |
| guards | replayed=yes; gross_capped_bars=8; daily_loss_pause_bars=46; bars=49120; min_margin_buffer=99.7812; liquidation_touches=0 |

## Walk-forward (out of sample)

| key | value |
| --- | --- |
| folds | 5 |
| oos_sharpe | 1.0760 |
| oos_windows | 62 |
| oos_window_sharpe_q10 | -3.8283 |
| oos_return | 3.1821 |
| oos_max_drawdown | -0.2794 |
| oos_bars | 45120 |
| oos_t_stat | 2.4169 |
| oos_t_lags | 15 |
| fold_sharpes | 1.7210, 0.2319, 1.2700, 0.4643, 1.7186 |
| fold_consistency | 1.0000 |
| selection_consistent | yes |
| oos_is_full_sample_tail | yes |
| best_key_oos_sharpe | 1.0760 |

## CPCV

| key | value |
| --- | --- |
| paths | 15 |
| oos_sharpe_mean | 1.0795 |
| oos_sharpe_q05 | 0.4542 |
| oos_sharpe_min | 0.3780 |
| fraction_negative | 0.0000 |

## Multiple testing

| key | value |
| --- | --- |
| n_trials | 8 |
| grid_trials | 8 |
| grid_effective_trials | 3.0000 |
| prior_trials | 0 |
| sharpe_variance_period | 0.0000 |
| candidate_sharpe_annual | 1.1846 |
| expected_max_sharpe_annual | 0.3742 |
| dsr | 0.9728 |
| dsr_p_value | 0.0272 |
| pbo | 0.2220 |
| pbo_combinations | 5000 |
| degradation_slope | -0.9754 |
| prob_oos_loss | 0.0014 |
| noise_null | sharpe_variance_period=0.0000; expected_max_sharpe_annual=0.6145; dsr_p_value=0.0880 |
| ledger_trials | 0 |

## Selection-deflated OOS threshold (D-028)

| key | value |
| --- | --- |
| n_obs | 45120 |
| n_trials | 8 |
| alpha | 0.0500 |
| gate | max_sharpe_quantile |
| variance | 0.0000 |
| threshold_annual | 1.0935 |
| expected_max_annual | 0.6408 |
| p_family | 0.0557 |
| oos_sharpe_annual | 1.0760 |

## Stability

| key | value |
| --- | --- |
| time_split_sharpes | 1.6247, 0.2653, 0.8137, 1.6052 |
| worst_neighbour_degradation | 0.1510 |
| parameter_neighbourhood | beta_window=down=1.16 base=1.18 up=1.01; scale=down=1.12 base=1.18 up=1.13 |

## Grid (full-sample Sharpe per configuration)

- beta_window=336, horizons=[168, 336, 720], scale=0.1: sharpe=1.18
- beta_window=720, horizons=[168, 336, 720], scale=0.1: sharpe=1.00
- beta_window=336, horizons=[24, 72, 168], scale=0.1: sharpe=0.96
- beta_window=720, horizons=[24, 72, 168], scale=0.1: sharpe=0.87
- beta_window=336, horizons=[168, 336, 720], scale=0.05: sharpe=0.86
- beta_window=720, horizons=[168, 336, 720], scale=0.05: sharpe=0.82
- beta_window=336, horizons=[24, 72, 168], scale=0.05: sharpe=0.58
- beta_window=720, horizons=[24, 72, 168], scale=0.05: sharpe=0.36

## Cost stress (Sharpe)

| key | value |
| --- | --- |
| x1 | 1.1846 |
| x1.5 | 1.0347 |
| x2 | 0.8849 |

## Slippage stress (Sharpe; fee fixed)

| key | value |
| --- | --- |
| slip2 | 1.1846 |
| slip5.5 | 1.0347 |
| slip9.2 | 0.8764 |

## Same book under close_to_close

| key | value |
| --- | --- |
| annualized_sharpe | 1.1489 |

## Verdict

| key | value |
| --- | --- |
| verdict | FAIL |
| reasons | oos_sharpe 1.08 < the deflated threshold 1.09 at 8 trials, p_family=0.0557 |
