"""Replay six wheat seasons at six Nile Delta sites: Saqya's advice versus conventional practice.

Usage: python3 sim/run_sim.py data/ results/

Truth: daily ET0 and rain from the ERA5 reanalysis (Open-Meteo archive).
What Saqya is allowed to know when it decides, at the start of each canal turn:
  * days 1 to 7: ET0 with a random error (one draw per decision, standard deviation 12%)
  * days 8 and later: the long-term average ET0 for that calendar day (other seasons only)
  * rain: only the next 3 days; rain further ahead is ignored (so Saqya never skips a turn
    because of a rain forecast that might not come)
Canal rotation: 5 days on, 10 days off (the winter rotation described by FAO for the Delta).
Conventional practice: 5 irrigations including the sowing irrigation, each about 435 m3/feddan
(103.5 mm), the mean of the conventional treatment in a Sakha field trial (El-Hadidi et al., 2016:
2,173 m3/feddan in 5 irrigations), given on the first canal day after days 30, 60, 90 and 120.
Both strategies use the same application efficiency (80%) and start at field capacity after the
same sowing irrigation, so any difference comes only from timing and amount. Water stress is
counted until 20 days before harvest (wheat is left to dry before harvest).

ET0 bias correction: ERA5-based ET0 is 10 to 25% higher than station ET0 in the Delta. We scale it,
month by month, to station values computed with CROPWAT (FAO Penman-Monteith) for Sharkia in 2021
(Table 1 in a 2023 paper in the Bulletin of the National Research Centre, doi 10.1186/s42269-023-01068-z).
Summer station values for Sakha (Ibrahim et al., 2009) show the same size of difference.
The uncorrected run is kept as a sensitivity test.
"""
from __future__ import annotations

import csv
import json
import random
import statistics
import sys
import zlib
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine"))
from crops import M3_PER_MM_FEDDAN  # noqa: E402
from saqya_engine import Rotation, SeasonResult, make_field, plan_turn, step  # noqa: E402

SOW_YEARS = [2019, 2020, 2021, 2022, 2023, 2024]
SOW_MONTH_DAY = (11, 15)
ON, OFF = 5, 10
CONV_GROSS = 2172.96 / 5 / M3_PER_MM_FEDDAN        # 103.4 mm per irrigation
CONV_TARGET_DAYS = (30, 60, 90, 120)
EVERY_TURN_LAST_DAY = 130
EFFICIENCY = 0.80
ERR_SD = 0.12
RAIN_HORIZON = 3
FC_HORIZON = 7
# station ET0 (mm/day), Sharkia, 2021, months 1..12
STATION_ET0 = [2.17, 2.73, 3.69, 5.24, 6.76, 6.79, 6.77, 6.27, 5.05, 3.89, 2.75, 2.07]
REFERENCE_SITE = "zagazig_sharqia"


def load_site(path: Path):
    d = json.loads(path.read_text())
    days = [date.fromisoformat(t) for t in d["daily"]["time"]]
    et0 = dict(zip(days, d["daily"]["et0_fao_evapotranspiration"]))
    rain = dict(zip(days, d["daily"]["precipitation_sum"]))
    return d.get("site_name", path.stem), et0, rain


def monthly_factors(ref_et0: dict[date, float]) -> list[float]:
    """Station / ERA5 ratio for each month, from the reference site's ERA5 climatology."""
    acc: dict[int, list[float]] = {}
    for d, v in ref_et0.items():
        acc.setdefault(d.month, []).append(v)
    return [STATION_ET0[m - 1] / statistics.fmean(acc[m]) for m in range(1, 13)]


def corrected(et0: dict[date, float], f: list[float]) -> dict[date, float]:
    return {d: v * f[d.month - 1] for d, v in et0.items()}


def climatology(et0: dict[date, float], exclude: tuple[date, date]) -> dict[tuple[int, int], float]:
    acc: dict[tuple[int, int], list[float]] = {}
    for d, v in et0.items():
        if exclude[0] <= d <= exclude[1]:
            continue
        acc.setdefault((d.month, d.day), []).append(v)
    clim = {k: statistics.fmean(v) for k, v in acc.items()}
    clim.setdefault((2, 29), clim[(2, 28)])
    return clim


def first_on_day(rot: Rotation, d: date) -> date:
    while not rot.is_on(d):
        d += timedelta(days=1)
    return d


def simulate(fld, rot, et0, rain, decide):
    """decide(day, dr) -> gross irrigation (mm) for that day."""
    res, dr = SeasonResult(), 0.0
    res.cutoff_das = fld.last_irrigation_das()
    for i in range(fld.crop.length):
        d = fld.sowing + timedelta(days=i)
        g = decide(d, dr, res)
        r = step(fld, d, dr, et0[d], rain[d], g)
        res.days.append(r)
        dr = r.dr_end
    return res


def run_one(site_key: str, et0: dict, rain: dict, year: int, j: int) -> dict:
    sow = date(year, *SOW_MONTH_DAY)
    fld = make_field("wheat", "clay", sow, efficiency=EFFICIENCY)
    harvest = sow + timedelta(days=fld.crop.length - 1)
    rot = Rotation(ON, OFF, anchor=sow - timedelta(days=j))   # sowing fell on day j of a turn
    clim = climatology(et0, (sow - timedelta(days=10), harvest + timedelta(days=10)))
    rng = random.Random(zlib.crc32(f"{site_key}-{year}-{j}".encode()))
    turns = set(rot.turn_starts(sow + timedelta(days=1), harvest))

    def saqya(d, dr, res):
        if d not in turns:
            return 0.0
        err = rng.gauss(0.0, ERR_SD)
        n = rot.cycle + 1
        et0_fc, rain_fc = [], []
        for i in range(n):
            dd = d + timedelta(days=i)
            if i < FC_HORIZON:
                et0_fc.append(max(0.0, et0.get(dd, clim[(dd.month, dd.day)]) * (1 + err)))
            else:
                et0_fc.append(clim[(dd.month, dd.day)])
            rain_fc.append(rain.get(dd, 0.0) if i < RAIN_HORIZON else 0.0)
        plan = plan_turn(fld, rot, d, dr, et0_fc, rain_fc)
        res.plans.append(plan)
        return plan.gross_mm

    conv_days = {first_on_day(rot, sow + timedelta(days=k)) for k in CONV_TARGET_DAYS}

    def conventional(d, dr, res):
        return CONV_GROSS if d in conv_days else 0.0

    def every_turn(d, dr, res):
        return CONV_GROSS if (d in turns and fld.das(d) <= EVERY_TURN_LAST_DAY) else 0.0

    out = {"site": site_key, "sow_year": year, "turn_day_at_sowing": j}
    for name, fn in [("saqya", saqya), ("conventional", conventional), ("every_turn", every_turn)]:
        r = simulate(fld, rot, et0, rain, fn)
        out.update({
            f"{name}_gross_mm": round(r.gross_mm, 2),
            f"{name}_events": r.events,
            f"{name}_stress_days": r.stress_days,
            f"{name}_et_deficit_mm": round(r.et_deficit_mm, 2),
            f"{name}_loss_mm": round(r.loss_mm, 2),
        })
        if name == "saqya":
            out["etc_mm"] = round(r.etc_mm, 2)
            out["rain_mm"] = round(r.rain_mm, 2)
            out["saqya_skips"] = sum(1 for p in r.plans if p.action == "skip")
            out["saqya_full"] = sum(1 for p in r.plans if p.action == "full")
    return out


def main() -> None:
    data, outdir = Path(sys.argv[1]), Path(sys.argv[2])
    outdir.mkdir(parents=True, exist_ok=True)
    _, ref_et0, _ = load_site(data / f"weather_{REFERENCE_SITE}.json")
    factors = monthly_factors(ref_et0)
    (outdir / "et0_monthly_factors.json").write_text(json.dumps([round(x, 4) for x in factors]))
    print("ET0 factors by month:", [round(x, 3) for x in factors])
    for variant, use_factors in [("corrected", True), ("era5_raw", False)]:
        summarise(data, outdir, variant, factors if use_factors else None)


def summarise(data: Path, outdir: Path, variant: str, factors) -> None:
    rows = []
    for f in sorted(data.glob("weather_*.json")):
        key = f.stem.replace("weather_", "")
        name, et0, rain = load_site(f)
        if factors:
            et0 = corrected(et0, factors)
        for y in SOW_YEARS:
            for j in range(ON):
                rows.append(run_one(key, et0, rain, y, j))
    with open(outdir / f"wheat_runs_{variant}.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    sow_irr = CONV_GROSS  # the same sowing irrigation for every strategy

    def total_m3(r, k):
        return (r[f"{k}_gross_mm"] + sow_irr) * M3_PER_MM_FEDDAN

    summ = {"variant": variant, "runs": len(rows), "sites": len({r["site"] for r in rows}), "seasons": len(SOW_YEARS),
            "rotation": f"{ON} on / {OFF} off", "efficiency": EFFICIENCY,
            "conventional_gross_per_irrigation_mm": round(CONV_GROSS, 2)}
    for k in ["saqya", "conventional", "every_turn"]:
        m3 = [total_m3(r, k) for r in rows]
        summ[k] = {
            "m3_per_feddan_mean": round(statistics.fmean(m3), 1),
            "m3_per_feddan_min": round(min(m3), 1),
            "m3_per_feddan_max": round(max(m3), 1),
            "irrigations_mean_incl_sowing": round(statistics.fmean(r[f"{k}_events"] + 1 for r in rows), 2),
            "stress_days_mean": round(statistics.fmean(r[f"{k}_stress_days"] for r in rows), 2),
            "runs_with_stress": sum(1 for r in rows if r[f"{k}_stress_days"] > 0),
            "et_deficit_mm_mean": round(statistics.fmean(r[f"{k}_et_deficit_mm"] for r in rows), 2),
            "loss_mm_mean": round(statistics.fmean(r[f"{k}_loss_mm"] for r in rows), 2),
        }
    sav = [1 - total_m3(r, "saqya") / total_m3(r, "conventional") for r in rows]
    sav_m3 = [total_m3(r, "conventional") - total_m3(r, "saqya") for r in rows]
    summ["saving_vs_conventional"] = {
        "share_mean": round(statistics.fmean(sav), 4), "share_min": round(min(sav), 4),
        "share_max": round(max(sav), 4), "share_median": round(statistics.median(sav), 4),
        "m3_per_feddan_mean": round(statistics.fmean(sav_m3), 1),
        "runs_saqya_uses_less": sum(1 for s in sav if s > 0),
    }
    summ["etc_mm_mean"] = round(statistics.fmean(r["etc_mm"] for r in rows), 1)
    summ["rain_mm_mean"] = round(statistics.fmean(r["rain_mm"] for r in rows), 1)
    summ["saqya_skips_mean"] = round(statistics.fmean(r["saqya_skips"] for r in rows), 2)
    summ["saqya_full_mean"] = round(statistics.fmean(r["saqya_full"] for r in rows), 2)
    by_site = {}
    for s in sorted({r["site"] for r in rows}):
        rs = [r for r in rows if r["site"] == s]
        by_site[s] = {
            "saving_share_mean": round(statistics.fmean(1 - total_m3(r, "saqya") / total_m3(r, "conventional") for r in rs), 4),
            "saqya_m3": round(statistics.fmean(total_m3(r, "saqya") for r in rs), 1),
            "conventional_m3": round(statistics.fmean(total_m3(r, "conventional") for r in rs), 1),
            "saqya_stress_days": round(statistics.fmean(r["saqya_stress_days"] for r in rs), 2),
            "conventional_stress_days": round(statistics.fmean(r["conventional_stress_days"] for r in rs), 2),
            "rain_mm": round(statistics.fmean(r["rain_mm"] for r in rs), 1),
        }
    summ["by_site"] = by_site
    (outdir / f"wheat_summary_{variant}.json").write_text(json.dumps(summ, indent=2))
    print(json.dumps({k: v for k, v in summ.items() if k != "by_site"}, indent=2))


if __name__ == "__main__":
    main()
