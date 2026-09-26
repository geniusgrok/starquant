# Book evidence: tsmom + 0.333 x flow — REJECT

## Range

| key | value |
| --- | --- |
| start | 2021-01-31 01:00:00+00:00 |
| end | 2026-09-07 16:00:00+00:00 |
| bars | 49096 |
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
| full_sharpe | 1.8184 |
| full_mdd | -0.2368 |
| oos_sharpe | 1.7671 |
| oos_return | 13.3008 |
| oos_mdd | -0.2368 |
| fold_sharpes | 1.7550, 0.5575, 2.5785, 1.2893, 2.6016 |

## Sleeve alone (as `research validate` would score it)

| key | value |
| --- | --- |
| full_sharpe | 0.5411 |
| full_mdd | -0.2782 |
| average_absolute_exposure | 0.2349 |
| oos_sharpe | 0.5882 |
| fold_sharpes | 1.2129, 0.1078, -0.1648, -0.0769, 1.4372 |
| cpcv_mean_q05_negative | 0.5196, -0.0042, 0.0667 |
| dsr_p_value | 0.9860 |
| n_trials | 71 |
| cost_x2_sharpe | 0.4305 |
| standalone_verdict | WEAK_PASS |
| standalone_reasons | - |

## Total book (main + fraction x sleeve)

| key | value |
| --- | --- |
| full_sharpe | 1.8227 |
| full_mdd | -0.2534 |
| oos_sharpe | 1.7715 |
| oos_return | 16.6409 |
| oos_mdd | -0.2534 |
| fold_sharpes | 1.9301, 0.5968, 2.5207, 1.1737, 2.6123 |

## Marginal

| key | value |
| --- | --- |
| delta_full_sharpe | 0.0043 |
| delta_oos_sharpe | 0.0044 |
| oos_mdd_worsening | 0.0165 |
| delta_oos_return | 3.3401 |
| fold_deltas | 0.1751, 0.0393, -0.0578, -0.1155, 0.0107 |
| fold_win_rate | 0.6000 |
| correlation_full | 0.2593 |
| correlation_oos | 0.2830 |
| sleeve_scaled_exposure | 0.0783 |

## Netting and caps

| key | value |
| --- | --- |
| sleeve_symbol_bars | 102955.0 |
| opposing_main_share | 0.1734 |
| same_direction_share | 0.8245 |
| main_flat_share | 0.0021 |
| cancelled_gross_share | 0.2889 |
| symbol_cap_share | 0.1158 |
| gross_cap_share | 0.0337 |

## Sensitivity (context only)

| key | value |
| --- | --- |
| 0.3333 | delta_oos_sharpe=0.0044; oos_mdd_worsening=0.0165; fold_win_rate=0.6000 |
| 0.2000 | delta_oos_sharpe=0.0280; oos_mdd_worsening=0.0134; fold_win_rate=0.6000 |
| 0.5000 | delta_oos_sharpe=-0.0365; oos_mdd_worsening=0.0415; fold_win_rate=0.4000 |

## Robustness universe

| key | value |
| --- | --- |
| universe | static |
| delta_oos_sharpe | -0.0820 |

## Yearly returns (main / total / sleeve alone at fraction)

| key | value |
| --- | --- |
| 2021 | main=0.7432; total=0.8370; sleeve_alone=0.0343 |
| 2022 | main=0.6031; total=0.7875; sleeve_alone=0.0966 |
| 2023 | main=0.6170; total=0.5988; sleeve_alone=-0.0152 |
| 2024 | main=0.4744; total=0.4117; sleeve_alone=-0.0256 |
| 2025 | main=0.5879; total=0.7235; sleeve_alone=0.0753 |
| 2026 | main=0.8879; total=0.9629; sleeve_alone=0.0655 |

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
| delta_oos_sharpe | no |
| oos_mdd_worsening | no |
| fold_win_rate | yes |
| cpcv_negative | yes |
| cost_x2_sharpe | no |
| robustness_delta | no |

## Verdict

| key | value |
| --- | --- |
| book_verdict | REJECT |
| reasons | delta_oos_sharpe, oos_mdd_worsening, cost_x2_sharpe, robustness_delta |
| notes | - |
