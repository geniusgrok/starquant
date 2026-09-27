# Validation: tsmom — FAIL

## Range

| key | value |
| --- | --- |
| start | 2021-01-31 01:00:00+00:00 |
| end | 2026-09-18 07:00:00+00:00 |
| bars | 49351 |

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
| bars | 49351 |
| gross_return | 119.8 |
| net_return | 78.7026 |
| annualized_sharpe | 1.6452 |
| annualized_sharpe_gross | 1.7742 |
| max_drawdown | -0.4029 |
| average_absolute_exposure | 1.3433 |
| turnover_units | 542.5 |
| nonzero_target_bars | 49339 |
| hit_rate | 0.5118 |
| cost_share_of_gross | 0.0728 |
| guards | replayed=yes; gross_capped_bars=4043; daily_loss_pause_bars=481; bars=49351; min_margin_buffer=97.1690; liquidation_touches=0 |

## Walk-forward (out of sample)

| key | value |
| --- | --- |
| folds | 5 |
| oos_sharpe | 1.5628 |
| oos_windows | 62 |
| oos_window_sharpe_q10 | -1.5604 |
| oos_return | 41.5760 |
| oos_max_drawdown | -0.4029 |
| oos_bars | 45351 |
| oos_t_stat | 3.5797 |
| oos_t_lags | 15 |
| fold_sharpes | 1.8158, -0.0036, 2.4814, 1.2998, 2.0856 |
| fold_consistency | 0.8000 |
| selection_consistent | yes |
| oos_is_full_sample_tail | yes |
| best_key_oos_sharpe | 1.5628 |
| selection_exercised | NO fold had a choice to make (single configuration, or every fold picked the same one), so the OOS Sharpe above is the TAIL OF ONE FULL-SAMPLE SERIES, not a selection's out-of-sample record.  D-043 caps such a report at WEAK_PASS: the number stands, the claim that a selection survived out of sample does not.  `registry.py` still admits WEAK_PASS to live use. |

## CPCV

| key | value |
| --- | --- |
| paths | 15 |
| oos_sharpe_mean | 1.5934 |
| oos_sharpe_q05 | 1.1763 |
| oos_sharpe_min | 1.1281 |
| fraction_negative | 0.0000 |
| embargo | 50 bars, which is shorter than the model's feature lookback (tsmom max(horizons)=720, AlphaModel.warmup_bars 1442).  Training bars AFTER a test block are therefore computed from a window covering it, and `cpcv_evaluate` picks parameters on exactly those bars.  The returns stay causal, so this is selection contamination rather than look-ahead - it makes `fraction_negative`, one of D-020's hard gates, easier to pass than it should be.  Open boundary on the record: see `cpcv_splits`' docstring and docs/analysis/2026-09-13-full-repo-review.md. |

## Multiple testing

| key | value |
| --- | --- |
| n_trials | 303 |
| grid_trials | 2 |
| grid_effective_trials | 2.0000 |
| prior_trials | 152 |
| sharpe_variance_period | 0.0000 |
| candidate_sharpe_annual | 1.6452 |
| expected_max_sharpe_annual | 1.6141 |
| dsr | 0.5295 |
| dsr_p_value | 0.4705 |
| pbo | 0.1982 |
| pbo_combinations | 5000 |
| degradation_slope | -0.9989 |
| prob_oos_loss | 0.0000 |
| noise_null | sharpe_variance_period=0.0000; expected_max_sharpe_annual=1.2196; dsr_p_value=0.1559 |
| ledger_trials | 149 |
| pbo_is_informative | NOT informative and NOT enforced at grid_trials=2: CSCV ranks configurations against each other, and with fewer than four it only says that two curves traded places across sub-periods.  `verdict.decide` skips the gate below four, so a move in this number is not a cost or a gain either. |

## Selection-deflated OOS threshold (D-028)

| key | value |
| --- | --- |
| n_obs | 45351 |
| n_trials | 303 |
| alpha | 0.0500 |
| gate | max_sharpe_quantile |
| variance | 0.0000 |
| threshold_annual | 1.5733 |
| expected_max_annual | 1.2725 |
| p_family | 0.0547 |
| oos_sharpe_annual | 1.5628 |
| caliber | ENFORCED at N=303 (the per-strategy bucket): threshold 1.57, margin -0.01.  REPORTED and never enforced at N=21618 (the whole library): threshold 2.01, margin -0.45, p_family 0.9819.  Which N is the gate is R0 / KILL-AR-01, an operator ruling rather than a property of the arithmetic, and both numbers are printed so the ruling stays arguable from the artefact alone. |

## Power of that gate (D-020 + D-028): what it would have detected

| key | value |
| --- | --- |
| standard error of the OOS Sharpe (annual) | 0.4390 |
| gate (max of the two halves) | 1.5733  [selection binds] |
|   D-028 selection threshold | 1.5733 at N=303, alpha=0.05 |
|   D-020 pass line | 1.0000 |
| P(clear | true annual Sharpe = 1.0) | 9.6% |
| P(clear | true annual Sharpe = 1.2) | 19.8% |
| P(clear | true annual Sharpe = 1.5) | 43.4% |
| P(clear | true annual Sharpe = 2.0) | 83.4% |
| not included in the above | cpcv_fraction_negative, pbo, fold_consistency, cost_stress_x2 (so the true joint power is LOWER) |

## The other caliber (R0: reported, never enforced)

| key | value |
| --- | --- |
| n_obs | 45351 |
| n_trials | 21618 |
| alpha | 0.0500 |
| gate | max_sharpe_quantile |
| variance | 0.0000 |
| threshold_annual | 2.0088 |
| expected_max_annual | 1.7758 |
| p_family | 0.9819 |
| oos_sharpe_annual | 1.5628 |
| power | n_trials=21618; alpha=0.0500; se_annual=0.4390; pass_line_annual=1.0000; selection_threshold_annual=2.0088; gate_annual=2.0088; binding=selection; detects=true_sharpe_annual=1.0000; power=0.0108, true_sharpe_annual=1.2000; power=0.0327, true_sharpe_annual=1.5000; power=0.1232, true_sharpe_annual=2.0000; power=0.4920; excludes=cpcv_fraction_negative, pbo, fold_consistency, cost_stress_x2 |

## Cost stress against that gate (same folds, same N, best_key basis)

| key | value |
| --- | --- |
| x1 | oos=1.56 threshold=1.57 margin=-0.01 clears=0.00 |
| x1.5 | oos=1.50 threshold=1.57 margin=-0.07 clears=0.00 |
| x2 | oos=1.44 threshold=1.57 margin=-0.13 clears=0.00 |

## Slippage stress against that gate (fee held fixed - the grid the question is about)

| key | value |
| --- | --- |
| slip2 | oos=1.56 threshold=1.57 margin=-0.01 clears=0.00 |
| slip4.43 | oos=1.52 threshold=1.57 margin=-0.05 clears=0.00 |
| slip5.5 | oos=1.50 threshold=1.57 margin=-0.07 clears=0.00 |
| slip9.2 | oos=1.44 threshold=1.57 margin=-0.13 clears=0.00 |

## Stability

| key | value |
| --- | --- |
| time_split_sharpes | 1.3583, 1.4374, 1.6428, 1.8253 |
| worst_neighbour_degradation | 0.0637 |
| parameter_neighbourhood | entry_threshold=down=1.56 base=1.65 up=1.54; return_scale=down=1.61 base=1.65 up=1.65; vol_window=down=1.65 base=1.65 up=1.65 |

## Grid (full-sample Sharpe per configuration)

- crowding_window=72: sharpe=1.65
- crowding_window=0: sharpe=1.56

## Cost stress (Sharpe)

| key | value |
| --- | --- |
| x1 | 1.6452 |
| x1.5 | 1.5863 |
| x2 | 1.5273 |

## Slippage stress (Sharpe; fee fixed)

| key | value |
| --- | --- |
| slip2 | 1.6452 |
| slip4.43 | 1.6043 |
| slip5.5 | 1.5863 |
| slip9.2 | 1.5239 |

## Same book under close_to_close

| key | value |
| --- | --- |
| annualized_sharpe | 1.6286 |

## Verdict

| key | value |
| --- | --- |
| verdict | FAIL |
| reasons | oos_sharpe 1.56 < the deflated threshold 1.57 at 303 trials, p_family=0.0547 |
