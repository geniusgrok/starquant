# Book evidence: tsmom + 0.333 x flow — REJECT

## Range

| key | value |
| --- | --- |
| start | 2021-01-31 01:00:00+00:00 |
| end | 2026-09-04 04:00:00+00:00 |
| bars | 49012 |
| oos_start | 2021-07-16 17:00:00+00:00 |

## Books

| key | value |
| --- | --- |
| main | tsmom |
| sleeve | flow |
| sleeve_params | {"cross_sectional": true, "entry_threshold": 0.2, "gate_horizons": [168, 336, 720], "gate_return_scale": 0.2, "gate_vol_window": 400, "gate_weights": [0.2, 0.3, 0.5], "long_side": false, "scale": 0.05, "short_gate": 0.3, "volume_window": 48, "window": 168} |
| fraction | 0.3333 |
| universe | pit |
| robustness_universe | static |

## Main book alone

| key | value |
| --- | --- |
| full_sharpe | 1.7160 |
| full_mdd | -0.1211 |
| oos_sharpe | 1.6436 |
| oos_return | 2.7092 |
| oos_mdd | -0.1211 |
| fold_sharpes | 1.4749, 0.7828, 2.3177, 1.0500, 2.5755 |

## Sleeve alone (as `research validate` would score it)

| key | value |
| --- | --- |
| full_sharpe | 0.8124 |
| full_mdd | -0.1243 |
| average_absolute_exposure | 0.0759 |
| oos_sharpe | 0.9203 |
| fold_sharpes | 2.2587, 0.6027, 0.9089, -1.2983, 1.0967 |
| cpcv_mean_q05_negative | 0.7678, -0.0027, 0.0667 |
| dsr_p_value | 0.6751 |
| n_trials | 10 |
| cost_x2_sharpe | 0.7286 |
| standalone_verdict | WEAK_PASS |
| standalone_reasons | - |

## Total book (main + fraction x sleeve)

| key | value |
| --- | --- |
| full_sharpe | 1.8221 |
| full_mdd | -0.1221 |
| oos_sharpe | 1.7700 |
| oos_return | 3.5141 |
| oos_mdd | -0.1221 |
| fold_sharpes | 1.8596, 0.8268, 2.5711, 0.9475, 2.6123 |

## Marginal

| key | value |
| --- | --- |
| delta_full_sharpe | 0.1060 |
| delta_oos_sharpe | 0.1264 |
| oos_mdd_worsening | 0.0010 |
| delta_oos_return | 0.8049 |
| fold_deltas | 0.3847, 0.0440, 0.2534, -0.1026, 0.0367 |
| fold_win_rate | 0.8000 |
| correlation_full | 0.2048 |
| correlation_oos | 0.2221 |
| sleeve_scaled_exposure | 0.0253 |

## Netting and caps

| key | value |
| --- | --- |
| sleeve_symbol_bars | 44440.0 |
| opposing_main_share | 0.1392 |
| same_direction_share | 0.8589 |
| main_flat_share | 0.0018 |
| cancelled_gross_share | 0.1943 |
| symbol_cap_share | 0.0143 |
| gross_cap_share | 0.0000 |

## Sensitivity (context only)

| key | value |
| --- | --- |
| 0.3333 | delta_oos_sharpe=0.1264; oos_mdd_worsening=0.0010; fold_win_rate=0.8000 |
| 0.2000 | delta_oos_sharpe=0.0877; oos_mdd_worsening=0.0001; fold_win_rate=0.8000 |
| 0.5000 | delta_oos_sharpe=0.1375; oos_mdd_worsening=0.0079; fold_win_rate=0.8000 |

## Robustness universe

| key | value |
| --- | --- |
| universe | static |
| delta_oos_sharpe | -0.0513 |

## Yearly returns (main / total / sleeve alone at fraction)

| key | value |
| --- | --- |
| 2021 | main=0.3065; total=0.3430; sleeve_alone=0.0300 |
| 2022 | main=0.2860; total=0.3887; sleeve_alone=0.0767 |
| 2023 | main=0.2613; total=0.2850; sleeve_alone=0.0131 |
| 2024 | main=0.1795; total=0.2065; sleeve_alone=0.0079 |
| 2025 | main=0.3575; total=0.4107; sleeve_alone=0.0228 |
| 2026 | main=0.3097; total=0.3219; sleeve_alone=0.0022 |

## Rule (D-018)

| key | value |
| --- | --- |
| min_delta_oos_sharpe | 0.1000 |
| max_oos_mdd_worsening | 0.0100 |
| min_fold_win_rate | 0.6000 |
| max_cpcv_negative | 0.1000 |
| min_cost_x2_sharpe | 0.5000 |
| min_robustness_delta | 0.0000 |

## Checks

| key | value |
| --- | --- |
| delta_oos_sharpe | yes |
| oos_mdd_worsening | yes |
| fold_win_rate | yes |
| cpcv_negative | yes |
| cost_x2_sharpe | yes |
| robustness_delta | no |

## Verdict

| key | value |
| --- | --- |
| book_verdict | REJECT |
| reasons | robustness_delta |
| notes | - |
