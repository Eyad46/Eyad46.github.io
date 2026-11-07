"""Figures for the slides and the video.

Usage: python3 sim/figures.py data/ results/ figures/
"""
from __future__ import annotations

import csv
import json
import statistics
import sys
from datetime import date, timedelta
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine"))
sys.path.insert(0, str(ROOT / "sim"))
from crops import M3_PER_MM_FEDDAN  # noqa: E402
import run_sim as rs  # noqa: E402
from saqya_engine import Rotation, make_field, plan_turn  # noqa: E402

SAQYA, CONV, EVERY = "#2a78d6", "#eb6834", "#8a8984"
INK, MUTED, GRID, SURF = "#1d2329", "#5b6470", "#e3e6e8", "#ffffff"
plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 13, "axes.edgecolor": MUTED, "axes.labelcolor": INK,
    "xtick.color": MUTED, "ytick.color": MUTED, "axes.spines.top": False, "axes.spines.right": False,
    "figure.facecolor": SURF, "axes.facecolor": SURF, "savefig.facecolor": SURF,
})


def season_traces(et0, rain, sow, j):
    fld = make_field("wheat", "clay", sow, efficiency=rs.EFFICIENCY)
    harvest = sow + timedelta(days=fld.crop.length - 1)
    rot = Rotation(rs.ON, rs.OFF, anchor=sow - timedelta(days=j))
    clim = rs.climatology(et0, (sow - timedelta(days=10), harvest + timedelta(days=10)))
    import random
    import zlib
    rng = random.Random(zlib.crc32(f"fig-{sow}-{j}".encode()))
    turns = set(rot.turn_starts(sow + timedelta(days=1), harvest))

    def saqya(d, dr, res):
        if d not in turns:
            return 0.0
        err = rng.gauss(0.0, rs.ERR_SD)
        e, r = [], []
        for i in range(rot.cycle + 1):
            dd = d + timedelta(days=i)
            e.append(max(0.0, et0[dd] * (1 + err)) if i < rs.FC_HORIZON else clim[(dd.month, dd.day)])
            r.append(rain[dd] if i < rs.RAIN_HORIZON else 0.0)
        return plan_turn(fld, rot, d, dr, e, r).gross_mm

    conv_days = {rs.first_on_day(rot, sow + timedelta(days=k)) for k in rs.CONV_TARGET_DAYS}

    def conventional(d, dr, res):
        return rs.CONV_GROSS if d in conv_days else 0.0

    return fld, rot, rs.simulate(fld, rot, et0, rain, saqya), rs.simulate(fld, rot, et0, rain, conventional)


def fig_timeline(data: Path, out: Path, factors) -> None:
    _, et0, rain = rs.load_site(data / "weather_sakha_kafr_el_sheikh.json")
    et0 = rs.corrected(et0, factors)
    sow = date(2023, 11, 15)
    fld, rot, sq, cv = season_traces(et0, rain, sow, 0)
    fig, axes = plt.subplots(2, 1, figsize=(13, 6.6), sharex=True, sharey=True)
    for ax, res, col, title in [(axes[0], cv, CONV, "Conventional: 5 fixed irrigations"),
                                (axes[1], sq, SAQYA, "Saqya: decides at every canal turn")]:
        days = [r.day for r in res.days]
        left = [r.taw - r.dr_end for r in res.days]
        stress = [r.taw - r.raw for r in res.days]
        taw = [r.taw for r in res.days]
        d0 = days[0]
        while d0 <= days[-1]:
            if rot.is_on(d0):
                ax.axvspan(d0, d0 + timedelta(days=1), color="#dbe9f6", lw=0, zorder=0)
            d0 += timedelta(days=1)
        ax.plot(days, taw, color=MUTED, lw=1, ls=(0, (2, 2)), zorder=2)
        ax.plot(days, stress, color="#b42318", lw=1.2, ls=(0, (5, 3)), zorder=2)
        ax.plot(days, left, color=col, lw=2.4, zorder=3)
        tot = 0.0
        for r in res.days:
            if r.irrigation_gross > 0:
                tot += r.irrigation_gross
                ax.annotate("", xy=(r.day, 168), xytext=(r.day, 186),
                            arrowprops=dict(arrowstyle="-|>", color=col, lw=1.6))
        cut = fld.sowing + timedelta(days=fld.last_irrigation_das())
        ax.axvline(cut, color=MUTED, lw=0.8)
        m3 = (tot + rs.CONV_GROSS) * M3_PER_MM_FEDDAN
        stress_days = res.stress_days
        ax.set_title(f"{title}   |   {m3:,.0f} m³ per feddan, {res.events + 1} irrigations, "
                     f"{stress_days} stress days", loc="left", fontsize=13.5, color=INK, pad=6)
        ax.set_ylim(0, 192)
        ax.grid(axis="y", color=GRID, lw=0.8)
        ax.set_ylabel("water in root zone (mm)")
    axes[1].text(fld.sowing + timedelta(days=fld.last_irrigation_das() + 2), 150, "dry-down\nbefore harvest",
                 color=MUTED, fontsize=10.5)
    axes[1].xaxis.set_major_formatter(mdates.DateFormatter("%b"))
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch
    handles = [Patch(facecolor="#dbe9f6", edgecolor="none", label="canal turn (water in the canal)"),
               Line2D([], [], color=INK, lw=2.4, label="water in the root zone"),
               Line2D([], [], color="#b42318", lw=1.2, ls=(0, (5, 3)), label="stress line (below it the wheat is short of water)"),
               Line2D([], [], color=MUTED, lw=1, ls=(0, (2, 2)), label="root zone full"),
               Line2D([], [], color=INK, lw=0, marker=7, markersize=9, label="irrigation")]
    fig.legend(handles=handles, loc="upper left", bbox_to_anchor=(0.01, 0.935), ncol=5, frameon=False, fontsize=10.5,
               handlelength=1.8, columnspacing=1.4)
    fig.suptitle("Wheat at Sakha, Kafr El-Sheikh, season 2023/24 (5 days on, 10 days off)",
                 x=0.01, ha="left", fontsize=15, color=INK, fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.9))
    fig.savefig(out / "fig_timeline.png", dpi=200)
    plt.close(fig)


def fig_bars(res_dir: Path, out: Path) -> None:
    s = json.loads((res_dir / "wheat_summary_corrected.json").read_text())
    items = [("Irrigate at every turn\n(head-end habit)", s["every_turn"], EVERY),
             ("Conventional\n5 irrigations", s["conventional"], CONV),
             ("Saqya", s["saqya"], SAQYA)]
    fig, ax = plt.subplots(figsize=(12, 4.6))
    for i, (lab, v, col) in enumerate(items):
        y = len(items) - 1 - i
        ax.barh(y, v["m3_per_feddan_mean"], height=0.56, color=col, zorder=3)
        if v["m3_per_feddan_max"] > v["m3_per_feddan_min"]:
            ax.plot([v["m3_per_feddan_min"], v["m3_per_feddan_max"]], [y, y], color=INK, lw=1.4, zorder=4)
            for xx in (v["m3_per_feddan_min"], v["m3_per_feddan_max"]):
                ax.plot([xx, xx], [y - 0.1, y + 0.1], color=INK, lw=1.4, zorder=4)
        ax.text(max(v["m3_per_feddan_mean"], v["m3_per_feddan_max"]) + 60, y + 0.08,
                f"{v['m3_per_feddan_mean']:,.0f} m³", va="center", fontsize=14, color=INK, fontweight="bold")
        ax.text(max(v["m3_per_feddan_mean"], v["m3_per_feddan_max"]) + 60, y - 0.2,
                f"crop water shortfall: {v['et_deficit_mm_mean']:.1f} mm", va="center", fontsize=11, color=MUTED)
        ax.text(-60, y, lab, ha="right", va="center", fontsize=13, color=INK)
    ax.set_yticks([])
    ax.set_xlim(0, 5400)
    ax.set_xlabel("water per feddan per wheat season (m³), sowing irrigation included")
    ax.grid(axis="x", color=GRID, lw=0.8, zorder=0)
    ax.spines["left"].set_visible(False)
    sav = s["saving_vs_conventional"]
    ax.set_title(f"Saqya used {100 * sav['share_mean']:.0f}% less water than the conventional schedule\n"
                 "mean of 180 cases (36 real site-seasons x 5 canal timings); whiskers: lowest to highest case",
                 loc="left", fontsize=12.5, color=INK)
    fig.tight_layout()
    fig.subplots_adjust(left=0.2)
    fig.savefig(out / "fig_bars.png", dpi=200)
    plt.close(fig)


def fig_sites(res_dir: Path, out: Path) -> None:
    rows = list(csv.DictReader(open(res_dir / "wheat_runs_corrected.csv")))
    names = {"damanhour_beheira": "Damanhour, Beheira", "mansoura_dakahlia": "Mansoura, Dakahlia",
             "sakha_kafr_el_sheikh": "Sakha, Kafr El-Sheikh", "shibin_menoufia": "Shibin El Kom, Menoufia",
             "tanta_gharbia": "Tanta, Gharbia", "zagazig_sharqia": "Zagazig, Sharqia"}
    sow = rs.CONV_GROSS

    def saving(r):
        a = float(r["saqya_gross_mm"]) + sow
        b = float(r["conventional_gross_mm"]) + sow
        return 100 * (1 - a / b)

    order = sorted(names, key=lambda k: statistics.fmean(saving(r) for r in rows if r["site"] == k))
    fig, ax = plt.subplots(figsize=(12, 4.6))
    for y, k in enumerate(order):
        vals = [saving(r) for r in rows if r["site"] == k]
        ax.scatter(vals, [y] * len(vals), s=26, color=SAQYA, alpha=0.35, lw=0, zorder=3)
        m = statistics.fmean(vals)
        ax.plot([m, m], [y - 0.28, y + 0.28], color=INK, lw=2.4, zorder=4)
        ax.text(m, y + 0.36, f"{m:.0f}%", ha="center", fontsize=11.5, color=INK)
        ax.text(-1.5, y, names[k], ha="right", va="center", fontsize=12.5, color=INK)
    ax.set_yticks([])
    ax.set_xlim(0, 60)
    ax.set_xlabel("water saved compared with the conventional schedule (%)  |  each dot = one case (season and canal timing)")
    ax.grid(axis="x", color=GRID, lw=0.8, zorder=0)
    ax.spines["left"].set_visible(False)
    fig.tight_layout()
    fig.subplots_adjust(left=0.22)
    fig.savefig(out / "fig_sites.png", dpi=200)
    plt.close(fig)


def main() -> None:
    data, res_dir, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    out.mkdir(parents=True, exist_ok=True)
    factors = json.loads((res_dir / "et0_monthly_factors.json").read_text())
    fig_timeline(data, out, factors)
    fig_bars(res_dir, out)
    fig_sites(res_dir, out)
    print("figures in", out)


if __name__ == "__main__":
    main()
