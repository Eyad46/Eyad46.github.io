/* Saqya demo: farmer profile -> live or replayed weather -> engine -> SMS thread and chart. */
(function () {
  'use strict';
  const S = window.Saqya;
  const $ = (id) => document.getElementById(id);

  const PLACES = [
    ['Sakha, Kafr El-Sheikh', 31.10, 30.94], ['Mansoura, Dakahlia', 31.04, 31.38], ['Tanta, Gharbia', 30.79, 31.00],
    ['Zagazig, Sharqia', 30.59, 31.50], ['Damanhour, Beheira', 31.03, 30.47], ['Shibin El Kom, Menoufia', 30.55, 31.01],
    ['Benha, Qalyubia', 30.47, 31.18], ['Damietta', 31.42, 31.81], ['Beni Suef', 29.07, 31.10],
    ['Minya', 28.11, 30.75], ['Assiut', 27.18, 31.18], ['Sohag', 26.56, 31.69],
  ];
  const PUMP_LABEL = { '3in': '3 inch, 40 m³/h', '4in': '4 inch, 70 m³/h', '6in': '6 inch, 160 m³/h' };
  const AR_DAYS = ['الأحد', 'الاثنين', 'الثلاثاء', 'الأربعاء', 'الخميس', 'الجمعة', 'السبت'];
  const EN_DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
  const AR_MONTHS = ['يناير', 'فبراير', 'مارس', 'أبريل', 'مايو', 'يونيو', 'يوليو', 'أغسطس', 'سبتمبر', 'أكتوبر', 'نوفمبر', 'ديسمبر'];
  const EN_MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

  let mode = 'replay';
  const todayReal = S.dnum(new Date().toISOString().slice(0, 10));

  // ---------- form setup ----------
  PLACES.forEach(([n], i) => $('loc').add(new Option(n, i)));
  Object.entries(S.CROPS).forEach(([k, c]) => $('crop').add(new Option(c.en, k)));
  Object.entries(S.SOILS).forEach(([k, s]) => $('soil').add(new Option(s.en, k)));
  Object.entries(PUMP_LABEL).forEach(([k, l]) => $('pump').add(new Option(l, k)));
  $('pump').value = '4in';

  function setReplayDefaults() {
    $('crop').value = 'wheat'; $('sow').value = '2025-11-15'; $('anchor').value = '2025-11-15';
    $('today').value = '2026-03-10'; $('today').disabled = false; $('todayLbl').textContent = 'Replay as if today is';
  }
  function setLiveDefaults() {
    const y = new Date().getUTCFullYear(), m = new Date().getUTCMonth();
    const sowY = m >= 10 ? y : y - 1;           // wheat sown on 1 November of this season
    $('crop').value = 'wheat'; $('sow').value = `${sowY}-11-01`; $('anchor').value = `${sowY}-11-01`;
    $('today').value = S.iso(todayReal); $('today').disabled = true; $('todayLbl').textContent = 'Today';
  }
  setReplayDefaults();
  $('mReplay').onclick = () => { mode = 'replay'; $('mReplay').classList.add('on'); $('mLive').classList.remove('on'); setReplayDefaults(); run(); };
  $('mLive').onclick = () => { mode = 'live'; $('mLive').classList.add('on'); $('mReplay').classList.remove('on'); setLiveDefaults(); run(); };
  $('go').onclick = run;

  // ---------- helpers ----------
  const arDigits = (s) => String(s).replace(/[0-9]/g, (d) => '٠١٢٣٤٥٦٧٨٩'[d]);
  const fmtInt = (x) => Math.round(x).toLocaleString('en-US');
  const arInt = (x) => arDigits(Math.round(x));
  function dayName(dn, lang) {
    const d = new Date(dn * 86400000);
    return lang === 'ar'
      ? `${AR_DAYS[d.getUTCDay()]} ${arDigits(d.getUTCDate())} ${AR_MONTHS[d.getUTCMonth()]}`
      : `${EN_DAYS[d.getUTCDay()]} ${d.getUTCDate()} ${EN_MONTHS[d.getUTCMonth()]}`;
  }
  function duration(min, lang) {
    min = Math.max(5, Math.round(min / 5) * 5);
    const h = Math.floor(min / 60), m = min % 60;
    if (lang === 'en') return h ? `${h} h${m ? ' ' + m + ' min' : ''}` : `${m} min`;
    let hs = '';
    if (h === 1) hs = 'ساعة'; else if (h === 2) hs = 'ساعتين'; else if (h >= 3 && h <= 10) hs = `${arDigits(h)} ساعات`; else if (h > 10) hs = `${arDigits(h)} ساعة`;
    const ms = m ? `${arDigits(m)} دقيقة` : '';
    return hs && ms ? `${hs} و${ms}` : (hs || ms);
  }
  function segments(text) {
    const ucs = /[^\x00-\x7F]/.test(text);
    const n = text.length, single = ucs ? 70 : 160, part = ucs ? 67 : 153;
    return n <= single ? 1 : Math.ceil(n / part);
  }

  // ---------- weather ----------
  async function getJSON(url) {
    const r = await fetch(url);
    if (!r.ok) throw new Error('weather service ' + r.status);
    return r.json();
  }
  async function fetchWeather(lat, lon, startDn, endDn, todayDn, live, calibrate) {
    const map = new Map();
    const put = (j, forecastFrom) => {
      const t = j.daily.time, e = j.daily.et0_fao_evapotranspiration, p = j.daily.precipitation_sum;
      t.forEach((d, i) => {
        if (e[i] == null) return;
        const dn = S.dnum(d);
        const f = calibrate ? S.ET0_FACTORS[S.monthOf(dn)] : 1;
        map.set(dn, { et0: e[i] * f, rain: p[i] || 0, forecast: forecastFrom != null && dn >= forecastFrom });
      });
    };
    const q = `latitude=${lat}&longitude=${lon}&daily=et0_fao_evapotranspiration,precipitation_sum&timezone=Africa%2FCairo`;
    if (!live) {
      put(await getJSON(`https://archive-api.open-meteo.com/v1/archive?${q}&start_date=${S.iso(startDn)}&end_date=${S.iso(endDn)}`));
    } else {
      if (todayDn - startDn > 92) {
        put(await getJSON(`https://archive-api.open-meteo.com/v1/archive?${q}&start_date=${S.iso(startDn)}&end_date=${S.iso(todayDn - 93)}`));
      }
      const past = Math.min(92, Math.max(0, todayDn - startDn));
      put(await getJSON(`https://api.open-meteo.com/v1/forecast?${q}&past_days=${past}&forecast_days=16`), todayDn);
    }
    return map;
  }

  // ---------- messages ----------
  function signupThread(st, lang) {
    const c = S.CROPS[st.crop];
    const sow = new Date(st.sowDn * 86400000), anc = new Date(st.anchorDn * 86400000);
    const dm = (d) => `${d.getUTCDate()}/${d.getUTCMonth() + 1}`;
    const inch = st.pump.replace('in', '');
    if (lang === 'ar') {
      return [
        ['out', 'ساقية'],
        ['in', 'أهلاً بيك في ساقية. ابعت المحصول وتاريخ الزراعة والمساحة بالفدان. مثال: قمح ١٥/١١ ١.٥'],
        ['out', arDigits(`${c.ar.replace('ال', '')} ${dm(sow)} ${st.area}`)],
        ['in', 'تمام. الترعة عندكم بتشتغل كام يوم وتقفل كام يوم؟ وآخر دور بدأ إمتى؟ مثال: ٥ ١٠ ١٥/١١'],
        ['out', arDigits(`${st.on} ${st.off} ${dm(anc)}`)],
        ['in', 'والماكينة مقاس كام بوصة؟ ٣ أو ٤ أو ٦'],
        ['out', arDigits(inch)],
        ['in', 'اتسجلت. هبعتلك رسالة قبل كل دور: تروي ولا لأ، وتشغّل الماكينة قد إيه.'],
      ];
    }
    return [
      ['out', 'SAQYA'],
      ['in', 'Welcome to Saqya. Send your crop, sowing date and field size in feddan. Example: wheat 15/11 1.5'],
      ['out', `${c.en.toLowerCase()} ${dm(sow)} ${st.area}`],
      ['in', 'Thanks. How many days does your canal run, how many is it closed, and when did the last turn start? Example: 5 10 15/11'],
      ['out', `${st.on} ${st.off} ${dm(anc)}`],
      ['in', 'What size is your pump in inches? 3, 4 or 6'],
      ['out', inch],
      ['in', "You're registered. Before every canal turn I will text you: irrigate or not, and for how long."],
    ];
  }

  function adviceText(plan, f, st, lang) {
    const c = S.CROPS[st.crop];
    const crop = lang === 'ar' ? c.ar : c.en.toLowerCase();
    const m3 = plan.gross * S.M3_PER_MM_FEDDAN * f.area;
    const mins = 60 * m3 / f.pump;
    const normal = S.CONV_GROSS * S.M3_PER_MM_FEDDAN * f.area;
    const normalMin = 60 * normal / f.pump;
    const head = lang === 'ar' ? `ساقية | دورك يبدأ ${dayName(plan.turnDn, 'ar')}.` : `Saqya | Your canal turn starts ${dayName(plan.turnDn, 'en')}.`;
    const next = dayName(plan.nextDn, lang);
    if (lang === 'ar') {
      if (plan.action === 'harvest') return `${head}\nبطّل ري. ${crop} بيستوي والحصاد قرّب، والري دلوقتي مية ضايعة.`;
      if (plan.action === 'skip' && plan.reason === 'rain') return `${head}\nمتروِيش. متوقع مطر حوالي ${arDigits(Math.round(plan.rainExpected))} مم وهيكفي ${crop} لحد الدور الجاي (${next}).`;
      if (plan.action === 'skip') return `${head}\nمتروِيش المرة دي. الأرض فيها مية تكفي ${crop} لحد الدور الجاي (${next}). كده وفّرت حوالي ${arInt(normal)} م³ و${duration(normalMin, 'ar')} ماكينة مقارنة برية عادية.`;
      if (plan.action === 'full') return `${head}\n${crop} محتاج رية كاملة: الجو حر والدور الجاي بعيد (${next}). شغّل الماكينة ${duration(mins, 'ar')} (حوالي ${arInt(m3)} م³).`;
      return `${head}\n${crop} محتاج رية خفيفة. شغّل الماكينة ${duration(mins, 'ar')} بس للأرض كلها (حوالي ${arInt(m3)} م³). متغرّقش الأرض، الدور الجاي (${next}) هيلحقك.`;
    }
    if (plan.action === 'harvest') return `${head}\nStop irrigating: your ${crop} is ripening and harvest is near. Water now is wasted.`;
    if (plan.action === 'skip' && plan.reason === 'rain') return `${head}\nSkip this turn. About ${Math.round(plan.rainExpected)} mm of rain is expected and will carry your ${crop} to the next turn (${next}).`;
    if (plan.action === 'skip') return `${head}\nNo need to irrigate this turn. The soil holds enough water for your ${crop} until your next turn (${next}). Compared with a normal irrigation you save about ${fmtInt(normal)} m³ and ${duration(normalMin, 'en')} of pump time.`;
    if (plan.action === 'full') return `${head}\nYour ${crop} needs a full irrigation: hot days ahead and your next turn (${next}) is far. Run your pump ${duration(mins, 'en')} (about ${fmtInt(m3)} m³).`;
    return `${head}\nYour ${crop} needs a light irrigation. Run your pump ${duration(mins, 'en')} only, for the whole field (about ${fmtInt(m3)} m³). Don't flood it: your next turn (${next}) will come in time.`;
  }

  function arCount(n) { return n === 1 ? 'رية واحدة' : n === 2 ? 'ريتين' : n <= 10 ? `${arDigits(n)} ريات` : `${arDigits(n)} رية`; }
  function seasonText(hist, conv, f, lang) {
    const extra = hist.days.filter((d) => d.irr > 0).length;
    const used = hist.days.reduce((a, d) => a + d.irr, 0) + S.CONV_GROSS;   // + sowing irrigation
    const usual = conv.days.reduce((a, d) => a + d.irr, 0) + S.CONV_GROSS;
    if (extra === 0 && Math.abs(used - usual) < 1e-6) return null;          // nothing to report yet
    const n = extra + 1;
    const u = used * S.M3_PER_MM_FEDDAN, v = usual * S.M3_PER_MM_FEDDAN, save = v - u;
    const stressConv = conv.days.filter((d) => d.ks < 0.999 && d.das < f.lastIrrigationDas()).length;
    if (lang === 'ar') {
      const base = `ساقية | من أول الموسم: ${arCount(n)}، ${arInt(u)} م³ للفدان. الجدول المعتاد كان هيصرف ${arInt(v)} م³ لحد النهارده.`;
      return save >= 0 ? `${base} وفّرت ${arInt(save)} م³ للفدان.` : `${base} زودنا ${arInt(-save)} م³ عشان الزرع ميعطشش ${arDigits(stressConv)} يوم.`;
    }
    const base = `Saqya | This season so far: ${n} irrigation${n === 1 ? '' : 's'}, ${fmtInt(u)} m³ per feddan. The usual calendar would have used ${fmtInt(v)} m³ by now.`;
    return save >= 0 ? `${base} You saved ${fmtInt(save)} m³ per feddan.` : `${base} Saqya added ${fmtInt(-save)} m³ to spare your crop ${stressConv} days of water stress.`;
  }

  const TRANSLATE = (st, f, plan, hist, conv) => ({ advice: adviceText(plan, f, st, 'en'), season: seasonText(hist, conv, f, 'en') });

  function bubble(side, text, opts) {
    opts = opts || {};
    const el = document.createElement('div');
    el.className = `msg ${side}` + (opts.key ? ' key' : '');
    const rtl = /[؀-ۿ]/.test(text);
    if (rtl) el.dir = 'rtl';
    el.textContent = text;
    if (opts.tr) { const t = document.createElement('span'); t.className = 'tr'; t.textContent = opts.tr; el.appendChild(t); }
    const meta = document.createElement('span');
    meta.className = 'meta';
    meta.textContent = (opts.time || '') + (side === 'in' ? `  ·  ${segments(text)} SMS` : '');
    el.appendChild(meta);
    $('thread').appendChild(el);
  }
  function dayChip(text) { const d = document.createElement('div'); d.className = 'day'; d.textContent = text; $('thread').appendChild(d); }

  // ---------- chart ----------
  function drawChart(f, rot, hist, plan, todayDn, futWith, futWithout) {
    const svg = $('chart'), W = 640, H = 330, m = { l: 44, r: 10, t: 16, b: 30 };
    const x0 = f.sowDn, x1 = f.sowDn + f.length;
    const all = hist.days.concat(futWith);
    const ymax = Math.max(...all.map((d) => d.taw), 40) * 1.12;
    const X = (dn) => m.l + (dn - x0) / (x1 - x0) * (W - m.l - m.r);
    const Y = (v) => H - m.b - v / ymax * (H - m.t - m.b);
    let s = '';
    for (let dn = x0; dn < x1; dn++) if (rot.isOn(dn)) s += `<rect x="${X(dn)}" y="${m.t}" width="${Math.max(1, X(dn + 1) - X(dn))}" height="${H - m.t - m.b}" fill="#dbe9f6"/>`;
    for (let v = 0; v <= ymax; v += ymax > 120 ? 50 : 25) s += `<line x1="${m.l}" x2="${W - m.r}" y1="${Y(v)}" y2="${Y(v)}" stroke="#e6e1d6"/><text x="${m.l - 6}" y="${Y(v) + 4}" text-anchor="end" font-size="13" fill="#6b7680">${v}</text>`;
    s += `<text x="12" y="${m.t + 4}" font-size="13" fill="#6b7680" transform="rotate(-90 12 ${m.t + 4})" text-anchor="end">mm of water in root zone</text>`;
    for (let dn = x0; dn <= x1; dn++) { const d = new Date(dn * 86400000); if (d.getUTCDate() === 1) s += `<text x="${X(dn)}" y="${H - 10}" font-size="13" fill="#6b7680" text-anchor="middle">${EN_MONTHS[d.getUTCMonth()]}</text>`; }
    const path = (pts) => pts.map((p, i) => `${i ? 'L' : 'M'}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join('');
    const line = (days, fn, attrs) => days.length ? `<path d="${path(days.map((d) => [X(d.dn + 1), Y(fn(d))]))}" fill="none" ${attrs}/>` : '';
    const seg = hist.days.concat(futWith);
    s += line(seg, (d) => d.taw, 'stroke="#9aa3aa" stroke-width="1" stroke-dasharray="2 3"');
    s += line(seg, (d) => d.taw - d.raw, 'stroke="#b42318" stroke-width="1.4" stroke-dasharray="6 4"');
    if (plan && (plan.action === 'irrigate' || plan.action === 'full')) s += line(futWithout, (d) => d.taw - d.dr, 'stroke="#9aa3aa" stroke-width="2" stroke-dasharray="5 4"');
    s += line(futWith, (d) => d.taw - d.dr, 'stroke="#2a78d6" stroke-width="2.4" stroke-dasharray="6 4"');
    s += line(hist.days, (d) => d.taw - d.dr, 'stroke="#2a78d6" stroke-width="2.6"');
    hist.days.concat(futWith).filter((d) => d.irr > 0).forEach((d) => {
      const x = X(d.dn + 0.5);
      s += `<path d="M${x - 5},${m.t + 2}L${x + 5},${m.t + 2}L${x},${m.t + 10}Z" fill="${d.dn >= todayDn ? '#c98f1d' : '#2a78d6'}"/>`;
    });
    if (todayDn > x0 && todayDn < x1) s += `<line x1="${X(todayDn)}" x2="${X(todayDn)}" y1="${m.t}" y2="${H - m.b}" stroke="#14212b" stroke-width="1"/><text x="${X(todayDn) + 4}" y="${m.t + 24}" font-size="13" fill="#14212b">today</text>`;
    s += `<rect id="hit" x="${m.l}" y="${m.t}" width="${W - m.l - m.r}" height="${H - m.t - m.b}" fill="transparent"/>`;
    svg.innerHTML = s;
    const byDn = new Map(seg.map((d) => [d.dn, d]));
    const tip = $('tip');
    svg.querySelector('#hit').addEventListener('mousemove', (ev) => {
      const r = svg.getBoundingClientRect();
      const px = (ev.clientX - r.left) / r.width * W;
      const dn = Math.round(x0 + (px - m.l) / (W - m.l - m.r) * (x1 - x0) - 0.5);
      const d = byDn.get(dn);
      if (!d) { tip.style.opacity = 0; return; }
      tip.innerHTML = `<b>${dayName(dn, 'en')}${dn >= todayDn ? ' (forecast)' : ''}</b><br>water in root zone: ${(d.taw - d.dr).toFixed(0)} mm<br>stress line: ${(d.taw - d.raw).toFixed(0)} mm<br>crop water use: ${d.etc.toFixed(1)} mm` + (d.rain > 0.2 ? `<br>rain: ${d.rain.toFixed(1)} mm` : '') + (d.irr > 0 ? `<br>irrigation: ${(d.irr * S.M3_PER_MM_FEDDAN).toFixed(0)} m³/feddan` : '') + (rot.isOn(dn) ? '<br>canal running' : '');
      tip.style.left = Math.min(window.innerWidth - 230, ev.clientX + 14) + 'px';
      tip.style.top = (ev.clientY + 12) + 'px';
      tip.style.opacity = 1;
    });
    svg.querySelector('#hit').addEventListener('mouseleave', () => { tip.style.opacity = 0; });
  }

  // ---------- main ----------
  async function run() {
    const st = {
      place: PLACES[+$('loc').value], crop: $('crop').value, soil: $('soil').value,
      sowDn: S.dnum($('sow').value), anchorDn: S.dnum($('anchor').value), area: +$('area').value || 1,
      pump: $('pump').value, on: Math.max(1, +$('on').value || 5), off: Math.max(1, +$('off').value || 10),
      lang: $('lang').value, cal: $('cal').checked,
      todayDn: mode === 'live' ? todayReal : S.dnum($('today').value),
    };
    const f = S.makeField(st.crop, st.soil, st.sowDn, st.area, S.PUMPS[st.pump]);
    const rot = S.makeRotation(st.on, st.off, st.anchorDn);
    $('go').disabled = true; $('status').textContent = 'Fetching the weather for ' + st.place[0] + '...';
    try {
      if (mode === 'replay' && st.todayDn > todayReal - 40) throw new Error('For a replay pick a date at least 40 days ago (or use Live forecast).');
      if (st.todayDn < st.sowDn) throw new Error('The crop is not sown yet on that date.');
      const endDn = Math.min(st.todayDn + 2 * (st.on + st.off) + 2, f.sowDn + f.length + 1, todayReal - 6);
      const wx = await fetchWeather(st.place[1], st.place[2], st.sowDn, Math.max(endDn, st.todayDn + 1), st.todayDn, mode === 'live', st.cal);
      // fill days beyond the forecast with the average of the last 5 forecast days (no rain)
      const known = [...wx.keys()].sort((a, b) => a - b), lastKnown = known[known.length - 1];
      const tail = known.slice(-5).map((k) => wx.get(k).et0), tailMean = tail.reduce((a, b) => a + b, 0) / tail.length;
      let estimated = 0;
      for (let dn = lastKnown + 1; dn <= f.sowDn + f.length + 20; dn++) { wx.set(dn, { et0: tailMean, rain: 0, forecast: true, est: true }); if (dn <= st.todayDn + st.on + st.off + 16) estimated++; }

      const hist = S.replaySeason(f, rot, wx, st.todayDn, 'saqya');
      const conv = S.replaySeason(f, rot, wx, st.todayDn, 'conventional');
      let turn = rot.turnStart(st.todayDn);
      if (turn < st.todayDn) turn = rot.next(turn);
      // carry the soil water from today to the start of the turn (no irrigation in between)
      let dr = hist.dr; const between = [];
      for (let dn = st.todayDn; dn < turn; dn++) { const w = wx.get(dn); const s = S.step(f, dn, dr, w.et0, w.rain, 0); between.push(s); dr = s.dr; }
      const e = [], r = [];
      for (let i = 0; i <= rot.cycle; i++) { const w = wx.get(turn + i); e.push(w.et0); r.push(w.rain); }
      const seasonOver = f.das(turn) >= f.length;
      const plan = seasonOver ? { action: 'harvest', turnDn: turn, nextDn: rot.next(turn), gross: 0, rainExpected: 0, drNow: dr } : S.planTurn(f, rot, turn, dr, e, r);
      const futWith = between.slice(), futWithout = between.slice();
      let d1 = dr, d2 = dr;
      for (let i = 0; i <= rot.cycle && f.das(turn + i) < f.length; i++) {
        const w = wx.get(turn + i);
        const a = S.step(f, turn + i, d1, w.et0, w.rain, i === 0 ? plan.gross : 0); futWith.push(a); d1 = a.dr;
        const b = S.step(f, turn + i, d2, w.et0, w.rain, 0); futWithout.push(b); d2 = b.dr;
      }

      // SMS thread
      $('thread').innerHTML = '';
      dayChip(dayName(st.sowDn - 2, 'en') + ' · sign-up');
      signupThread(st, st.lang).forEach(([side, text]) => bubble(side, text));
      const tr = TRANSLATE(st, f, plan, hist, conv);
      const sendDn = Math.max(st.todayDn, turn - 1);
      dayChip(dayName(sendDn, 'en') + (sendDn === st.todayDn ? ' · today' : ''));
      const sTxt = seasonText(hist, conv, f, st.lang);
      if (sTxt) bubble('in', sTxt, { tr: st.lang === 'ar' ? tr.season : null, time: '07:58' });
      bubble('in', adviceText(plan, f, st, st.lang), { tr: st.lang === 'ar' ? tr.advice : null, time: '08:00', key: true });
      $('thread').scrollTop = $('thread').scrollHeight;

      // facts
      const das = f.das(turn), kcNow = f.kc(Math.max(0, das));
      const next7 = [...Array(7)].map((_, i) => wx.get(st.todayDn + i).et0);
      const et7 = next7.reduce((a, b) => a + b, 0) / 7;
      const m3 = plan.gross * S.M3_PER_MM_FEDDAN * f.area;
      const actionTxt = { skip: 'Skip this turn', irrigate: 'Light irrigation', full: 'Full irrigation', harvest: 'Stop irrigating' }[plan.action];
      const facts = [
        ['Next canal turn', dayName(turn, 'en'), turn === st.todayDn ? 'starts today' : `in ${turn - st.todayDn} days`],
        ['Advice', actionTxt, plan.gross > 0 ? `${duration(60 * m3 / f.pump, 'en')} of pumping, ${fmtInt(m3)} m³` : (plan.action === 'skip' ? 'no pumping' : '')],
        ['Crop stage', `day ${das} of ${f.length}`, `Kc ${kcNow.toFixed(2)}, roots ${f.zr(das).toFixed(2)} m`],
        ['Weather next 7 days', `${et7.toFixed(1)} mm/day`, `reference ET0${st.cal ? ', station-calibrated' : ''}`],
      ];
      $('facts').innerHTML = facts.map(([k, v, s2]) => `<div class="fact"><div class="k">${k}</div><div class="v">${v}</div><div class="s">${s2}</div></div>`).join('');
      const use = e.slice(0, Math.max(1, plan.n || rot.cycle)).reduce((a, x, i) => a + x * f.kc(das + i), 0);
      const room = Math.max(0, f.raw(das, f.kc(das) * e[0]) - dr);
      let why = '';
      if (plan.action === 'harvest') why = 'The crop has reached the dry-down before harvest, so Saqya stops advising irrigation.';
      else {
        why = `Between this turn and the next one (${rot.cycle} days) the ${S.CROPS[st.crop].en.toLowerCase()} will use about ${use.toFixed(0)} mm of water. ` +
          `The soil can give about ${room.toFixed(0)} mm more before the crop is stressed` + (plan.rainExpected >= 1 ? `, and ${plan.rainExpected.toFixed(0)} mm of rain is expected` : '') + '. ' +
          (plan.action === 'skip' ? 'That is enough, so the farmer can skip the turn and leave the water in the canal for the farms further down.' :
            plan.action === 'full' ? 'Even a full root zone is only just enough, so Saqya asks for a full irrigation.' :
              `Allowing for when the rain falls and a 10% safety margin, the crop needs about ${Math.max(1, plan.needed).toFixed(0)} mm from this turn. ` +
              (plan.floor ? `A basin cannot be irrigated with less than ${plan.net.toFixed(0)} mm, so Saqya asks for that smallest practical irrigation (pump time includes 25% for losses), not a full flood.`
                : 'So Saqya asks for exactly that plus 25% for losses, not a full flood irrigation.'));
      }
      if (estimated > 0 && mode === 'live') why += ` Days beyond the 16-day forecast are estimated from its last days.`;
      $('why').textContent = why;
      drawChart(f, rot, hist, plan, st.todayDn, futWith, futWithout);
      $('status').textContent = `Weather for ${st.place[0]} loaded (${mode === 'live' ? 'live forecast' : 'replay of real weather'}).`;
    } catch (err) {
      $('status').textContent = err.message;
    } finally {
      $('go').disabled = false;
    }
  }
  run();
})();
