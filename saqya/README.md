# Saqya (ساقية)

**The right amount of water, on your canal's schedule, in a text message.**

Saqya is an irrigation advisor for smallholder farmers in the old lands of the Nile Delta. Before every canal turn it sends the farmer one SMS: irrigate or not, and for how many minutes to run the pump. It needs no sensors, no smartphone and no internet on the farmer's side.

Live demo: https://eyad46.github.io/saqya/

## Why

* Egypt's renewable water is about 65 billion m³ a year against a demand of about 88.5 billion m³, and the share per person has fallen to about 500 m³ a year (Minister of Water Resources and Irrigation, Ahram Online, 7 April 2026).
* Agriculture takes 79% of Egypt's freshwater withdrawals (FAO AQUASTAT via World Bank, 2022).
* In the Delta, water reaches a field only on its canal's "on" days (for example 5 days on, 10 days off in winter, FAO). Farmers who are unsure when water will come again tend to over-irrigate, especially at the head of the canal, which leaves less for farmers at the tail (IWMI, Heads or Tails, 2015; FAO IIIMP rapid assessment).

## How it works

1. **Weather.** Each day Saqya pulls the free 16-day forecast for the farmer's village from Open-Meteo: reference evapotranspiration (FAO-56 Penman-Monteith) and rain. Reanalysis ET0 runs 10 to 25% above Delta station values, so it is scaled month by month to station data.
2. **Soil water account.** The FAO-56 single crop coefficient method (Allen et al., 1998) tracks the water left in the root zone: rain and irrigation in, crop water use (Kc x ET0) out. Crop stage lengths, crop coefficients, rooting depths and depletion fractions are FAO-56 Tables 11, 12 and 22; soil water holding is FAO-56 Table 19.
3. **Planned around the canal.** At the start of each turn Saqya asks: what is the least water that keeps the crop above its stress line (90% of readily available water) every day until the next turn, without filling the soil beyond field capacity? The answer is converted into pump minutes for the farmer's field and pump. If the soil already holds enough, the farmer is told to skip the turn.

## Results (simulation)

`sim/run_sim.py` replays six real wheat seasons (2019/20 to 2024/25) at six Delta sites with five different rotation timings: 180 seasons. Saqya decides with a noisy 7-day forecast and long-term averages beyond that, and ignores rain more than 3 days ahead. It is compared with a conventional schedule of 5 irrigations of about 435 m³ per feddan each, the control treatment of a field trial at Sakha (El-Hadidi et al., 2016: 2,173 m³ per feddan). Both use the same application efficiency (80%).

| Schedule | Water per feddan per season | Stress days (before dry-down) |
|---|---|---|
| Irrigate at every canal turn | 3,911 m³ | 1.1 |
| Conventional, 5 irrigations | 2,173 m³ | 3.8 |
| **Saqya** | **1,625 m³** (1,065 to 1,956) | **0.1** |

Saqya used less water than the conventional schedule in all 180 seasons, 25% less on average (548 m³ per feddan), with fewer stress days. With uncorrected reanalysis ET0 (crop demand about 20% higher) the saving falls to 6% on average, and the conventional schedule then leaves the crop short of water for about 16 days a season, against 0.6 days with Saqya.

Simulated seasonal crop water use is 395 mm, close to the 406 mm computed for the Sakha trial.

## Limits

* No capillary rise from the shallow water table and no salinity leaching are modelled; a pilot would calibrate soil water holding and the minimum basin depth (40 mm net here) field by field.
* Water a farmer saves partly returns to drains that are reused downstream, so basin-level savings are smaller than farm-level savings. Farm-level savings still mean less pumping, less fertiliser washed out, and more water reaching the tail of the canal.
* The conventional baseline comes from one field trial; real practice varies a lot between farmers.

## Run it

```
python3 sim/fetch_weather.py data/          # 10 years of daily weather for 6 Delta sites (Open-Meteo)
python3 sim/run_sim.py data/ results/       # 180-season replay, writes results/*.json and *.csv
python3 sim/figures.py data/ results/ figures/
python3 tests/test_parity.py                # browser engine gives the same advice as the Python engine
python3 server/sms_bot.py                   # try the SMS conversation in a terminal
```

The demo (`index.html`, `engine.js`, `app.js`) is plain HTML and JavaScript with no build step.

## Sources

* Allen, R.G., Pereira, L.S., Raes, D., Smith, M. (1998). Crop evapotranspiration. FAO Irrigation and Drainage Paper 56.
* El-Hadidi, E.M., Labib, G., Kasem, A.A. (2016). Impact of sowing date of wheat under water stress in North Nile Delta, Egypt. J. Soil Sci. and Agric. Eng., Mansoura Univ., 7(2): 193 to 200.
* FAO. Rapid assessment study: towards integrated planning of irrigation and drainage in Egypt (IIIMP).
* IWMI (2015). Heads or tails (Ghazouani et al., IWMI Research Report 160).
* Ahram Online (7 April 2026). Egypt's per capita water share drops to 500 cubic metres.
* World Bank, indicator ER.H2O.FWAG.ZS (FAO AQUASTAT).
* Station ET0 for Sharkia, 2021: Table 1 in Bulletin of the National Research Centre (2023), doi 10.1186/s42269-023-01068-z.
* Weather data: Open-Meteo.com (CC BY 4.0), ERA5 reanalysis and forecast models.

Eyad Selim, Cairo, 2026. MIT licence.
