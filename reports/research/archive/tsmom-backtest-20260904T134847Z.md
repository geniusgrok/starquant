# Backtest: tsmom

## Range

| key | value |
| --- | --- |
| start | 2021-01-31 01:00:00+00:00 |
| end | 2026-09-04 06:00:00+00:00 |
| bars | 49014 |

## Params

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
| crowding_window | 0 |
| crowding_cut | 0.7000 |
| crowding_penalty | 0.5000 |
| momentum_mode | fixed |
| conviction_mode | sign |

## Summary

| key | value |
| --- | --- |
| bars | 49014 |
| gross_return | 20.9527 |
| net_return | 15.3326 |
| annualized_sharpe | 1.7136 |
| annualized_sharpe_gross | 1.8780 |
| max_drawdown | -0.2422 |
| average_absolute_exposure | 0.8541 |
| turnover_units | 395.0 |
| nonzero_target_bars | 49014 |
| hit_rate | 0.5128 |
| cost_share_of_gross | 0.0876 |
| guards | replayed=yes; gross_capped_bars=355; daily_loss_pause_bars=36; bars=49014 |

## Benchmark (equal-weight long, zero cost)

| key | value |
| --- | --- |
| gross_return | 0.3147 |
| sharpe | 0.5035 |

## Yearly

| key | value |
| --- | --- |
| 2021 | ret=0.582 sharpe=1.69 |
| 2022 | ret=0.598 sharpe=1.62 |
| 2023 | ret=0.492 sharpe=1.42 |
| 2024 | ret=0.428 sharpe=1.26 |
| 2025 | ret=0.738 sharpe=1.86 |
| 2026 | ret=0.744 sharpe=2.78 |

## Per symbol

| key | value |
| --- | --- |
| 1000BONKUSDT | net=-0.003 sharpe=-0.03 turnover=1.3 |
| 1000FLOKIUSDT | net=-0.006 sharpe=-0.14 turnover=0.6 |
| 1000LUNCUSDT | net=0.013 sharpe=0.29 turnover=0.5 |
| 1000PEPEUSDT | net=0.190 sharpe=0.81 turnover=10.6 |
| 1000RATSUSDT | net=-0.009 sharpe=-0.44 turnover=0.2 |
| 1000SATSUSDT | net=-0.050 sharpe=-0.91 turnover=1.4 |
| 1000SHIBUSDT | net=0.010 sharpe=0.08 turnover=8.7 |
| 1MBABYDOGEUSDT | net=0.015 sharpe=0.34 turnover=0.6 |
| AAVEUSDT | net=0.011 sharpe=0.18 turnover=1.6 |
| ACEUSDT | net=0.007 sharpe=0.39 turnover=0.0 |
| ADAUSDT | net=0.062 sharpe=0.27 turnover=17.9 |
| AGIXUSDT | net=-0.006 sharpe=-0.15 turnover=0.4 |
| AKEUSDT | net=0.047 sharpe=0.84 turnover=0.1 |
| ALICEUSDT | net=-0.006 sharpe=-0.18 turnover=0.4 |
| ALPACAUSDT | net=0.009 sharpe=0.94 turnover=0.3 |
| ALTUSDT | net=-0.000 sharpe=-0.18 turnover=0.0 |
| APEUSDT | net=0.070 sharpe=0.74 turnover=2.5 |
| API3USDT | net=0.009 sharpe=0.65 turnover=0.1 |
| APTUSDT | net=0.011 sharpe=0.11 turnover=3.5 |
| ARBUSDT | net=0.030 sharpe=0.33 turnover=3.3 |
| ARKUSDT | net=-0.003 sharpe=-0.16 turnover=0.1 |
| ARPAUSDT | net=-0.036 sharpe=-0.86 turnover=0.3 |
| ASTERUSDT | net=0.008 sharpe=0.17 turnover=0.6 |
| ATOMUSDT | net=-0.041 sharpe=-0.59 turnover=2.6 |
| AUCTIONUSDT | net=0.004 sharpe=0.24 turnover=0.2 |
| AVAXUSDT | net=0.137 sharpe=0.75 turnover=10.4 |
| AVNTUSDT | net=-0.005 sharpe=-0.50 turnover=0.0 |
| AXSUSDT | net=0.001 sharpe=0.02 turnover=2.0 |
| BABYUSDT | net=0.003 sharpe=0.39 turnover=0.0 |
| BANDUSDT | net=0.004 sharpe=0.21 turnover=0.1 |
| BANKUSDT | net=-0.012 sharpe=-0.30 turnover=0.1 |
| BBUSDT | net=-0.001 sharpe=-0.09 turnover=0.0 |
| BCHUSDT | net=0.085 sharpe=0.66 turnover=5.3 |
| BEATUSDT | net=0.010 sharpe=0.24 turnover=0.2 |
| BELUSDT | net=-0.001 sharpe=-0.05 turnover=0.2 |
| BERAUSDT | net=0.002 sharpe=0.30 turnover=0.1 |
| BIGTIMEUSDT | net=0.002 sharpe=0.12 turnover=0.1 |
| BIOUSDT | net=0.017 sharpe=0.51 turnover=0.2 |
| BLURUSDT | net=0.002 sharpe=0.09 turnover=0.1 |
| BLZUSDT | net=0.015 sharpe=0.30 turnover=0.4 |
| BNBUSDT | net=0.272 sharpe=1.03 turnover=27.7 |
| BNTUSDT | net=0.002 sharpe=0.07 turnover=0.1 |
| BNXUSDT | net=0.005 sharpe=0.36 turnover=0.0 |
| BOMEUSDT | net=0.006 sharpe=0.10 turnover=1.3 |
| BSBUSDT | net=0.003 sharpe=0.06 turnover=0.1 |
| BTCUSDT | net=0.377 sharpe=1.36 turnover=26.4 |
| CFXUSDT | net=0.032 sharpe=0.40 turnover=1.4 |
| CHIPUSDT | net=-0.008 sharpe=-0.40 turnover=0.3 |
| CHZUSDT | net=-0.065 sharpe=-0.78 turnover=2.2 |
| COAIUSDT | net=-0.012 sharpe=-0.59 turnover=0.0 |
| COMPUSDT | net=0.023 sharpe=0.61 turnover=0.3 |
| CRVUSDT | net=0.035 sharpe=1.15 turnover=0.4 |
| CTSIUSDT | net=-0.002 sharpe=-0.19 turnover=0.1 |
| CYBERUSDT | net=0.000 sharpe=0.02 turnover=0.3 |
| CYSUSDT | net=-0.003 sharpe=-0.14 turnover=0.0 |
| DASHUSDT | net=-0.012 sharpe=-0.45 turnover=0.2 |
| DEXEUSDT | net=0.006 sharpe=0.19 turnover=0.2 |
| DOGEUSDT | net=0.159 sharpe=0.57 turnover=24.9 |
| DOGSUSDT | net=0.002 sharpe=0.09 turnover=0.1 |
| DOTUSDT | net=0.015 sharpe=0.14 turnover=5.1 |
| DYDXUSDT | net=-0.041 sharpe=-0.45 turnover=2.2 |
| EDUUSDT | net=0.010 sharpe=0.44 turnover=0.1 |
| ENAUSDT | net=0.023 sharpe=0.19 turnover=3.3 |
| ENJUSDT | net=0.002 sharpe=0.08 turnover=0.2 |
| ENSUSDT | net=-0.002 sharpe=-0.15 turnover=0.2 |
| EOSUSDT | net=0.011 sharpe=0.13 turnover=2.5 |
| ETCUSDT | net=0.057 sharpe=0.50 turnover=3.9 |
| ETHFIUSDT | net=-0.001 sharpe=-0.13 turnover=0.0 |
| ETHUSDT | net=0.169 sharpe=0.63 turnover=25.6 |
| EVAAUSDT | net=-0.036 sharpe=-1.12 turnover=1.0 |
| FARTCOINUSDT | net=-0.028 sharpe=-0.28 turnover=1.9 |
| FETUSDT | net=-0.014 sharpe=-0.66 turnover=0.2 |
| FILUSDT | net=0.027 sharpe=0.23 turnover=4.0 |
| FLMUSDT | net=-0.001 sharpe=-0.07 turnover=0.2 |
| FOLKSUSDT | net=0.006 sharpe=0.30 turnover=0.1 |
| FTMUSDT | net=0.039 sharpe=0.29 turnover=4.9 |
| FTTUSDT | net=0.004 sharpe=0.21 turnover=0.2 |
| FUNUSDT | net=0.024 sharpe=0.56 turnover=0.2 |
| GALAUSDT | net=0.030 sharpe=0.34 turnover=2.2 |
| GALUSDT | net=0.011 sharpe=0.69 turnover=0.1 |
| GASUSDT | net=0.003 sharpe=0.19 turnover=0.2 |
| GIGGLEUSDT | net=-0.002 sharpe=-0.13 turnover=0.1 |
| GMTUSDT | net=0.008 sharpe=0.11 turnover=2.5 |
| GOATUSDT | net=-0.004 sharpe=-0.40 turnover=0.1 |
| GRTUSDT | net=0.003 sharpe=0.46 turnover=0.0 |
| HBARUSDT | net=-0.012 sharpe=-0.20 turnover=0.8 |
| HIFIUSDT | net=-0.000 sharpe=-0.11 turnover=0.2 |
| HIGHUSDT | net=0.006 sharpe=0.41 turnover=0.0 |
| HNTUSDT | net=-0.003 sharpe=-0.49 turnover=0.3 |
| HUSDT | net=-0.001 sharpe=-0.03 turnover=0.2 |
| HYPERUSDT | net=-0.002 sharpe=-0.25 turnover=0.1 |
| HYPEUSDT | net=0.101 sharpe=0.77 turnover=3.2 |
| IDUSDT | net=-0.018 sharpe=-0.61 turnover=0.3 |
| INJUSDT | net=-0.012 sharpe=-0.22 turnover=1.0 |
| IOUSDT | net=-0.006 sharpe=-0.36 turnover=0.1 |
| IPUSDT | net=0.000 sharpe=0.05 turnover=0.0 |
| JASMYUSDT | net=0.007 sharpe=0.85 turnover=0.1 |
| JUPUSDT | net=-0.003 sharpe=-0.26 turnover=0.1 |
| KAITOUSDT | net=0.012 sharpe=0.56 turnover=0.2 |
| KNCUSDT | net=0.003 sharpe=0.15 turnover=0.1 |
| LABUSDT | net=0.103 sharpe=1.41 turnover=0.3 |
| LAYERUSDT | net=0.028 sharpe=0.70 turnover=0.2 |
| LDOUSDT | net=-0.025 sharpe=-0.52 turnover=0.5 |
| LEVERUSDT | net=0.005 sharpe=0.17 turnover=0.2 |
| LIGHTUSDT | net=-0.001 sharpe=-0.02 turnover=0.2 |
| LINAUSDT | net=-0.014 sharpe=-0.25 turnover=0.8 |
| LINKUSDT | net=0.002 sharpe=0.03 turnover=11.5 |
| LOOMUSDT | net=0.002 sharpe=0.34 turnover=0.1 |
| LPTUSDT | net=0.007 sharpe=0.26 turnover=0.5 |
| LQTYUSDT | net=-0.003 sharpe=-0.34 turnover=0.1 |
| LRCUSDT | net=-0.003 sharpe=-0.06 turnover=0.3 |
| LTCUSDT | net=0.012 sharpe=0.08 turnover=10.2 |
| LUNA2USDT | net=0.001 sharpe=0.04 turnover=0.5 |
| LUNAUSDT | net=0.000 sharpe=0.01 turnover=2.4 |
| MANAUSDT | net=0.011 sharpe=0.15 turnover=1.8 |
| MANTAUSDT | net=0.001 sharpe=0.05 turnover=0.2 |
| MASKUSDT | net=0.005 sharpe=0.08 turnover=1.0 |
| MATICUSDT | net=0.064 sharpe=0.38 turnover=10.6 |
| MEMEUSDT | net=-0.005 sharpe=-0.21 turnover=0.3 |
| MEWUSDT | net=-0.002 sharpe=-0.06 turnover=0.3 |
| MKRUSDT | net=-0.014 sharpe=-0.50 turnover=0.3 |
| MMTUSDT | net=0.000 sharpe=0.28 turnover=0.0 |
| MOODENGUSDT | net=0.015 sharpe=0.32 turnover=0.3 |
| MOVEUSDT | net=-0.001 sharpe=-0.03 turnover=0.4 |
| MTLUSDT | net=-0.007 sharpe=-0.16 turnover=0.4 |
| MUBARAKUSDT | net=-0.002 sharpe=-0.37 turnover=0.0 |
| MYXUSDT | net=0.073 sharpe=0.90 turnover=0.8 |
| NEARUSDT | net=0.067 sharpe=0.52 turnover=4.5 |
| NEIROETHUSDT | net=-0.027 sharpe=-0.64 turnover=0.4 |
| NEIROUSDT | net=0.021 sharpe=0.37 turnover=0.5 |
| NOTUSDT | net=0.018 sharpe=0.28 turnover=1.2 |
| NXPCUSDT | net=0.000 sharpe=0.12 turnover=0.0 |
| OCEANUSDT | net=0.014 sharpe=0.50 turnover=0.1 |
| OGNUSDT | net=0.001 sharpe=0.03 turnover=0.2 |
| OMUSDT | net=0.003 sharpe=0.17 turnover=0.1 |
| OPUSDT | net=0.024 sharpe=0.20 turnover=4.0 |
| ORDIUSDT | net=-0.055 sharpe=-0.53 turnover=3.2 |
| PAXGUSDT | net=0.008 sharpe=0.18 turnover=1.2 |
| PENGUUSDT | net=0.001 sharpe=0.02 turnover=0.4 |
| PEOPLEUSDT | net=0.013 sharpe=0.20 turnover=1.5 |
| PERPUSDT | net=0.000 sharpe=0.01 turnover=0.4 |
| PIPPINUSDT | net=0.048 sharpe=0.66 turnover=0.6 |
| PNUTUSDT | net=0.088 sharpe=1.24 turnover=0.7 |
| POLYXUSDT | net=-0.002 sharpe=-0.49 turnover=0.1 |
| POPCATUSDT | net=-0.020 sharpe=-0.72 turnover=0.3 |
| POWERUSDT | net=0.008 sharpe=0.26 turnover=0.2 |
| PUMPUSDT | net=0.019 sharpe=0.26 turnover=1.0 |
| RAREUSDT | net=-0.000 sharpe=-0.01 turnover=0.3 |
| RAVEUSDT | net=0.019 sharpe=0.45 turnover=0.2 |
| REEFUSDT | net=0.040 sharpe=0.76 turnover=0.5 |
| RIVERUSDT | net=0.043 sharpe=0.58 turnover=0.3 |
| RNDRUSDT | net=-0.011 sharpe=-0.26 turnover=0.4 |
| RSRUSDT | net=-0.004 sharpe=-0.15 turnover=0.2 |
| RUNEUSDT | net=-0.010 sharpe=-0.27 turnover=0.5 |
| RVNUSDT | net=-0.001 sharpe=-0.04 turnover=0.3 |
| SANDUSDT | net=0.069 sharpe=0.73 turnover=3.2 |
| SEIUSDT | net=0.005 sharpe=0.13 turnover=0.4 |
| SIRENUSDT | net=0.033 sharpe=0.45 turnover=0.3 |
| SOLUSDT | net=0.215 sharpe=0.76 turnover=22.7 |
| STMXUSDT | net=-0.014 sharpe=-0.65 turnover=0.4 |
| STORJUSDT | net=0.006 sharpe=0.14 turnover=0.4 |
| STOUSDT | net=-0.019 sharpe=-0.79 turnover=0.2 |
| STXUSDT | net=0.006 sharpe=0.19 turnover=0.5 |
| SUIUSDT | net=0.152 sharpe=0.79 turnover=10.1 |
| SUNUSDT | net=0.002 sharpe=0.14 turnover=0.1 |
| SUSHIUSDT | net=0.014 sharpe=0.27 turnover=0.7 |
| SXPUSDT | net=-0.013 sharpe=-0.22 turnover=0.8 |
| TAOUSDT | net=-0.035 sharpe=-0.49 turnover=1.3 |
| THETAUSDT | net=0.001 sharpe=0.05 turnover=0.2 |
| TIAUSDT | net=0.020 sharpe=0.33 turnover=0.8 |
| TNSRUSDT | net=0.001 sharpe=0.08 turnover=0.1 |
| TOMOUSDT | net=-0.028 sharpe=-0.49 turnover=1.1 |
| TONUSDT | net=-0.005 sharpe=-0.09 turnover=1.0 |
| TRBUSDT | net=0.065 sharpe=0.74 turnover=1.6 |
| TRUMPUSDT | net=-0.012 sharpe=-0.13 turnover=1.2 |
| TRXUSDT | net=0.020 sharpe=0.35 turnover=1.5 |
| TSTUSDT | net=-0.003 sharpe=-0.45 turnover=0.0 |
| TURBOUSDT | net=0.000 sharpe=0.00 turnover=0.3 |
| TUTUSDT | net=-0.008 sharpe=-0.27 turnover=0.0 |
| UMAUSDT | net=0.001 sharpe=0.06 turnover=0.2 |
| UNFIUSDT | net=-0.011 sharpe=-0.16 turnover=1.2 |
| UNIUSDT | net=0.024 sharpe=0.33 turnover=1.4 |
| USUALUSDT | net=0.017 sharpe=0.52 turnover=0.1 |
| UXLINKUSDT | net=0.018 sharpe=0.34 turnover=0.3 |
| VELVETUSDT | net=-0.015 sharpe=-0.34 turnover=0.3 |
| VETUSDT | net=0.029 sharpe=0.70 turnover=0.3 |
| VINEUSDT | net=-0.002 sharpe=-0.41 turnover=0.0 |
| VIRTUALUSDT | net=-0.011 sharpe=-0.34 turnover=0.1 |
| VOXELUSDT | net=-0.004 sharpe=-0.52 turnover=0.0 |
| WAVESUSDT | net=0.033 sharpe=0.50 turnover=1.3 |
| WCTUSDT | net=-0.003 sharpe=-0.15 turnover=0.3 |
| WIFUSDT | net=0.042 sharpe=0.32 turnover=4.8 |
| WLDUSDT | net=0.118 sharpe=0.78 turnover=4.1 |
| WLFIUSDT | net=0.030 sharpe=0.60 turnover=0.3 |
| XAIUSDT | net=0.005 sharpe=0.39 turnover=0.1 |
| XLMUSDT | net=-0.018 sharpe=-0.21 turnover=2.0 |
| XPLUSDT | net=0.005 sharpe=0.16 turnover=0.3 |
| XRPUSDT | net=0.101 sharpe=0.37 turnover=26.7 |
| XTZUSDT | net=-0.022 sharpe=-0.77 turnover=0.8 |
| YFIUSDT | net=0.001 sharpe=0.07 turnover=0.2 |
| YGGUSDT | net=-0.000 sharpe=-0.01 turnover=0.0 |
| ZECUSDT | net=0.042 sharpe=0.37 turnover=2.2 |
| ZILUSDT | net=0.001 sharpe=0.03 turnover=0.2 |
| ZROUSDT | net=-0.008 sharpe=-0.30 turnover=0.3 |
| 币安人生USDT | net=0.005 sharpe=0.28 turnover=0.0 |
