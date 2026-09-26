# Book evidence: tsmom + 0.333 x residual — REJECT

## Range

| key | value |
| --- | --- |
| start | 2021-01-31 01:00:00+00:00 |
| end | 2026-09-18 16:00:00+00:00 |
| bars | 49360 |
| oos_start | 2021-07-16 17:00:00+00:00 |

## Books

| key | value |
| --- | --- |
| main | tsmom |
| sleeve | residual |
| sleeve_params | {"benchmark": "BTCUSDT", "beta_window": 336, "entry_threshold": 0.2, "horizons": [24, 72, 168], "scale": 0.05} |
| fraction | 0.3333 |
| universe | pit |
| robustness_universe | static |

## Main book alone

| key | value |
| --- | --- |
| full_sharpe | 1.6243 |
| full_mdd | -0.4203 |
| oos_sharpe | 1.5411 |
| oos_return | 44.1672 |
| oos_mdd | -0.4203 |
| fold_sharpes | 1.6954, 0.0097, 2.2466, 1.3118, 2.3009 |

## Sleeve alone (as `research validate` would score it)

| key | value |
| --- | --- |
| full_sharpe | 0.6233 |
| full_mdd | -0.6670 |
| average_absolute_exposure | 1.3599 |
| oos_sharpe | 0.5716 |
| fold_sharpes | 0.9532, -0.0181, 0.1487, -0.2710, 2.0546 |
| cpcv_mean_q05_negative | 0.6213, 0.1432, 0.0000 |
| dsr_p_value | 0.3332 |
| n_trials | 18 |
| cost_x2_sharpe | -0.1123 |
| standalone_verdict | FAIL |
| standalone_reasons | cost stress x2 sharpe -0.11 < 0.0 |

## Total book (main + fraction x sleeve)

| key | value |
| --- | --- |
| full_sharpe | 1.6311 |
| full_mdd | -0.4963 |
| oos_sharpe | 1.5696 |
| oos_return | 62.0179 |
| oos_mdd | -0.4963 |
| fold_sharpes | 1.6110, -0.0497, 2.2845, 1.1118, 2.7821 |

## Marginal

| key | value |
| --- | --- |
| delta_full_sharpe | 0.0069 |
| delta_oos_sharpe | 0.0285 |
| oos_mdd_worsening | 0.0760 |
| delta_oos_return | 17.8507 |
| fold_deltas | -0.0843, -0.0594, 0.0379, -0.2000, 0.4812 |
| fold_win_rate | 0.4000 |
| oos_mdd_worsening_equal_risk | 0.0473 |
| correlation_full | 0.2617 |
| correlation_oos | 0.2517 |
| sleeve_scaled_exposure | 0.4525 |

## Netting and caps

| key | value |
| --- | --- |
| sleeve_symbol_bars | 816893.0 |
| opposing_main_share | 0.4012 |
| same_direction_share | 0.5964 |
| main_flat_share | 0.0024 |
| cancelled_gross_share | 0.7776 |
| symbol_cap_share | 0.1118 |
| gross_cap_share | 0.1759 |

## Sensitivity (context only)

| key | value |
| --- | --- |
| 0.3333 | delta_oos_sharpe=0.0285; oos_mdd_worsening=0.0760; fold_win_rate=0.4000 |
| 0.2000 | delta_oos_sharpe=0.0386; oos_mdd_worsening=0.0602; fold_win_rate=0.4000 |
| 0.5000 | delta_oos_sharpe=-0.0765; oos_mdd_worsening=0.1106; fold_win_rate=0.2000 |

## Robustness universe

| key | value |
| --- | --- |
| universe | static |
| delta_oos_sharpe | -0.0299 |

## Yearly returns (main / total / sleeve alone at fraction)

| key | value |
| --- | --- |
| 2021 | main=1.4754; total=1.5004; sleeve_alone=0.1854 |
| 2022 | main=1.0677; total=1.0834; sleeve_alone=0.2138 |
| 2023 | main=0.7856; total=0.7182; sleeve_alone=-0.0485 |
| 2024 | main=0.6687; total=0.6804; sleeve_alone=-0.0736 |
| 2025 | main=1.3020; total=1.6469; sleeve_alone=0.1072 |
| 2026 | main=1.4535; total=1.9942; sleeve_alone=0.2850 |

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
| fold_win_rate | no |
| cpcv_negative | yes |
| cost_x2_sharpe | no |
| robustness_delta | no |

## §3 limits (read by the state machine at validated->booked, not by `book_verdict`)

| key | value |
| --- | --- |
| slippage_stress_5.5_pass | no |
| slippage_stress_reasons | delta_oos_sharpe, oos_mdd_worsening, fold_win_rate |
| sleeve_sharpe_by_slippage | slip2=0.6233; slip4.43=0.3679; slip5.5=0.2554; slip9.2=-0.1333 |
| max_correlation_with_running | 0.3023 |
| correlation_with_running | flow_short=0.3023; main=0.2603 |
| running_books_notes | - |
| turnover_ratio_to_main | 7.7120 |
| turnover_per_gross_ratio | 7.7554 |

## Verdict

| key | value |
| --- | --- |
| book_verdict | REJECT |
| reasons | delta_oos_sharpe, oos_mdd_worsening, fold_win_rate, cost_x2_sharpe, robustness_delta |
| notes | - |
