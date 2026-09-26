# Book evidence: tsmom + 0.333 x flow — ACCEPT

## Range

| key | value |
| --- | --- |
| start | 2021-01-31 01:00:00+00:00 |
| end | 2026-09-03 11:00:00+00:00 |
| bars | 48995 |
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
| full_sharpe | 1.6411 |
| full_mdd | -0.1261 |
| oos_sharpe | 1.5291 |
| oos_return | 2.1922 |
| oos_mdd | -0.1261 |
| fold_sharpes | 1.2234, 0.7794, 2.0446, 1.6549, 1.9443 |

## Sleeve alone (as `research validate` would score it)

| key | value |
| --- | --- |
| full_sharpe | 1.1078 |
| full_mdd | -0.1101 |
| average_absolute_exposure | 0.0936 |
| oos_sharpe | 1.0933 |
| fold_sharpes | 1.6348, 0.9055, 0.7936, -0.6275, 2.1331 |
| cpcv_mean_q05_negative | 1.0873, 0.4715, 0.0000 |
| dsr_p_value | 0.8067 |
| n_trials | 48 |
| cost_x2_sharpe | 0.9989 |
| standalone_verdict | FAIL |
| standalone_reasons | dsr_p_value 0.806741196092261 > 0.1 |

## Total book (main + fraction x sleeve)

| key | value |
| --- | --- |
| full_sharpe | 1.7883 |
| full_mdd | -0.1329 |
| oos_sharpe | 1.6844 |
| oos_return | 3.0291 |
| oos_mdd | -0.1329 |
| fold_sharpes | 1.6137, 0.8750, 2.1821, 1.5345, 2.2203 |

## Marginal

| key | value |
| --- | --- |
| delta_full_sharpe | 0.1471 |
| delta_oos_sharpe | 0.1554 |
| oos_mdd_worsening | 0.0068 |
| delta_oos_return | 0.8368 |
| fold_deltas | 0.3903, 0.0955, 0.1376, -0.1203, 0.2760 |
| fold_win_rate | 0.8000 |
| correlation_full | 0.2849 |
| correlation_oos | 0.2919 |
| sleeve_scaled_exposure | 0.0311 |

## Netting and caps

| key | value |
| --- | --- |
| sleeve_symbol_bars | 61168.0 |
| opposing_main_share | 0.0891 |
| same_direction_share | 0.9075 |
| main_flat_share | 0.0033 |
| cancelled_gross_share | 0.1099 |
| symbol_cap_share | 0.0018 |
| gross_cap_share | 0.0000 |

## Sensitivity (context only)

| key | value |
| --- | --- |
| 0.3333 | delta_oos_sharpe=0.1554; oos_mdd_worsening=0.0068; fold_win_rate=0.8000 |
| 0.2000 | delta_oos_sharpe=0.1083; oos_mdd_worsening=0.0041; fold_win_rate=0.8000 |
| 0.5000 | delta_oos_sharpe=0.1736; oos_mdd_worsening=0.0170; fold_win_rate=0.8000 |

## Robustness universe

| key | value |
| --- | --- |
| universe | static |
| delta_oos_sharpe | 0.0097 |

## Yearly returns (main / total / sleeve alone at fraction)

| key | value |
| --- | --- |
| 2021 | main=0.3064; total=0.3540; sleeve_alone=0.0276 |
| 2022 | main=0.2120; total=0.3022; sleeve_alone=0.0668 |
| 2023 | main=0.3748; total=0.4442; sleeve_alone=0.0443 |
| 2024 | main=0.1777; total=0.1969; sleeve_alone=0.0057 |
| 2025 | main=0.2505; total=0.3131; sleeve_alone=0.0548 |
| 2026 | main=0.2188; total=0.2570; sleeve_alone=0.0256 |

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
| robustness_delta | yes |

## Verdict

| key | value |
| --- | --- |
| book_verdict | ACCEPT |
| reasons | - |
| notes | - |
