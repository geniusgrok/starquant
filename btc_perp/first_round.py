"""Five registered BTC candidates; shared causal kernel, no exchange access."""

from __future__ import annotations

import dataclasses
from typing import Any

import numpy as np

from btc_perp.causal import _funding_gap, _provenance, _sha256
from btc_perp.config import ROOT, load_config
from btc_perp.measure import _tape_problems
from btc_perp.reportio import completion, publish
from btc_perp.robustness import _public, _replay

REPORT = ROOT / "reports" / "btc_account_first_round.json"


def choose(results: dict[str, Any]) -> dict[str, Any]:
    floor = results["baseline"]["base"]["cagr"] * 0.8
    eligible = [
        name
        for name in ("half-risk", "no-adds", "half-risk-no-adds")
        if results[name]["base"]["cagr"] >= floor
        and all(not row["breaches_half_peak_line"] and not row["locked_at_end"] for row in results[name].values())
    ]
    selected = (
        max(
            eligible,
            key=lambda name: (
                min(row["cagr"] for row in results[name].values()),
                results[name]["base"]["end_cny"],
                name,
            ),
        )
        if eligible
        else "baseline"
    )
    return {"selected": selected, "eligible": eligible, "cagr_retention_floor": floor}


def run_first_round(write_report: bool = True) -> dict[str, Any]:
    problems = _tape_problems()
    premium = [ROOT / "data" / "premium" / f"BTCUSDT-8h-2026-09-{day:02d}.zip" for day in range(1, 20)]
    for path in premium:
        checksum = path.with_suffix(path.suffix + ".CHECKSUM")
        if not path.is_file() or not checksum.is_file():
            problems.append(f"missing premium archive/checksum: {path.name}")
        elif _sha256(path) != checksum.read_text().split()[0]:
            problems.append(f"premium checksum mismatch: {path.name}")
    if problems:
        report: dict[str, Any] = {
            "verified": False,
            "problems": problems,
            "completion": completion(data_validated=False, path_complete=False, economic_pass=False),
        }
        if write_report:
            publish(REPORT, report)
        return report
    cfg = load_config()
    candidates = {
        "baseline": (cfg, False),
        "half-risk": (dataclasses.replace(cfg, risk=0.024), False),
        "no-adds": (dataclasses.replace(cfg, max_units=1), False),
        "half-risk-no-adds": (dataclasses.replace(cfg, risk=0.024, max_units=1), False),
        "long-only": (cfg, True),
    }
    scenarios = {
        "base": {},
        "stop10bp": {"stop_extra": 0.001},
        "stop20bp": {"stop_extra": 0.002},
        "stop50bp": {"stop_extra": 0.005},
        "fee5bp": {"taker": 0.0005},
    }
    results: dict[str, Any] = {}
    for name, (candidate, long_only) in candidates.items():
        results[name] = {}
        for scenario, kwargs in scenarios.items():
            raw = _replay(candidate, long_only=long_only, **kwargs)
            row = _public(raw)
            row["meets_150"] = row["cagr"] >= 1.5 and row["min_equity_over_peak"] > 0.5
            row["daily_close_cny"] = [
                [int(raw["_days"][i]), float(raw["_equity"][i])] for i in range(1439, len(raw["_equity"]), 1440)
            ]
            results[name][scenario] = row
            print(name, scenario, f"CAGR={row['cagr']:.2%}", f"ratio={row['min_equity_over_peak']:.3f}", flush=True)
    base = results["baseline"]["base"]
    # Recorded causal result, not a result selected from this new experiment.
    reproduced = abs(base["end_cny"] - 1839663.45) < 0.02 and base["n_long"] == 57 and base["n_short"] == 35
    decision = (
        choose(results) if reproduced else {"selected": "baseline", "eligible": [], "blocked": "baseline mismatch"}
    )
    inputs = {
        name: _sha256(ROOT / "data" / name) for name in ("btcusdt_1m.npz", "funding.npz", "usdcny_frankfurter.json")
    }
    inputs.update({f"premium/{path.name}": _sha256(path) for path in premium})
    provenance = _provenance()
    provenance["files_sha256"]["btc_perp/first_round.py"] = _sha256(ROOT / "btc_perp/first_round.py")
    report = {
        "verified": reproduced,
        "baseline_reproduced": reproduced,
        "out_of_sample": False,
        "completion": completion(data_validated=True, path_complete=True, economic_pass=False),
        "inputs": inputs,
        "provenance": provenance,
        "results": results,
        "decision": decision,
        "candidate_configs": {
            name: dataclasses.asdict(candidate) | {"long_only": long_only}
            for name, (candidate, long_only) in candidates.items()
        },
        "funding_coverage": _funding_gap(np.load(ROOT / "data/btcusdt_1m.npz")["ts"][::60]),
        "short_counterfactual": {
            scenario: {
                "marginal_final_cny": results["baseline"][scenario]["end_cny"]
                - results["long-only"][scenario]["end_cny"],
                "note": "full-account path difference; not isolated short PnL",
            }
            for scenario in scenarios
        },
    }
    if write_report:
        publish(REPORT, report)
    return report
