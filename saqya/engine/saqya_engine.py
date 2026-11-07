"""Saqya engine: a FAO-56 root-zone water balance and a canal-rotation-aware irrigation planner.

The physics is the standard FAO-56 single crop coefficient method (Allen et al., 1998):
  ETc = Kc x ET0                                   (FAO-56 Eq. 56)
  TAW = 1000 (theta_FC - theta_WP) Zr              (Eq. 82)
  RAW = p TAW, p adjusted for ETc                  (Eq. 83 and Table 22 note)
  Ks  = (TAW - Dr) / ((1 - p) TAW) when Dr > RAW   (Eq. 84)
  Dr,i = Dr,i-1 - P - I + ETc,adj + DP             (Eq. 85, no runoff or capillary rise)

What is new here is the planner. In the old lands of the Nile Delta water reaches a field only on
its canal's "on" days (for example 5 days on, 10 days off in winter). So the real question for a
farmer is not "on which day should I irrigate" but "my turn has started: should I irrigate now, and
how much, so the crop is fine until my next turn without water running to the drain?"
plan_turn() answers exactly that question.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional, Sequence

try:  # package import (tests, simulation)
    from .crops import CROPS, M3_PER_MM_FEDDAN, SOILS, Crop, Soil
except ImportError:  # direct script use
    from crops import CROPS, M3_PER_MM_FEDDAN, SOILS, Crop, Soil  # type: ignore


# ---------------------------------------------------------------- field and crop curves
@dataclass
class Field:
    crop: Crop
    soil: Soil
    sowing: date
    area_feddan: float = 1.0
    pump_m3h: float = 70.0
    efficiency: float = 0.80      # share of the pumped water that ends up stored in the root zone
    zr_min: float = 0.20          # effective rooting depth at sowing (m)

    def das(self, d: date) -> int:
        """Days after sowing (0 on the sowing day)."""
        return (d - self.sowing).days

    def kc(self, das: int) -> float:
        l1, l2, l3, l4 = self.crop.stages
        ini, mid, end = self.crop.kc
        if das < l1:
            return ini
        if das < l1 + l2:
            return ini + (mid - ini) * (das - l1) / l2
        if das < l1 + l2 + l3:
            return mid
        if das < l1 + l2 + l3 + l4:
            return mid + (end - mid) * (das - l1 - l2 - l3) / l4
        return end

    def zr(self, das: int) -> float:
        """Rooting depth grows linearly from zr_min at sowing to zr_max at the end of development."""
        l1, l2, _, _ = self.crop.stages
        grow = l1 + l2
        if das <= 0:
            return self.zr_min
        if das >= grow:
            return self.crop.zr_max
        return self.zr_min + (self.crop.zr_max - self.zr_min) * das / grow

    def taw(self, das: int) -> float:
        return self.soil.taw_per_m * self.zr(das)

    def p(self, etc: float) -> float:
        return min(0.8, max(0.1, self.crop.p + 0.04 * (5.0 - etc)))

    def raw(self, das: int, etc: float) -> float:
        return self.p(etc) * self.taw(das)

    def in_season(self, d: date) -> bool:
        return 0 <= self.das(d) < self.crop.length

    def last_irrigation_das(self) -> int:
        """Day after sowing from which no more irrigation is advised (dry-down before harvest)."""
        return self.crop.length - self.crop.stop_days


# ---------------------------------------------------------------- canal rotation
@dataclass
class Rotation:
    on_days: int
    off_days: int
    anchor: date                 # any date on which an "on" window starts

    @property
    def cycle(self) -> int:
        return self.on_days + self.off_days

    def is_on(self, d: date) -> bool:
        return (d - self.anchor).days % self.cycle < self.on_days

    def turn_start(self, d: date) -> date:
        """Start of the on-window that contains d, or of the next one if d is an off day."""
        k = (d - self.anchor).days % self.cycle
        if k < self.on_days:
            return d - timedelta(days=k)
        return d + timedelta(days=self.cycle - k)

    def next_turn_after(self, start: date) -> date:
        return start + timedelta(days=self.cycle)

    def turn_starts(self, first: date, last: date) -> list[date]:
        out, t = [], self.turn_start(first)
        if t < first:
            t = self.next_turn_after(t)
        while t <= last:
            out.append(t)
            t = self.next_turn_after(t)
        return out


# ---------------------------------------------------------------- daily water balance
@dataclass
class DayResult:
    day: date
    das: int
    et0: float
    rain: float
    irrigation_gross: float
    kc: float
    etc: float
    etc_adj: float
    ks: float
    dr_end: float
    taw: float
    raw: float
    loss: float                  # irrigation and rain water not stored in the root zone (mm)


def step(fld: Field, d: date, dr: float, et0: float, rain: float, irr_gross: float = 0.0) -> DayResult:
    """One day of the FAO-56 balance. Water is added at the start of the day, then the crop uses water."""
    das = fld.das(d)
    taw = fld.taw(das)
    dr = min(dr, taw)  # roots grow into wetter soil: depletion in mm is kept, capped by TAW
    infiltrating = irr_gross * fld.efficiency + rain
    stored = min(infiltrating, dr)
    loss = irr_gross * (1.0 - fld.efficiency) + (infiltrating - stored)
    dr -= stored
    kc = fld.kc(das)
    etc = kc * et0
    raw = fld.raw(das, etc)
    p = fld.p(etc)
    ks = 1.0 if dr <= raw else max(0.0, (taw - dr) / ((1.0 - p) * taw))
    etc_adj = ks * etc
    dr = min(taw, dr + etc_adj)
    return DayResult(d, das, et0, rain, irr_gross, kc, etc, etc_adj, ks, dr, taw, raw, loss)


# ---------------------------------------------------------------- the planner
@dataclass
class Plan:
    turn_start: date
    next_turn: date
    action: str                  # "skip", "irrigate" or "full"
    net_mm: float
    gross_mm: float
    dr_now: float
    dr_at_next_without: float    # projected depletion at the next turn if the farmer skips
    raw_at_next: float
    taw_at_next: float
    rain_expected_mm: float
    reason: str = ""

    def m3(self, fld: Field) -> float:
        return self.gross_mm * M3_PER_MM_FEDDAN * fld.area_feddan

    def pump_minutes(self, fld: Field) -> int:
        return int(round(60.0 * self.m3(fld) / fld.pump_m3h)) if self.gross_mm > 0 else 0

    def pump_minutes_per_feddan(self, fld: Field) -> int:
        return int(round(60.0 * self.gross_mm * M3_PER_MM_FEDDAN / fld.pump_m3h)) if self.gross_mm > 0 else 0


def _project(fld: Field, start: date, dr0: float, et0: Sequence[float], rain: Sequence[float],
             n_days: int, net_irrigation: float) -> list[tuple[float, float, float]]:
    """Planning projection with no stress (Ks = 1). Returns (dr_end, raw, taw) for each day."""
    out = []
    dr = max(0.0, dr0 - net_irrigation)
    for i in range(n_days):
        d = start + timedelta(days=i)
        das = fld.das(d)
        taw = fld.taw(das)
        dr = min(dr, taw)
        dr = max(0.0, dr - rain[i])
        etc = fld.kc(das) * et0[i]
        dr = min(taw, dr + etc)
        out.append((dr, fld.raw(das, etc), taw))
    return out


def plan_turn(fld: Field, rot: Rotation, turn_start: date, dr_now: float,
              et0_fc: Sequence[float], rain_fc: Sequence[float],
              safety: float = 0.90, min_net_mm: float = 40.0) -> Plan:
    """Decide what to do on the first day of a canal turn.

    et0_fc and rain_fc are forecasts for turn_start, turn_start + 1, ... and must cover at least
    the days up to (not including) the start of the next turn. The plan keeps the projected depletion
    below safety x RAW on every day until the next turn, using as little water as possible and never
    more than the soil can hold (refill to field capacity at most).
    """
    nxt = rot.next_turn_after(turn_start)
    n = (nxt - turn_start).days
    if len(et0_fc) < n or len(rain_fc) < n:
        raise ValueError("forecast must cover the days until the next turn")
    # no advice during the dry-down before harvest: only protect the crop until the cut-off day
    n = min(n, max(0, fld.last_irrigation_das() - fld.das(turn_start)))
    rain_expected = float(sum(rain_fc[:n]))
    if n == 0:
        return Plan(turn_start, nxt, "skip", 0.0, 0.0, dr_now, dr_now, 0.0,
                    fld.taw(fld.das(turn_start)), rain_expected, "harvest")

    def worst(net: float, s: float) -> float:
        traj = _project(fld, turn_start, dr_now, et0_fc, rain_fc, n, net)
        return max((dr - s * raw for dr, raw, _ in traj), default=-1.0)

    without = _project(fld, turn_start, dr_now, et0_fc, rain_fc, n, 0.0)
    dr_next = without[-1][0] if without else dr_now
    raw_next = without[-1][1] if without else 0.0
    taw_next = without[-1][2] if without else fld.taw(fld.das(turn_start))

    if n == 0 or worst(0.0, safety) <= 0:
        reason = "rain" if rain_expected >= 5 and worst(0.0, safety) <= 0 < _no_rain_worst(fld, turn_start, dr_now, et0_fc, n, safety) else "enough"
        return Plan(turn_start, nxt, "skip", 0.0, 0.0, dr_now, dr_next, raw_next, taw_next, rain_expected, reason)

    if worst(dr_now, safety) > 0:
        net, action, reason = dr_now, "full", "long gap or hot weather: refill the root zone"
    else:
        lo, hi = 0.0, dr_now
        for _ in range(40):
            mid = 0.5 * (lo + hi)
            if worst(mid, safety) <= 0:
                hi = mid
            else:
                lo = mid
        net, action, reason = hi, "irrigate", "top up to last until the next turn"

    if net < min_net_mm:
        if worst(0.0, 1.0) <= 0:  # skipping only uses the safety margin: skip
            return Plan(turn_start, nxt, "skip", 0.0, 0.0, dr_now, dr_next, raw_next, taw_next, rain_expected, "enough")
        net = min_net_mm  # a basin cannot be irrigated with less than this
    gross = net / fld.efficiency
    return Plan(turn_start, nxt, action, net, gross, dr_now, dr_next, raw_next, taw_next, rain_expected, reason)


def _no_rain_worst(fld: Field, start: date, dr0: float, et0: Sequence[float], n: int, s: float) -> float:
    traj = _project(fld, start, dr0, et0, [0.0] * n, n, 0.0)
    return max((dr - s * raw for dr, raw, _ in traj), default=-1.0)


# ---------------------------------------------------------------- whole-season replay helpers
@dataclass
class SeasonResult:
    days: list[DayResult] = field(default_factory=list)
    plans: list[Plan] = field(default_factory=list)

    @property
    def gross_mm(self) -> float:
        return sum(d.irrigation_gross for d in self.days)

    @property
    def events(self) -> int:
        return sum(1 for d in self.days if d.irrigation_gross > 0)

    cutoff_das: int = 10**6      # stress is only counted before the dry-down period

    @property
    def stress_days(self) -> int:
        return sum(1 for d in self.days if d.ks < 0.999 and d.das < self.cutoff_das)

    @property
    def et_deficit_mm(self) -> float:
        return sum(d.etc - d.etc_adj for d in self.days if d.das < self.cutoff_das)

    @property
    def etc_mm(self) -> float:
        return sum(d.etc for d in self.days)

    @property
    def loss_mm(self) -> float:
        return sum(d.loss for d in self.days)

    @property
    def rain_mm(self) -> float:
        return sum(d.rain for d in self.days)


def run_season(fld: Field, et0: dict[date, float], rain: dict[date, float],
               irrigation_on: dict[date, float]) -> SeasonResult:
    """Replay a season with a fixed list of gross irrigations (mm) by date, starting at field capacity."""
    res, dr = SeasonResult(), 0.0
    for i in range(fld.crop.length):
        d = fld.sowing + timedelta(days=i)
        r = step(fld, d, dr, et0[d], rain.get(d, 0.0), irrigation_on.get(d, 0.0))
        res.days.append(r)
        dr = r.dr_end
    return res


def make_field(crop: str = "wheat", soil: str = "clay", sowing: Optional[date] = None, **kw) -> Field:
    return Field(CROPS[crop], SOILS[soil], sowing or date(2025, 11, 15), **kw)
