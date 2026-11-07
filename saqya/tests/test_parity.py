"""Check that the browser engine (web/engine.js) gives the same advice as the Python engine.

Usage: python3 tests/test_parity.py
"""
from __future__ import annotations

import json
import random
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine"))
from saqya_engine import Rotation, make_field, plan_turn, step  # noqa: E402

rng = random.Random(7)
cases = []
for i in range(400):
    crop = rng.choice(["wheat", "sugar_beet", "potato", "onion", "maize", "cotton", "tomato"])
    soil = rng.choice(["clay", "silty_clay", "loam", "sandy_loam"])
    sow = date(2025, 11, 1) + timedelta(days=rng.randint(0, 60))
    on, off = rng.choice([(5, 10), (4, 4), (7, 7), (4, 8), (5, 5)])
    anchor = sow - timedelta(days=rng.randint(0, on - 1))
    das = rng.randint(1, 200)
    turn = sow + timedelta(days=das)
    n = on + off + 1
    et0 = [round(rng.uniform(1.0, 7.5), 2) for _ in range(n)]
    rain = [round(rng.choice([0, 0, 0, 0, rng.uniform(0, 25)]), 1) for _ in range(n)]
    fld = make_field(crop, soil, sow)
    dr = round(rng.uniform(0, fld.taw(fld.das(turn))), 2)
    rot = Rotation(on, off, anchor)
    p = plan_turn(fld, rot, turn, dr, et0, rain)
    cases.append({"crop": crop, "soil": soil, "sow": sow.isoformat(), "on": on, "off": off,
                  "anchor": anchor.isoformat(), "turn": turn.isoformat(), "dr": dr, "et0": et0, "rain": rain,
                  "py_action": p.action, "py_gross": round(p.gross_mm, 4)})

# a full season step-by-step comparison
fld = make_field("wheat", "clay", date(2025, 11, 15))
w = [(round(rng.uniform(1, 6), 2), round(rng.choice([0, 0, 0, rng.uniform(0, 15)]), 1)) for _ in range(160)]
dr, traj = 0.0, []
for i, (e, r) in enumerate(w):
    g = 80.0 if i in (30, 60, 90) else 0.0
    s = step(fld, fld.sowing + timedelta(days=i), dr, e, r, g)
    dr = s.dr_end
    traj.append(round(dr, 6))

payload = {"cases": cases, "season": {"weather": w, "traj": traj}}
js = r"""
const S = require(process.argv[process.argv.length - 1]);
const data = JSON.parse(require('fs').readFileSync(0, 'utf8'));
let bad = 0, maxdiff = 0;
for (const c of data.cases) {
  const f = S.makeField(c.crop, c.soil, S.dnum(c.sow));
  const rot = S.makeRotation(c.on, c.off, S.dnum(c.anchor));
  const p = S.planTurn(f, rot, S.dnum(c.turn), c.dr, c.et0, c.rain);
  const action = p.action === 'harvest' ? 'skip' : p.action;
  const d = Math.abs(p.gross - c.py_gross);
  maxdiff = Math.max(maxdiff, d);
  if (action !== c.py_action || d > 1e-3) { bad++; if (bad < 5) console.log('MISMATCH', JSON.stringify({c, js: p})); }
}
const f = S.makeField('wheat', 'clay', S.dnum('2025-11-15'));
let dr = 0, sd = 0;
data.season.weather.forEach(([e, r], i) => {
  const g = [30, 60, 90].includes(i) ? 80 : 0;
  const s = S.step(f, f.sowDn + i, dr, e, r, g); dr = s.dr;
  sd = Math.max(sd, Math.abs(dr - data.season.traj[i]));
});
console.log(JSON.stringify({cases: data.cases.length, mismatches: bad, max_gross_diff: maxdiff, season_max_diff: sd}));
"""
out = subprocess.run(["node", "-e", js, str(ROOT / "engine.js")], input=json.dumps(payload),
                     capture_output=True, text=True)
print(out.stdout.strip() or out.stderr)
res = json.loads(out.stdout.strip().splitlines()[-1])
assert res["mismatches"] == 0 and res["season_max_diff"] < 1e-6, res
print("parity OK")
