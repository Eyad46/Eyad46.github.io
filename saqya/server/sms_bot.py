"""Saqya SMS conversation: sign-up, advice and irrigation log, in Egyptian Arabic or English.

handle(phone, text) returns the reply text. It can sit behind any SMS gateway webhook
(the gateway posts the sender and the message, and sends back the reply). Profiles are kept in
a small JSON file. Run this file to chat with the bot in a terminal.
"""
from __future__ import annotations

import json
import re
import sys
import urllib.request
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine"))
from crops import CROPS, M3_PER_MM_FEDDAN, PUMPS_M3H  # noqa: E402
from saqya_engine import Field, Rotation, SOILS, plan_turn, step  # noqa: E402

DB = ROOT / "server" / "profiles.json"
ET0_FACTORS = [0.766, 0.843, 0.805, 0.881, 0.94, 0.883, 0.896, 0.899, 0.835, 0.846, 0.827, 0.768]
DEFAULT_PLACE = (31.10, 30.94)   # Sakha; a real deployment asks for the village or a location pin
AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
CROP_WORDS = {"قمح": "wheat", "wheat": "wheat", "بنجر": "sugar_beet", "beet": "sugar_beet", "بطاطس": "potato",
              "potato": "potato", "بصل": "onion", "onion": "onion", "ذرة": "maize", "maize": "maize", "corn": "maize",
              "قطن": "cotton", "cotton": "cotton", "طماطم": "tomato", "tomato": "tomato"}
AR_CROP = {"wheat": "القمح", "sugar_beet": "البنجر", "potato": "البطاطس", "onion": "البصل", "maize": "الذرة",
           "cotton": "القطن", "tomato": "الطماطم"}
AR_DAYS = ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]
AR_MONTHS = ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"]

T = {
    "welcome": {"ar": "أهلاً بيك في ساقية. ابعت المحصول وتاريخ الزراعة والمساحة بالفدان. مثال: قمح 15/11 1.5",
                "en": "Welcome to Saqya. Send your crop, sowing date and field size in feddan. Example: wheat 15/11 1.5"},
    "rotation": {"ar": "تمام. الترعة بتشتغل كام يوم وتقفل كام يوم؟ وآخر دور بدأ إمتى؟ مثال: 5 10 15/11",
                 "en": "Thanks. How many days does your canal run, how many is it closed, and when did the last turn start? Example: 5 10 15/11"},
    "pump": {"ar": "والماكينة مقاس كام بوصة؟ 3 أو 4 أو 6", "en": "What size is your pump in inches? 3, 4 or 6"},
    "done": {"ar": "اتسجلت. هبعتلك رسالة قبل كل دور. لو رويت ابعت: رويت. ولو عايز النصيحة دلوقتي ابعت: نصيحة",
             "en": "You're registered. I will text you before every canal turn. If you irrigate, send: irrigated. For advice now send: advice"},
    "again": {"ar": "معلش مافهمتش. جرّب تاني زي المثال.", "en": "Sorry, I did not understand. Please follow the example."},
    "logged": {"ar": "اتسجلت الرية. شكراً.", "en": "Irrigation logged. Thanks."},
}


def load() -> dict:
    return json.loads(DB.read_text()) if DB.exists() else {}


def save(db: dict) -> None:
    DB.write_text(json.dumps(db, ensure_ascii=False, indent=1))


def parse_date(tok: str, today: date) -> date | None:
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?", tok)
    if not m:
        return None
    d, mo = int(m.group(1)), int(m.group(2))
    y = int(m.group(3)) if m.group(3) else today.year
    y = y + 2000 if y < 100 else y
    try:
        out = date(y, mo, d)
    except ValueError:
        return None
    if not m.group(3) and out > today + timedelta(days=31):
        out = date(y - 1, mo, d)
    return out


def ar_num(x) -> str:
    return str(x).translate(str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩"))


def day_name(d: date, lang: str) -> str:
    if lang == "ar":
        return f"{AR_DAYS[d.weekday()]} {ar_num(d.day)} {AR_MONTHS[d.month - 1]}"
    return d.strftime("%a %d %b").replace(" 0", " ")


def duration(minutes: float, lang: str) -> str:
    m = max(5, int(round(minutes / 5.0)) * 5)
    h, mm = divmod(m, 60)
    if lang == "en":
        return (f"{h} h " if h else "") + (f"{mm} min" if mm or not h else "").strip()
    hs = {0: "", 1: "ساعة", 2: "ساعتين"}.get(h, f"{ar_num(h)} ساعات" if h <= 10 else f"{ar_num(h)} ساعة")
    ms = f"{ar_num(mm)} دقيقة" if mm else ""
    return f"{hs} و{ms}" if hs and ms else (hs or ms)


def weather(lat: float, lon: float, start: date, today: date) -> dict[date, tuple[float, float]]:
    past = max(0, min(92, (today - start).days))
    url = ("https://api.open-meteo.com/v1/forecast?"
           f"latitude={lat}&longitude={lon}&daily=et0_fao_evapotranspiration,precipitation_sum"
           f"&past_days={past}&forecast_days=16&timezone=Africa%2FCairo")
    req = urllib.request.Request(url, headers={"User-Agent": "saqya-sms/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        j = json.load(r)["daily"]
    out = {}
    for t, e, p in zip(j["time"], j["et0_fao_evapotranspiration"], j["precipitation_sum"]):
        if e is not None:
            d = date.fromisoformat(t)
            out[d] = (e * ET0_FACTORS[d.month - 1], p or 0.0)
    return out


def advice(p: dict, today: date, wx: dict | None = None) -> str:
    lang = p["lang"]
    sow = date.fromisoformat(p["sow"])
    fld = Field(CROPS[p["crop"]], SOILS["clay"], sow, area_feddan=p["area"], pump_m3h=PUMPS_M3H[p["pump"]])
    rot = Rotation(p["on"], p["off"], date.fromisoformat(p["anchor"]))
    wx = wx or weather(*DEFAULT_PLACE, sow, today)
    days = sorted(wx)
    tail = sum(wx[d][0] for d in days[-5:]) / 5
    get = lambda d: wx.get(d, (tail, 0.0))  # noqa: E731
    # each "irrigated" message counts as one normal irrigation (about 435 m3 per feddan)
    logged = {date.fromisoformat(x) for x in p.get("irrigations", [])}
    dr = 0.0
    for i in range(max(0, (today - sow).days)):  # rebuild the soil water account from the farmer's log
        d = sow + timedelta(days=i)
        e, r = get(d)
        dr = step(fld, d, dr, e, r, 103.4 if d in logged else 0.0).dr_end
    turn = rot.turn_start(today)
    if turn < today:
        turn = rot.next_turn_after(turn)
    for i in range((turn - today).days):
        d = today + timedelta(days=i)
        e, r = get(d)
        dr = step(fld, d, dr, e, r, 0.0).dr_end
    e = [get(turn + timedelta(days=i))[0] for i in range(rot.cycle + 1)]
    r = [get(turn + timedelta(days=i))[1] for i in range(rot.cycle + 1)]
    plan = plan_turn(fld, rot, turn, dr, e, r)
    crop = AR_CROP[p["crop"]] if lang == "ar" else CROPS[p["crop"]].name_en.lower()
    m3 = plan.gross_mm * M3_PER_MM_FEDDAN * fld.area_feddan
    mins = 60 * m3 / fld.pump_m3h
    head = f"ساقية | دورك يبدأ {day_name(turn, 'ar')}." if lang == "ar" else f"Saqya | Your canal turn starts {day_name(turn, 'en')}."
    nxt = day_name(plan.next_turn, lang)
    if plan.reason == "harvest":
        return head + ("\nبطّل ري، الحصاد قرّب." if lang == "ar" else "\nStop irrigating: harvest is near.")
    if plan.action == "skip":
        return head + (f"\nمتروِيش المرة دي. الأرض فيها مية تكفي {crop} لحد الدور الجاي ({nxt})." if lang == "ar"
                       else f"\nNo need to irrigate this turn. The soil holds enough water for your {crop} until your next turn ({nxt}).")
    if lang == "ar":
        return head + f"\n{crop} محتاج رية. شغّل الماكينة {duration(mins, 'ar')} للأرض كلها (حوالي {ar_num(round(m3))} م³). الدور الجاي {nxt}."
    return head + f"\nYour {crop} needs water. Run your pump {duration(mins, 'en')} for the whole field (about {round(m3)} m³). Next turn: {nxt}."


def handle(phone: str, text: str, today: date | None = None, wx: dict | None = None) -> str:
    today = today or date.today()
    db = load()
    raw = text.strip()
    t = raw.translate(AR_DIGITS).lower()
    p = db.get(phone)
    if p is None or t in ("saqya", "ساقية", "start", "اشتراك"):
        lang = "ar" if re.search(r"[؀-ۿ]", raw) else "en"
        db[phone] = {"lang": lang, "step": "crop"}
        save(db)
        return T["welcome"][lang]
    lang = p["lang"]
    toks = t.split()
    if p["step"] == "crop":
        crop = next((CROP_WORDS[w] for w in toks if w in CROP_WORDS), None)
        sow = next((parse_date(w, today) for w in toks if parse_date(w, today)), None)
        area = next((float(w) for w in toks if re.fullmatch(r"\d+(\.\d+)?", w)), None)
        if not (crop and sow and area):
            return T["again"][lang]
        p.update(crop=crop, sow=sow.isoformat(), area=area, step="rotation")
    elif p["step"] == "rotation":
        nums = [int(w) for w in toks if re.fullmatch(r"\d{1,2}", w)]
        anc = next((parse_date(w, today) for w in toks if parse_date(w, today)), None)
        if len(nums) < 2 or not anc:
            return T["again"][lang]
        p.update(on=nums[0], off=nums[1], anchor=anc.isoformat(), step="pump")
    elif p["step"] == "pump":
        size = next((w for w in toks if w in ("3", "4", "6")), None)
        if not size:
            return T["again"][lang]
        p.update(pump=f"{size}in", step="ready", irrigations=[])
    else:
        if t in ("رويت", "irrigated"):
            p.setdefault("irrigations", []).append(today.isoformat())
            db[phone] = p
            save(db)
            return T["logged"][lang]
        if t in ("نصيحة", "advice"):
            return advice(p, today, wx)
        return T["done"][lang]
    db[phone] = p
    save(db)
    return {"rotation": T["rotation"], "pump": T["pump"], "ready": T["done"]}[p["step"]][lang]


if __name__ == "__main__":
    phone = "+20-demo"
    print("Saqya SMS demo. Type a message (start with: ساقية or SAQYA). Ctrl+C to quit.")
    try:
        while True:
            print("Saqya:", handle(phone, input("You: ")))
    except (KeyboardInterrupt, EOFError):
        print()
