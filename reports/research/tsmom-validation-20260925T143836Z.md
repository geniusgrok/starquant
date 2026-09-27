# Validation: tsmom — WEAK_PASS

## Range

| key | value |
| --- | --- |
| start | 2021-01-31 01:00:00+00:00 |
| end | 2026-09-25 13:00:00+00:00 |
| bars | 49525 |

## Holdout (KILL-006)

| key | value |
| --- | --- |
| months | 0 |
| note | no tail reserved: every bar was available to this run |

## Book guards / exits (the layers the loop applies)

| key | value |
| --- | --- |
| guards | max_weight=0.1500; max_gross=2.0000; daily_loss_pause=-0.0500 |
| exits | stop_loss=6.0000; stop_loss_price_cap=0.0000; trailing_stop=0.0000; trailing_activate=0.0000; take_profit=6.0000; cooldown_bars=24; vol_halflife=48; bars_per_day=24; min_unit=0.0050; unit_mode=entry; regime_window=0; regime_er_cut=0.0500; regime_tp_scale=0.5000; regime_side=low; stale_carry_bars=2 |
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
| bars | 49525 |
| gross_return | 6.0367 |
| net_return | 4.6514 |
| annualized_sharpe | 1.9220 |
| annualized_sharpe_gross | 2.1547 |
| max_drawdown | -0.1039 |
| average_absolute_exposure | 0.5051 |
| turnover_units | 295.0 |
| nonzero_target_bars | 49334 |
| hit_rate | 0.5104 |
| cost_share_of_gross | 0.1080 |
| skew | 1.0018 |
| kurtosis | 28.4091 |
| sortino | 2.8399 |
| risk_free_rate | 0.0000 |
| guards | replayed=yes; gross_capped_bars=0; daily_loss_pause_bars=0; bars=49525; min_margin_buffer=107.3; liquidation_touches=0 |

## Walk-forward (out of sample)

| key | value |
| --- | --- |
| folds | 5 |
| oos_sharpe | 1.8329 |
| oos_windows | 63 |
| oos_window_sharpe_q10 | -1.8497 |
| oos_return | 3.6477 |
| oos_max_drawdown | -0.1039 |
| oos_bars | 45525 |
| oos_t_stat | 4.1167 |
| oos_t_lags | 15 |
| fold_sharpes | 2.2329, 0.5760, 2.7577, 1.2785, 2.3356 |
| fold_consistency | 1.0000 |
| selection_consistent | yes |
| oos_is_full_sample_tail | yes |
| best_key_oos_sharpe | 1.8329 |
| selection_exercised | NO fold had a choice to make (single configuration, or every fold picked the same one), so the OOS Sharpe above is the TAIL OF ONE FULL-SAMPLE SERIES, not a selection's out-of-sample record.  D-043 caps such a report at WEAK_PASS: the number stands, the claim that a selection survived out of sample does not.  `registry.py` still admits WEAK_PASS to live use. |

## CPCV

| key | value |
| --- | --- |
| paths | 15 |
| oos_sharpe_mean | 1.9245 |
| oos_sharpe_q05 | 1.5813 |
| oos_sharpe_min | 1.4897 |
| fraction_negative | 0.0000 |
| embargo | 50 bars, which is shorter than the model's feature lookback (tsmom max(horizons)=720, AlphaModel.warmup_bars 1442).  Training bars AFTER a test block are therefore computed from a window covering it, and `cpcv_evaluate` picks parameters on exactly those bars.  The returns stay causal, so this is selection contamination rather than look-ahead - it makes `fraction_negative`, one of D-020's hard gates, easier to pass than it should be.  Open boundary on the record: see `cpcv_splits`' docstring and docs/analysis/2026-09-13-full-repo-review.md. |

## Multiple testing

| key | value |
| --- | --- |
| n_trials | 341 |
| grid_trials | 2 |
| grid_effective_trials | 2.0000 |
| prior_trials | 172 |
| sharpe_variance_period | 0.0000 |
| candidate_sharpe_annual | 1.9220 |
| expected_max_sharpe_annual | 1.6214 |
| dsr | 0.7646 |
| dsr_p_value | 0.2354 |
| pbo | 0.0098 |
| pbo_combinations | 5000 |
| degradation_slope | -0.9962 |
| prob_oos_loss | 0.0000 |
| noise_null | sharpe_variance_period=0.0000; expected_max_sharpe_annual=1.2237; dsr_p_value=0.0469 |
| ledger_trials | 167 |
| pbo_is_informative | NOT informative and NOT enforced at grid_trials=2: CSCV ranks configurations against each other, and with fewer than four it only says that two curves traded places across sub-periods.  `verdict.decide` skips the gate below four, so a move in this number is not a cost or a gain either. |

## Selection-deflated OOS threshold (D-028)

| key | value |
| --- | --- |
| n_obs | 45525 |
| n_trials | 341 |
| alpha | 0.0500 |
| gate | max_sharpe_quantile |
| variance | 0.0000 |
| threshold_annual | 1.5733 |
| expected_max_annual | 1.2777 |
| p_family | 0.0043 |
| oos_sharpe_annual | 1.8329 |
| caliber | ENFORCED at N=341 (the per-strategy bucket): threshold 1.57, margin +0.26.  REPORTED and never enforced at N=21638 (the whole library): threshold 1.99, margin -0.16, p_family 0.2405.  Which N is the gate is R0 / KILL-AR-01, an operator ruling rather than a property of the arithmetic, and both numbers are printed so the ruling stays arguable from the artefact alone. |

## Power of that gate (D-020 + D-028): what it would have detected

| key | value |
| --- | --- |
| standard error of the OOS Sharpe (annual) | 0.4353 |
| gate (max of the two halves) | 1.5733  [selection binds] |
|   D-028 selection threshold | 1.5733 at N=341, alpha=0.05 |
|   D-020 pass line | 1.0000 |
| P(clear | true annual Sharpe = 1.0) | 9.4% |
| P(clear | true annual Sharpe = 1.2) | 19.6% |
| P(clear | true annual Sharpe = 1.5) | 43.3% |
| P(clear | true annual Sharpe = 2.0) | 83.7% |
| not included in the above | cpcv_fraction_negative, pbo, fold_consistency, cost_stress_x2 (so the true joint power is LOWER) |

## The other caliber (R0: reported, never enforced)

| key | value |
| --- | --- |
| n_obs | 45525 |
| n_trials | 21638 |
| alpha | 0.0500 |
| gate | max_sharpe_quantile |
| variance | 0.0000 |
| threshold_annual | 1.9917 |
| expected_max_annual | 1.7608 |
| p_family | 0.2405 |
| oos_sharpe_annual | 1.8329 |
| power | n_trials=21638; alpha=0.0500; se_annual=0.4353; pass_line_annual=1.0000; selection_threshold_annual=1.9917; gate_annual=1.9917; binding=selection; detects=true_sharpe_annual=1.0000; power=0.0114, true_sharpe_annual=1.2000; power=0.0345, true_sharpe_annual=1.5000; power=0.1293, true_sharpe_annual=2.0000; power=0.5076; excludes=cpcv_fraction_negative, pbo, fold_consistency, cost_stress_x2 |

## Cost stress against that gate (same folds, same N, best_key basis)

| key | value |
| --- | --- |
| x1 | oos=1.83 threshold=1.57 margin=0.26 clears=1.00 |
| x1.5 | oos=1.72 threshold=1.57 margin=0.15 clears=1.00 |
| x2 | oos=1.61 threshold=1.57 margin=0.04 clears=1.00 |

## Slippage stress against that gate (fee held fixed - the grid the question is about)

| key | value |
| --- | --- |
| slip2 | oos=1.83 threshold=1.57 margin=0.26 clears=1.00 |
| slip4.43 | oos=1.76 threshold=1.57 margin=0.18 clears=1.00 |
| slip5.5 | oos=1.72 threshold=1.57 margin=0.15 clears=1.00 |
| slip9.2 | oos=1.60 threshold=1.57 margin=0.03 clears=1.00 |

## Stability

| key | value |
| --- | --- |
| time_split_sharpes | 1.6108, 1.8302, 1.7221, 2.1548 |
| worst_neighbour_degradation | 0.1196 |
| parameter_neighbourhood | entry_threshold=down=1.70 base=1.92 up=1.69; return_scale=down=1.80 base=1.92 up=1.84; vol_window=down=1.92 base=1.92 up=1.92 |

## Sharpe by benchmark-volatility regime (reported, never enforced)

| key | value |
| --- | --- |
| low (annualised vol 0.40-0.71) | sharpe=3.06  bars=15175 |
| mid (annualised vol 0.71-0.88) | sharpe=1.35  bars=15175 |
| high (annualised vol 0.88-2.23) | sharpe=0.93  bars=15175 |
| basis: series | walk_forward oos_returns, the series time_split_sharpes splits |
| basis: state | annualised std, over vol_window_days, of benchmark_returns: equal-weight, zero cost, over the symbols the book could hold at each bar (pit members; every panel symbol if static) |
| basis: vol_window_days | 30 |
| basis: label_on_bar_t_reads | benchmark bars through t-1: what was known when bar t's position was decided |
| basis: cut_points | this sample's own terciles: the state is ex-ante, the cut points are not.  Volatility trends over years, so a tercile is partly a calendar period: read it against time_split_sharpes |

## Grid (full-sample Sharpe per configuration)

- crowding_window=72: sharpe=1.92
- crowding_window=0: sharpe=1.78

## Cost stress (Sharpe)

| key | value |
| --- | --- |
| x1 | 1.9220 |
| x1.5 | 1.8122 |
| x2 | 1.7024 |
| break-even multiple m* (never enforced) | full_sample=9.77  oos=9.27  (mean net return is 0 with turnover and carry costs x m*) |

## Slippage stress (Sharpe; fee fixed)

| key | value |
| --- | --- |
| slip2 | 1.9220 |
| slip4.43 | 1.8458 |
| slip5.5 | 1.8122 |
| slip9.2 | 1.6961 |

## Same book under close_to_close

| key | value |
| --- | --- |
| annualized_sharpe | 1.8932 |

## Verdict

| key | value |
| --- | --- |
| verdict | WEAK_PASS |
| reasons | oos_is_full_sample_tail: no fold had a choice to make (single configuration, or every fold picked the same one), so this OOS is the tail of one full-sample series |
