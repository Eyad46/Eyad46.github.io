/* Saqya engine (browser and Node). Same method as engine/saqya_engine.py:
   FAO-56 single crop coefficient water balance + a planner built around the canal rotation. */
(function (root) {
  'use strict';

  const CROPS = {
    wheat:      { en: 'Wheat',       ar: 'القمح',       stages: [20, 50, 60, 30],  kc: [0.40, 1.15, 0.35], zrMax: 1.0, p: 0.55, stop: 20 },
    sugar_beet: { en: 'Sugar beet',  ar: 'البنجر',      stages: [35, 60, 70, 40],  kc: [0.35, 1.20, 0.70], zrMax: 0.7, p: 0.55, stop: 25 },
    potato:     { en: 'Potato',      ar: 'البطاطس',     stages: [25, 30, 45, 30],  kc: [0.50, 1.15, 0.75], zrMax: 0.4, p: 0.35, stop: 10 },
    onion:      { en: 'Onion',       ar: 'البصل',       stages: [20, 35, 110, 45], kc: [0.70, 1.05, 0.75], zrMax: 0.3, p: 0.30, stop: 20 },
    maize:      { en: 'Maize',       ar: 'الذرة',       stages: [20, 35, 40, 30],  kc: [0.30, 1.20, 0.35], zrMax: 1.0, p: 0.55, stop: 15 },
    cotton:     { en: 'Cotton',      ar: 'القطن',       stages: [30, 50, 60, 55],  kc: [0.35, 1.175, 0.60], zrMax: 1.0, p: 0.65, stop: 30 },
    tomato:     { en: 'Tomato',      ar: 'الطماطم',     stages: [30, 40, 40, 25],  kc: [0.60, 1.15, 0.80], zrMax: 0.7, p: 0.40, stop: 7 },
  };
  const SOILS = {
    clay:       { en: 'Clay (Delta old lands)', ar: 'طينية', fc: 0.36, wp: 0.22 },
    silty_clay: { en: 'Silty clay',             ar: 'طينية سلتية', fc: 0.36, wp: 0.23 },
    loam:       { en: 'Loam',                   ar: 'طميية', fc: 0.25, wp: 0.12 },
    sandy_loam: { en: 'Sandy loam',             ar: 'رملية طميية', fc: 0.23, wp: 0.11 },
  };
  const PUMPS = { '3in': 40, '4in': 70, '6in': 160 };
  const M3_PER_MM_FEDDAN = 4.20083;
  // Station / ERA5 ratio of ET0 by month (Delta), see sim/run_sim.py
  const ET0_FACTORS = [0.766, 0.843, 0.805, 0.881, 0.94, 0.883, 0.896, 0.899, 0.835, 0.846, 0.827, 0.768];
  const CONV_GROSS = 2172.96 / 5 / M3_PER_MM_FEDDAN;   // 103.4 mm, conventional irrigation depth
  const CONV_DAYS = [30, 60, 90, 120];

  // ---------- dates as integer day numbers (UTC) ----------
  const dnum = (iso) => Math.round(Date.parse(iso + 'T00:00:00Z') / 86400000);
  const iso = (dn) => new Date(dn * 86400000).toISOString().slice(0, 10);
  const monthOf = (dn) => new Date(dn * 86400000).getUTCMonth();   // 0..11
  const weekdayOf = (dn) => new Date(dn * 86400000).getUTCDay();    // 0 = Sunday

  function makeField(cropKey, soilKey, sowDn, areaFeddan, pumpM3h, efficiency) {
    const crop = CROPS[cropKey], soil = SOILS[soilKey];
    const length = crop.stages.reduce((a, b) => a + b, 0);
    const f = {
      cropKey, soilKey, crop, soil, sowDn, length,
      area: areaFeddan || 1, pump: pumpM3h || 70, eff: efficiency || 0.8, zrMin: 0.2,
      das(dn) { return dn - this.sowDn; },
      kc(das) {
        const [l1, l2, l3, l4] = crop.stages, [ini, mid, end] = crop.kc;
        if (das < l1) return ini;
        if (das < l1 + l2) return ini + (mid - ini) * (das - l1) / l2;
        if (das < l1 + l2 + l3) return mid;
        if (das < l1 + l2 + l3 + l4) return mid + (end - mid) * (das - l1 - l2 - l3) / l4;
        return end;
      },
      zr(das) {
        const grow = crop.stages[0] + crop.stages[1];
        if (das <= 0) return this.zrMin;
        if (das >= grow) return crop.zrMax;
        return this.zrMin + (crop.zrMax - this.zrMin) * das / grow;
      },
      taw(das) { return 1000 * (soil.fc - soil.wp) * this.zr(das); },
      p(etc) { return Math.min(0.8, Math.max(0.1, crop.p + 0.04 * (5 - etc))); },
      raw(das, etc) { return this.p(etc) * this.taw(das); },
      lastIrrigationDas() { return length - crop.stop; },
    };
    return f;
  }

  function makeRotation(on, off, anchorDn) {
    const cycle = on + off;
    const mod = (a, n) => ((a % n) + n) % n;
    return {
      on, off, cycle, anchor: anchorDn,
      isOn(dn) { return mod(dn - anchorDn, cycle) < on; },
      turnStart(dn) { const k = mod(dn - anchorDn, cycle); return k < on ? dn - k : dn + (cycle - k); },
      next(startDn) { return startDn + cycle; },
      turnStarts(first, last) {
        const out = []; let t = this.turnStart(first);
        if (t < first) t = this.next(t);
        while (t <= last) { out.push(t); t = this.next(t); }
        return out;
      },
    };
  }

  function step(f, dn, dr, et0, rain, irrGross) {
    irrGross = irrGross || 0;
    const das = f.das(dn), taw = f.taw(das);
    dr = Math.min(dr, taw);
    const infil = irrGross * f.eff + rain;
    const stored = Math.min(infil, dr);
    const loss = irrGross * (1 - f.eff) + (infil - stored);
    dr -= stored;
    const kc = f.kc(das), etc = kc * et0, raw = f.raw(das, etc), p = f.p(etc);
    const ks = dr <= raw ? 1 : Math.max(0, (taw - dr) / ((1 - p) * taw));
    const etcAdj = ks * etc;
    dr = Math.min(taw, dr + etcAdj);
    return { dn, das, et0, rain, irr: irrGross, kc, etc, etcAdj, ks, dr, taw, raw, loss };
  }

  function project(f, startDn, dr0, et0, rain, n, net) {
    const out = []; let dr = Math.max(0, dr0 - net);
    for (let i = 0; i < n; i++) {
      const das = f.das(startDn + i), taw = f.taw(das);
      dr = Math.min(dr, taw);
      dr = Math.max(0, dr - rain[i]);
      const etc = f.kc(das) * et0[i];
      dr = Math.min(taw, dr + etc);
      out.push([dr, f.raw(das, etc), taw]);
    }
    return out;
  }

  function planTurn(f, rot, turnDn, drNow, et0Fc, rainFc, safety, minNet) {
    safety = safety == null ? 0.9 : safety; minNet = minNet == null ? 40 : minNet;
    const nxt = rot.next(turnDn);
    let n = nxt - turnDn;
    n = Math.min(n, Math.max(0, f.lastIrrigationDas() - f.das(turnDn)));
    const rainExpected = rainFc.slice(0, n).reduce((a, b) => a + b, 0);
    const base = { turnDn, nextDn: nxt, drNow, rainExpected, n };
    if (n === 0) return Object.assign(base, { action: 'harvest', net: 0, gross: 0, drNext: drNow });
    const worst = (net, s, rain) => {
      const tr = project(f, turnDn, drNow, et0Fc, rain || rainFc, n, net);
      return Math.max(...tr.map(([dr, raw]) => dr - s * raw));
    };
    const without = project(f, turnDn, drNow, et0Fc, rainFc, n, 0);
    const last = without[without.length - 1];
    Object.assign(base, { drNext: last[0], rawNext: last[1], tawNext: last[2] });
    if (worst(0, safety) <= 0) {
      const zero = new Array(n).fill(0);
      const becauseRain = rainExpected >= 5 && worst(0, safety, zero) > 0;
      return Object.assign(base, { action: 'skip', reason: becauseRain ? 'rain' : 'enough', net: 0, gross: 0 });
    }
    let net, action;
    if (worst(drNow, safety) > 0) { net = drNow; action = 'full'; }
    else {
      let lo = 0, hi = drNow;
      for (let i = 0; i < 40; i++) { const mid = (lo + hi) / 2; if (worst(mid, safety) <= 0) hi = mid; else lo = mid; }
      net = hi; action = 'irrigate';
    }
    const needed = net;
    let floor = false;
    if (net < minNet) {
      if (worst(0, 1.0) <= 0) return Object.assign(base, { action: 'skip', reason: 'enough', net: 0, gross: 0 });
      net = minNet; floor = true;
    }
    return Object.assign(base, { action, net, needed, floor, gross: net / f.eff });
  }

  // Replay the season from sowing to the day before `untilDn`, following Saqya's advice at every turn.
  // In the past we know the real weather, so each decision uses the real next days (no forecast error).
  function replaySeason(f, rot, wx, untilDn, policy) {
    policy = policy || 'saqya';
    const days = [], plans = [];
    let dr = 0;
    const firstTurns = new Set(rot.turnStarts(f.sowDn + 1, f.sowDn + f.length - 1));
    const convDays = new Set(CONV_DAYS.map((k) => { let d = f.sowDn + k; while (!rot.isOn(d)) d++; return d; }));
    const end = Math.min(untilDn, f.sowDn + f.length);
    for (let dn = f.sowDn; dn < end; dn++) {
      const w = wx.get(dn); if (!w) break;
      let g = 0;
      if (policy === 'saqya' && firstTurns.has(dn)) {
        const e = [], r = [];
        for (let i = 0; i <= rot.cycle; i++) { const ww = wx.get(dn + i) || w; e.push(ww.et0); r.push(ww.rain); }
        const pl = planTurn(f, rot, dn, dr, e, r);
        plans.push(pl); g = pl.gross;
      } else if (policy === 'conventional' && convDays.has(dn)) g = CONV_GROSS;
      const s = step(f, dn, dr, w.et0, w.rain, g);
      days.push(s); dr = s.dr;
    }
    return { days, plans, dr };
  }

  const api = { CROPS, SOILS, PUMPS, M3_PER_MM_FEDDAN, ET0_FACTORS, CONV_GROSS, CONV_DAYS,
    dnum, iso, monthOf, weekdayOf, makeField, makeRotation, step, project, planTurn, replaySeason };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.Saqya = api;
})(typeof window !== 'undefined' ? window : globalThis);
