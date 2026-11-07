"""Crop and soil parameters, all taken from FAO Irrigation and Drainage Paper 56 (Allen et al., 1998).

Stage lengths: FAO-56 Table 11, rows for arid climates (wheat: the "Dec, Calif. Desert" row, used here for
15 November sowing; maize: the June row). The Pakistan "Oct/Nov, arid" small-grains row (25/35/65/40)
gives a 23% saving instead of 25% in the replay.
Crop coefficients (Kc mid, Kc end): FAO-56 Table 12. Wheat Kc ini 0.4 follows FAO-56 Fig. 29 for large,
infrequent surface wettings (Table 12 gives 0.3 for cereals; with 0.3 the replay saving is 28%).
Rooting depth and depletion fraction p: FAO-56 Table 22. We use the smaller rooting depth of the
range because FAO-56 says the smaller values may be used for irrigation scheduling, and many Delta
fields have a shallow water table that limits rooting.
Soil water at field capacity and wilting point: midpoints of the ranges in FAO-56 Table 19.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Crop:
    key: str
    name_en: str
    name_ar: str
    season: str                      # "winter" or "summer"
    stages: tuple[int, int, int, int]  # initial, development, mid-season, late season (days)
    kc: tuple[float, float, float]     # Kc ini, Kc mid, Kc end
    zr_max: float                    # maximum effective rooting depth used for scheduling (m)
    p: float                         # depletion fraction for no stress at ETc about 5 mm/day
    source: str
    stop_days: int = 20              # no irrigation advice in the last days before harvest (dry-down)

    @property
    def length(self) -> int:
        return sum(self.stages)


CROPS: dict[str, Crop] = {c.key: c for c in [
    Crop("wheat", "Wheat", "قمح", "winter", (20, 50, 60, 30), (0.40, 1.15, 0.35), 1.0, 0.55,
         "Table 11 small grains, December planting, arid desert (20/50/60/30); Table 12 Kc mid 1.15, "
         "Kc end 0.25 to 0.40; Kc ini 0.4 for large, infrequent surface wettings (Fig. 29); Table 22 Zr 1.0 to 1.5 m, p 0.55", stop_days=20),
    Crop("maize", "Maize", "ذرة شامية", "summer", (20, 35, 40, 30), (0.30, 1.20, 0.35), 1.0, 0.55,
         "Table 11 maize (grain), June planting (20/35/40/30); Table 12 Kc 0.3 / 1.20 / 0.35 (dry harvest); Table 22 Zr 1.0 to 1.7 m, p 0.55", stop_days=15),
    Crop("cotton", "Cotton", "قطن", "summer", (30, 50, 60, 55), (0.35, 1.175, 0.60), 1.0, 0.65,
         "Table 11 cotton, March to May planting, Egypt (30/50/60/55); Table 12 Kc 0.35 / 1.15 to 1.20 / 0.70 to 0.50; Table 22 Zr 1.0 to 1.7 m, p 0.65", stop_days=30),
    Crop("sugar_beet", "Sugar beet", "بنجر السكر", "winter", (35, 60, 70, 40), (0.35, 1.20, 0.70), 0.7, 0.55,
         "Table 11 sugar beet, November planting, arid regions (35/60/70/40); Table 12 Kc 0.35 / 1.20 / 0.70; Table 22 Zr 0.7 to 1.2 m, p 0.55", stop_days=25),
    Crop("potato", "Potato", "بطاطس", "winter", (25, 30, 45, 30), (0.50, 1.15, 0.75), 0.4, 0.35,
         "Table 11 potato, January/November planting, (semi) arid (25/30/45/30); Table 12 Kc 0.5 / 1.15 / 0.75; Table 22 Zr 0.4 to 0.6 m, p 0.35", stop_days=10),
    Crop("tomato", "Tomato", "طماطم", "summer", (30, 40, 40, 25), (0.60, 1.15, 0.80), 0.7, 0.40,
         "Table 11 tomato, January planting, arid region (30/40/40/25); Table 12 Kc 0.6 / 1.15 / 0.70 to 0.90; Table 22 Zr 0.7 to 1.5 m, p 0.40", stop_days=7),
    Crop("onion", "Onion (dry)", "بصل", "winter", (20, 35, 110, 45), (0.70, 1.05, 0.75), 0.3, 0.30,
         "Table 11 onion (dry), October/January planting, arid region (20/35/110/45); Table 12 Kc 0.7 / 1.05 / 0.75; Table 22 Zr 0.3 to 0.6 m, p 0.30", stop_days=20),
]}


@dataclass(frozen=True)
class Soil:
    key: str
    name_en: str
    name_ar: str
    theta_fc: float  # m3/m3
    theta_wp: float  # m3/m3

    @property
    def taw_per_m(self) -> float:
        """Total available water per metre of root zone (mm/m)."""
        return 1000.0 * (self.theta_fc - self.theta_wp)


SOILS: dict[str, Soil] = {s.key: s for s in [
    Soil("clay", "Clay", "طينية", 0.36, 0.22),
    Soil("silty_clay", "Silty clay", "طينية سلتية", 0.36, 0.23),
    Soil("loam", "Loam", "طميية", 0.25, 0.12),
    Soil("sandy_loam", "Sandy loam", "رملية طميية", 0.23, 0.11),
    Soil("sand", "Sand", "رملية", 0.12, 0.045),
]}

# Pump presets: discharge estimated from outlet size at about 2.5 m/s water velocity.
# Every farmer can replace this with their own measured value.
PUMPS_M3H = {"3in": 40.0, "4in": 70.0, "6in": 160.0}

FEDDAN_M2 = 4200.83          # 1 feddan in square metres
M3_PER_MM_FEDDAN = FEDDAN_M2 / 1000.0  # 1 mm of water over 1 feddan = 4.2 m3
