"""Download daily reference evapotranspiration (FAO-56 Penman-Monteith) and rainfall for Delta sites.

Source: Open-Meteo historical weather API (ERA5 reanalysis), https://open-meteo.com, licence CC BY 4.0.
Usage: python3 sim/fetch_weather.py data/
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

SITES = {
    "sakha_kafr_el_sheikh": ("Sakha, Kafr El-Sheikh", 31.10, 30.94),
    "mansoura_dakahlia": ("Mansoura, Dakahlia", 31.04, 31.38),
    "tanta_gharbia": ("Tanta, Gharbia", 30.79, 31.00),
    "zagazig_sharqia": ("Zagazig, Sharqia", 30.59, 31.50),
    "damanhour_beheira": ("Damanhour, Beheira", 31.03, 30.47),
    "shibin_menoufia": ("Shibin El Kom, Menoufia", 30.55, 31.01),
}
START, END = "2014-11-01", "2025-06-30"
UA = "saqya-research/1.0 (student water project)"


def fetch(lat: float, lon: float) -> dict:
    url = ("https://archive-api.open-meteo.com/v1/archive?"
           f"latitude={lat}&longitude={lon}&start_date={START}&end_date={END}"
           "&daily=et0_fao_evapotranspiration,precipitation_sum,temperature_2m_max,temperature_2m_min"
           "&timezone=Africa%2FCairo")
    for attempt in range(5):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.load(r)
        except Exception as e:  # noqa: BLE001
            wait = 10 * (attempt + 1)
            print(f"  retry in {wait}s: {e}")
            time.sleep(wait)
    raise RuntimeError("download failed")


def main() -> None:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "data")
    out.mkdir(parents=True, exist_ok=True)
    for key, (name, lat, lon) in SITES.items():
        f = out / f"weather_{key}.json"
        if f.exists():
            print("have", f)
            continue
        print("fetching", name)
        data = fetch(lat, lon)
        data["site_name"] = name
        f.write_text(json.dumps(data))
        time.sleep(2)
    print("done")


if __name__ == "__main__":
    main()
