# Validation: carry — FAIL

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
| window_bars | 168 |
| mode | rank |
| scale | 0.0001 |
| cross_sectional | yes |
| winsor_pct | 0.1000 |
| entry_threshold | 0.2000 |
| min_symbols | 5 |

## Full sample

| key | value |
| --- | --- |
| bars | 49120 |
| gross_return | 2.2291 |
| net_return | 4.9918 |
| annualized_sharpe | 1.3089 |
| annualized_sharpe_gross | 0.9038 |
| max_drawdown | -0.3494 |
| average_absolute_exposure | 1.3404 |
| turnover_units | 658.5 |
| nonzero_target_bars | 49120 |
| hit_rate | 0.5082 |
| cost_share_of_gross | -0.4478 |
| guards | replayed=yes; gross_capped_bars=450; daily_loss_pause_bars=40; bars=49120; min_margin_buffer=99.0272; liquidation_touches=0 |

## Walk-forward (out of sample)

| key | value |
| --- | --- |
| folds | 5 |
| oos_sharpe | 0.5418 |
| oos_windows | 62 |
| oos_window_sharpe_q10 | -3.6724 |
| oos_return | 0.7670 |
| oos_max_drawdown | -0.3494 |
| oos_bars | 45120 |
| oos_t_stat | 1.2199 |
| oos_t_lags | 15 |
| fold_sharpes | 0.8629, -1.0747, 0.8862, 1.1831, 0.7491 |
| fold_consistency | 0.8000 |
| selection_consistent | no |
| oos_is_full_sample_tail | no |
| best_key_oos_sharpe | 0.8864 |

## CPCV

| key | value |
| --- | --- |
| paths | 15 |
| oos_sharpe_mean | 1.2440 |
| oos_sharpe_q05 | 0.4290 |
| oos_sharpe_min | 0.2976 |
| fraction_negative | 0.0000 |

## Multiple testing

| key | value |
| --- | --- |
| n_trials | 4 |
| grid_trials | 4 |
| grid_effective_trials | 2.0000 |
| prior_trials | 0 |
| sharpe_variance_period | 0.0000 |
| candidate_sharpe_annual | 1.3089 |
| expected_max_sharpe_annual | 0.2212 |
| dsr | 0.9949 |
| dsr_p_value | 0.0051 |
| pbo | 0.3370 |
| pbo_combinations | 5000 |
| degradation_slope | -0.9316 |
| prob_oos_loss | 0.0082 |
| noise_null | sharpe_variance_period=0.0000; expected_max_sharpe_annual=0.4453; dsr_p_value=0.0207 |
| ledger_trials | 0 |

## Selection-deflated OOS threshold (D-028)

| key | value |
| --- | --- |
| n_obs | 45120 |
| n_trials | 4 |
| alpha | 0.0500 |
| gate | max_sharpe_quantile |
| variance | 0.0000 |
| threshold_annual | 0.9852 |
| expected_max_annual | 0.4640 |
| p_family | 0.3715 |
| oos_sharpe_annual | 0.5418 |

## Stability

| key | value |
| --- | --- |
| time_split_sharpes | 0.1448, 0.7047, 0.5493, 0.8128 |
| worst_neighbour_degradation | 0.2763 |
| parameter_neighbourhood | entry_threshold=down=1.24 base=1.31 up=1.30; window_bars=down=0.95 base=1.31 up=1.02 |

## Grid (full-sample Sharpe per configuration)

- entry_threshold=0.2, window_bars=168: sharpe=1.31
- entry_threshold=0.3, window_bars=168: sharpe=1.05
- entry_threshold=0.3, window_bars=72: sharpe=1.02
- entry_threshold=0.2, window_bars=72: sharpe=0.80

## Cost stress (Sharpe)

| key | value |
| --- | --- |
| x1 | 1.3089 |
| x1.5 | 1.1579 |
| x2 | 1.0069 |

## Slippage stress (Sharpe; fee fixed)

| key | value |
| --- | --- |
| slip2 | 1.3089 |
| slip5.5 | 1.1579 |
| slip9.2 | 0.9982 |

## Same book under close_to_close

| key | value |
| --- | --- |
| annualized_sharpe | 1.2943 |

## Verdict

| key | value |
| --- | --- |
| verdict | FAIL |
| reasons | oos_sharpe 0.54 < the deflated threshold 0.99 at 4 trials, p_family=0.3715, pbo 0.34 > 0.3 |
