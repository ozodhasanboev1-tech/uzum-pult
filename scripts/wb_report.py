#!/usr/bin/env python3
# Wildberries hisobot moduli (Uzum hisobotlariga qo'shimcha). Faqat o'qish so'rovlari.
# Ishlatish:
#   python3 wb_report.py daily   [--no-tg] [--date YYYY-MM-DD]  kechagi (yoki ko'rsatilgan kun) sotuv/vozvrat + ~taxminiy foyda
#   python3 wb_report.py weekly  [--no-tg] [--from YYYY-MM-DD --to YYYY-MM-DD]   aniq realizatsiya (o'tgan hafta)
#   python3 wb_report.py monthly [--no-tg]                 o'tgan oy + arxiv (~/wb_archive.json -> ~/out_wb/wb_archive.json)
#   python3 wb_report.py hourly  [--no-tg]                 bugungi buyurtmalar
#   python3 wb_report.py album                            ~/out_wb/wb_album.json bo'lsa — tovar rasmlarini Telegram'ga (URL orqali)
# Kalitlar env: WB_CLEO, WB_NASIROV, TG_TOKEN, TG_CHAT. Tannarx: ~/wb_tannarx.csv ("WB tannarx" jadvali).
# Chiqish: ~/out_wb/wb_<rejim>.json, wb_<rejim>.txt, wb_<rejim>_<kabinet>.png (+ oylikda grafiklar).
import os, sys, io, re, csv, json, time, math, statistics, collections, datetime as dt, concurrent.futures as cf
import requests

H = os.path.expanduser("~")
OUTD = os.path.join(H, "out_wb")
TZ = dt.timezone(dt.timedelta(hours=5))
MSK = dt.timezone(dt.timedelta(hours=3))
CABS = [("CLEO", "WB_CLEO"), ("NASIROV", "WB_NASIROV")]
FIN = "https://finance-api.wildberries.ru/api/finance/v1/sales-reports/detailed"
STAT = "https://statistics-api.wildberries.ru/api/v1/supplier/"
CONTENT = "https://content-api.wildberries.ru/content/v2/get/cards/list"
UZ_MONTHS = ["", "yanvar", "fevral", "mart", "aprel", "may", "iyun", "iyul", "avgust", "sentyabr", "oktyabr", "noyabr", "dekabr"]
BACKFILL_FROM = dt.date(2026, 1, 1)   # oylik arxivni shu sanadan to'ldiradi (API bergan joydan)
FIELDS = ["sotuv", "komissiya", "logistika", "saqlash", "obrabotka", "jarima", "ushlab", "yakuniy", "tannarx", "foyda"]

TOK = {n: os.environ[v].strip() for n, v in CABS if os.environ.get(v, "").strip()}
TG = (os.environ.get("TG_TOKEN", "").strip(), os.environ.get("TG_CHAT", "").strip())

def hide(s):
    s = str(s)
    for t in list(TOK.values()) + [TG[0]]:
        if t:
            s = s.replace(t, "***")
    return s

num = lambda v: float(v) if v not in (None, "") else 0.0
F = lambda n: f"{int(round(n or 0)):,}".replace(",", " ")
def S(n):
    n = float(n or 0); a = abs(n)
    if a >= 1e9: return f"{n/1e9:.1f} mlrd".replace(".", ",")
    if a >= 1e6: return f"{n/1e6:.1f} mln".replace(".", ",")
    if a >= 1e3: return f"{n/1e3:.0f} ming"
    return f"{n:.0f}"
def arrow(a, b):
    if not b: return ""
    p = (a - b) / abs(b) * 100
    return "≈0%" if abs(p) < 0.5 else f"{'▲' if p >= 0 else '▼'}{abs(p):.0f}%"
cut = lambda x, n: x if len(x) <= n else x[: n - 1] + "…"

# ---------------------------------------------------------------- API
def fin_rows(tok, d0, d1, period="weekly", log=None):
    """Aniq realizatsiya qatorlari (UZS, summalar matn). 204 gacha rrdId bilan bo'laklab, 1 so'rov/daqiqa."""
    rows, rrd, tries = [], 0, 0
    while True:
        try:
            r = requests.post(FIN, headers={"Authorization": tok}, timeout=300,
                              json={"dateFrom": f"{d0}", "dateTo": f"{d1}", "limit": 100000, "rrdId": rrd, "period": period})
        except Exception as x:
            tries += 1
            if tries > 3: raise Exception(f"finance: {hide(x)[:120]}")
            time.sleep(20); continue
        if r.status_code == 429:
            tries += 1
            if tries > 6: raise Exception("finance: 429 (limit)")
            time.sleep(65); continue
        if r.status_code == 204: return rows
        if r.status_code != 200: raise Exception(f"finance HTTP {r.status_code} {hide(r.text)[:120]}")
        b = r.json(); d = b if isinstance(b, list) else (b.get("data") or [])
        if not d: return rows
        rows += d; rrd = d[-1].get("rrdId") or 0
        if len(d) < 100000: return rows   # oxirgi bo'lak — qo'shimcha so'rov shart emas
        time.sleep(62)

def stat(tok, method, date_from, flag=0):
    for a in range(4):
        try:
            r = requests.get(STAT + method, headers={"Authorization": tok}, params={"dateFrom": date_from, "flag": flag}, timeout=180)
            if r.status_code == 429: time.sleep(65); continue
            if r.ok: return r.json() or []
            raise Exception(f"{method} HTTP {r.status_code} {hide(r.text)[:100]}")
        except requests.RequestException as x:
            e = x; time.sleep(10)
    raise Exception(f"{method}: {hide(e)[:100]}")

def cards(tok):
    """nmID -> artikul, nomi, rasm (content-api)."""
    out, cur = {}, {"limit": 100}
    for _ in range(30):
        r = requests.post(CONTENT, headers={"Authorization": tok}, json={"settings": {"cursor": cur, "filter": {"withPhoto": -1}}}, timeout=90)
        if r.status_code == 429: time.sleep(10); continue
        if not r.ok: break
        j = r.json(); cs = j.get("cards") or []
        for c in cs:
            ph = (c.get("photos") or [{}])[0]
            dm = c.get("dimensions") or {}
            try: vol = round(float(dm.get("length") or 0) * float(dm.get("width") or 0) * float(dm.get("height") or 0) / 1000, 3)
            except Exception: vol = 0
            out[c.get("nmID")] = dict(vc=c.get("vendorCode"), title=c.get("title"), photo=ph.get("c246x328") or ph.get("tm") or ph.get("big"),
                                      sub=c.get("subjectID"), subn=c.get("subjectName"), vol=vol)
        if len(cs) < 100: break
        cu = j.get("cursor") or {}; cur = {"limit": 100, "updatedAt": cu.get("updatedAt"), "nmID": cu.get("nmID")}
    return out

def par(fn, names):
    """Har kabinet alohida token — parallel ishlaydi (limit token bo'yicha)."""
    res = {}
    with cf.ThreadPoolExecutor(max(1, len(names))) as ex:
        fut = {ex.submit(fn, n): n for n in names}
        for f in cf.as_completed(fut):
            n = fut[f]
            try: res[n] = (f.result(), None)
            except Exception as x: res[n] = (None, hide(x)[:160])
    return res

# ---------------------------------------------------------------- narx tekshiruvi uchun (faqat o'qish)
MP = "https://marketplace-api.wildberries.ru/api/v3/orders"
COMM = "https://common-api.wildberries.ru/api/v1/tariffs/commission"
def _get(url, tok, params=None, tries=5):
    e = "?"
    for w in (0, 5, 15, 30, 60)[:tries]:
        time.sleep(w)
        try:
            r = requests.get(url, headers={"Authorization": tok}, params=params, timeout=(15, 90))
            if r.ok: return r.json()
            e = f"HTTP {r.status_code}"
            if r.status_code in (400, 401, 403, 404): break
        except Exception as x: e = type(x).__name__
    raise Exception(f"{url.rsplit('/', 1)[-1]}: {e}")

def mp_orders(tok, days=7):
    """FBS (o'z sklad) buyurtmalari: marketplace-api /api/v3/orders — oxirgi N kun."""
    out, nxt = [], 0
    d0 = int(time.time()) - days * 86400
    for _ in range(20):
        j = _get(MP, tok, {"limit": 1000, "next": nxt, "dateFrom": d0}) or {}
        o = j.get("orders") or []; out += o
        nxt = j.get("next") or 0
        if len(o) < 1000 or not nxt: break
    return out

PRICES = "https://discounts-prices-api.wildberries.ru/api/v2/list/goods/filter"
def prices(tok):
    """nmID -> [narx, chegirma %, chegirmali narx, valyuta] (sotuvchi narxi, avtoaksiyasiz)."""
    out, off = {}, 0
    for _ in range(30):
        j = _get(PRICES, tok, {"limit": 1000, "offset": off}) or {}
        L = ((j.get("data") or {}).get("listGoods")) or []
        for g in L:
            sz = (g.get("sizes") or [{}])[0]
            out[g.get("nmID")] = [sz.get("price"), g.get("discount"), sz.get("discountedPrice"), g.get("currencyIsoCode4217")]
        if len(L) < 1000: break
        off += 1000
    return out

def commission(tok):
    """subjectID -> (FBS %, FBO %) WB tariflari."""
    j = _get(COMM, tok, {"locale": "ru"}, tries=3) or {}
    res = {}
    for x in j.get("report") or []:
        res[x.get("subjectID")] = (x.get("kgvpMarketplace"), x.get("paidStorageKgvp"))
    return res

# ---------------------------------------------------------------- tannarx
def load_cost():
    """~/wb_tannarx.csv: "Tasdiqlangan tannarx", bo'sh bo'lsa "Taklif tannarx (so'm)". Kalit: nmID va artikul."""
    by_nm, by_vc = {}, {}
    p = os.path.join(H, "wb_tannarx.csv")
    if not os.path.exists(p): return by_nm, by_vc
    def n_(c):
        c = re.sub(r"[\s\xa0']", "", c or "").replace("so'm", "")
        if re.fullmatch(r"\d{1,3}(,\d{3})+(\.\d+)?", c): c = c.replace(",", "")
        try: v = float(c.replace(",", ".")); return v if v > 0 else None
        except ValueError: return None
    for r in csv.DictReader(open(p, encoding="utf-8-sig")):
        k = {x.lower().strip(): x for x in r}
        g = lambda name: r.get(next((v for kk, v in k.items() if name in kk), ""), "")
        v = n_(g("tasdiqlangan")) or n_(g("taklif"))
        if not v: continue
        nm = re.sub(r"\D", "", g("nmid"))
        if nm: by_nm[int(nm)] = v
        if g("artikul").strip(): by_vc[g("artikul").strip().lower()] = v
    return by_nm, by_vc

# ---------------------------------------------------------------- hisob-kitob
def sign(x):
    return -1 if (x.get("docTypeName") or "").lower().startswith("возврат") else 1

def aggregate(rows, cost, card):
    """Qatorlarni tovar (nmId) bo'yicha yig'adi. Yakuniy = forPay − logistika − saqlash − obrabotka − jarima − ushlab."""
    by_nm, by_vc = cost
    items = collections.OrderedDict()
    pen, ded, rets = [], [], collections.Counter()
    for x in rows:
        nm = x.get("nmId") or 0
        s = sign(x)
        it = items.setdefault(nm, dict(nm=nm, vc=x.get("vendorCode") or "", title=x.get("title") or "", soni=0, vozvrat=0,
                                        sotuv=0.0, forpay=0.0, logistika=0.0, saqlash=0.0, obrabotka=0.0, jarima=0.0, ushlab=0.0, qoshimcha=0.0))
        if not it["vc"] and x.get("vendorCode"): it["vc"] = x["vendorCode"]
        if not it["title"] and x.get("title"): it["title"] = x["title"]
        op = (x.get("sellerOperName") or "").lower()
        q = int(x.get("quantity") or 0)
        if op in ("продажа", "возврат"):
            if s > 0: it["soni"] += q
            else: it["vozvrat"] += q; rets["Xaridor qaytardi (Возврат)"] += q
        it["sotuv"] += s * num(x.get("retailAmount"))
        it["forpay"] += s * num(x.get("forPay"))
        it["logistika"] += num(x.get("deliveryService"))
        it["saqlash"] += num(x.get("paidStorage"))
        it["obrabotka"] += num(x.get("paidAcceptance"))
        it["jarima"] += num(x.get("penalty"))
        it["ushlab"] += num(x.get("deduction"))
        it["qoshimcha"] += num(x.get("additionalPayment"))
        bt = x.get("bonusTypeName") or ""
        if num(x.get("penalty")):
            pen.append(dict(nm=nm, vc=it["vc"], sabab=bt or x.get("sellerOperName") or "", summa=num(x.get("penalty")), sana=x.get("rrDate")))
        if num(x.get("deduction")):
            ded.append(dict(nm=nm, vc=it["vc"], sabab=bt or x.get("sellerOperName") or "", summa=num(x.get("deduction")), sana=x.get("rrDate")))
        if op == "логистика" and ("от клиента" in bt.lower() or "возврат" in bt.lower()):
            rets[f"Logistika: {bt}"] += int(x.get("deliveryAmount") or 0) + int(x.get("returnAmount") or 0) or 1
    for p in pen + ded:
        c = card.get(p["nm"]) or {}
        if c.get("vc"): p["vc"] = c["vc"]
    out = []
    for it in items.values():
        c = card.get(it["nm"]) or {}
        it["vc"] = it["vc"] if it["nm"] else "—"
        it["title"] = it["title"] or c.get("title") or ("Tovarga bog'lanmagan (saqlash, ushlab qolish)" if not it["nm"] else "")
        it["photo"] = c.get("photo")
        if c.get("vc") and it["nm"]: it["vc"] = c["vc"]
        it["komissiya"] = it["sotuv"] - it["forpay"]
        it["yakuniy"] = it["forpay"] - it["logistika"] - it["saqlash"] - it["obrabotka"] - it["jarima"] - it["ushlab"]
        unit = by_nm.get(it["nm"]) or by_vc.get((it["vc"] or "").lower())
        net_q = it["soni"] - it["vozvrat"]
        it["tannarx"] = (unit or 0) * net_q
        it["no_cost"] = bool(net_q and not unit)
        it["foyda"] = it["yakuniy"] - it["tannarx"]
        out.append(it)
    out.sort(key=lambda i: (i["nm"] == 0, -i["sotuv"], i["foyda"]))
    tot = {k: sum(i[k] for i in out) for k in FIELDS + ["soni", "vozvrat", "forpay", "qoshimcha"]}
    return dict(items=out, tot=tot, pen=pen, ded=ded, rets=dict(rets))

def std_rows(label, cab, items, approx=False):
    """Umumiy JSON formati."""
    return [dict(sana=label, kabinet=cab, artikul=i["vc"], nomi=i["title"], nm=i["nm"], soni=i["soni"] - i.get("vozvrat", 0),
                 vozvrat=i.get("vozvrat", 0), sotuv=round(i["sotuv"], 2), komissiya=round(i["komissiya"], 2), logistika=round(i["logistika"], 2),
                 saqlash=round(i["saqlash"], 2), obrabotka=round(i["obrabotka"], 2), jarima=round(i["jarima"], 2), ushlab=round(i["ushlab"], 2),
                 yakuniy=round(i["yakuniy"], 2), tannarx=round(i["tannarx"], 2), foyda=round(i["foyda"], 2), rasm=i.get("photo"),
                 taxminiy=approx) for i in items]

def last_week(today=None):
    t = today or dt.datetime.now(TZ).date()
    e = t - dt.timedelta(days=t.weekday())     # shu haftaning dushanbasi
    return e - dt.timedelta(days=7), e - dt.timedelta(days=1)

def rate_from(rows, sales):
    """UZS/RUB: bir xil srid bo'yicha realizatsiyadagi retailPriceWithDisc (UZS) / statistikadagi priceWithDisc (RUB)."""
    rub = {s.get("srid"): s.get("priceWithDisc") for s in sales if s.get("priceWithDisc")}
    r = [num(x.get("retailPriceWithDisc")) / rub[x["srid"]] for x in rows
         if x.get("srid") in rub and (x.get("sellerOperName") or "") == "Продажа" and num(x.get("retailPriceWithDisc")) > 0]
    return (statistics.median(r), len(r)) if r else (None, 0)

# ---------------------------------------------------------------- rasm (PNG)
_IMGC, IMGSTAT = {}, collections.Counter()
def jpg_url(url):
    """Telegram o'zi yuklab olishi uchun: .../images/<o'lcham>/N.webp -> .../images/big/N.jpg"""
    return re.sub(r"/images/[^/]+/(\d+)\.\w+$", r"/images/big/\1.jpg", url) if url else None

def get_img(url):
    """To'liq rasm (kesh). WB rasmlari *.wbbasket.ru da — muhit tarmog'ida ruxsat bo'lmasa None."""
    from PIL import Image
    if not url: return None
    if url in _IMGC: return _IMGC[url]
    im = None
    for u in dict.fromkeys([url, jpg_url(url)]):
        try:
            r = requests.get(u, timeout=8)
            if r.ok:
                im = Image.open(io.BytesIO(r.content)).convert("RGB"); break
        except Exception:
            pass
    IMGSTAT["ok" if im is not None else "fail"] += 1
    _IMGC[url] = im
    return im

def thumb(url, w=56, h=74):
    im = get_img(url)
    if im is None: return None
    im = im.copy(); im.thumbnail((w, h)); return im

def _fonts():
    from PIL import ImageFont
    fp, fb = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    return lambda s, b=False: ImageFont.truetype(fb if b else fp, s)

def delta_s(a, b, money=False):
    """Oldingi davr bilan farq: ▲12% / ▼30% / yangi."""
    if b in (None, 0):
        return ("yangi", "#7000FF") if a else ("", "#6E6A85")
    p = (a - b) / abs(b) * 100
    if abs(p) < 0.5: return ("≈0%", "#6E6A85")
    return (f"{'▲' if p > 0 else '▼'}{abs(p):.0f}%", "#14A660" if p > 0 else "#E5484D")

def cards_png(path, title, sub, items, approx=False, prev=None, n=15, loss_list=True):
    """Uzum uslubidagi kartochkalar: TOP-n tovar rasm bilan — nechta sotildi, summa, foyda (+ oldingi davrga nisbatan).
    prev: {nm: dict(soni, sotuv, foyda)} — o'tgan oy/hafta (bo'lsa)."""
    from PIL import Image, ImageDraw
    FT = _fonts()
    pre = "~" if approx else ""
    top = sorted([i for i in items if i["nm"] and i["soni"] - i.get("vozvrat", 0) > 0], key=lambda i: (-(i["soni"] - i.get("vozvrat", 0)), -i["sotuv"]))[:n]
    loss = sorted([i for i in items if i["nm"] and i["foyda"] < 0], key=lambda i: i["foyda"])[:6] if loss_list and not approx else []
    W, cols, tw, th, gap = 1200, 5, 216, 318, 10
    rows_n = max(1, math.ceil(len(top) / cols))
    Hh = 150 + rows_n * (th + gap) + 20 + (70 + 34 * len(loss) if loss else 0) + 20
    im = Image.new("RGB", (W, Hh), "#F6F5FB"); d = ImageDraw.Draw(im)
    d.text((40, 24), title, font=FT(28, True), fill="#1D1B2C")
    d.text((40, 66), sub, font=FT(15), fill="#6E6A85")
    d.text((40, 108), f"TOP-{len(top)} tovar — nimadan nechta sotildi" if top else "Bu davrda sotuv bo'lmadi", font=FT(18, True), fill="#1D1B2C")
    mxq = max([i["soni"] - i.get("vozvrat", 0) for i in top] + [1])
    for k, it in enumerate(top):
        x = 40 + (k % cols) * (tw + gap); y = 145 + (k // cols) * (th + gap)
        d.rounded_rectangle((x, y, x + tw, y + th), 12, fill="#FFFFFF", outline="#E6E3F0")
        ph = get_img(it.get("photo"))
        if ph is not None:
            ph = ph.copy(); ph.thumbnail((tw - 24, 156)); im.paste(ph, (x + (tw - ph.width) // 2, y + 10))
        else:
            d.rounded_rectangle((x + 40, y + 12, x + tw - 40, y + 160), 8, fill="#F3EFFC")
            d.text((x + tw // 2, y + 76), "WB", font=FT(26, True), fill="#CB11AB", anchor="mm")
            d.text((x + tw // 2, y + 108), "rasm yo'q", font=FT(11), fill="#9A96AD", anchor="mm")
        d.rounded_rectangle((x + 8, y + 8, x + 34, y + 30), 6, fill="#CB11AB")
        d.text((x + 21, y + 19), str(k + 1), font=FT(13, True), fill="white", anchor="mm")
        q = it["soni"] - it.get("vozvrat", 0)
        d.text((x + 10, y + 172), cut(it["vc"] or "—", 24), font=FT(13, True), fill="#1D1B2C")
        d.text((x + 10, y + 192), cut(it["title"] or "", 30), font=FT(10), fill="#6E6A85")
        d.text((x + 10, y + 212), f"{F(q)} dona", font=FT(20, True), fill="#1D1B2C")
        if it.get("vozvrat"): d.text((x + tw - 10, y + 220), f"vozvrat {it['vozvrat']}", font=FT(10), fill="#E5484D", anchor="ra")
        d.text((x + 10, y + 244), f"sotuv {S(it['sotuv'])}", font=FT(12), fill="#6E6A85")
        fc = "#14A660" if it["foyda"] >= 0 else "#E5484D"
        d.text((x + 10, y + 264), f"{pre}foyda {S(it['foyda'])}" if it["tannarx"] else "tannarx yo'q", font=FT(12, True), fill=fc if it["tannarx"] else "#F5A524")
        P = (prev or {}).get(it["nm"])
        if prev is not None:
            ds, dc = delta_s(q, (P or {}).get("soni") - (P or {}).get("vozvrat", 0) if P else None)
            if ds: d.text((x + tw - 10, y + 264), ds, font=FT(12, True), fill=dc, anchor="ra")
        d.rectangle((x + 10, y + th - 18, x + tw - 10, y + th - 12), fill="#E6E3F0")
        d.rectangle((x + 10, y + th - 18, x + 10 + int((tw - 20) * q / mxq), y + th - 12), fill="#CB11AB")
    yy = 145 + rows_n * (th + gap) + 10
    if loss:
        d.rounded_rectangle((40, yy, W - 40, yy + 56 + 34 * len(loss)), 12, fill="#FFFFFF", outline="#E6E3F0")
        d.text((60, yy + 14), "Zararda — sotuv kam yoki rasxod (logistika/obrabotka/jarima) katta", font=FT(16, True), fill="#E5484D")
        for j, it in enumerate(loss):
            y_ = yy + 50 + j * 34; q = it["soni"] - it.get("vozvrat", 0)
            d.text((60, y_), cut(it["vc"], 34), font=FT(13, True), fill="#1D1B2C")
            d.text((390, y_ + 1), cut(it["title"] or "", 46), font=FT(11), fill="#6E6A85")
            d.text((900, y_), f"{F(q)} dona" if q else "sotuvsiz", font=FT(13), fill="#6E6A85", anchor="ra")
            d.text((W - 60, y_), F(it["foyda"]) + " so'm", font=FT(13, True), fill="#E5484D", anchor="ra")
        yy += 66 + 34 * len(loss)
    im.crop((0, 0, W, yy + 10)).save(path)
    return path

def album_of(items, approx=False, n=10):
    """Rasm yuklab bo'lmasa (tarmoq yopiq) — Telegram rasmni o'zi URL'dan oladi: [(jpg_url, caption)]."""
    pre = "~" if approx else ""
    top = sorted([i for i in items if i["nm"] and i.get("photo") and i["soni"] - i.get("vozvrat", 0) > 0],
                 key=lambda i: (-(i["soni"] - i.get("vozvrat", 0)), -i["sotuv"]))[:n]
    return [(jpg_url(i["photo"]), f"{i['vc']} — {i['soni'] - i.get('vozvrat', 0)} dona · {F(i['sotuv'])} so'm"
             + (f" · {pre}foyda {F(i['foyda'])}" if i["tannarx"] else "")) for i in top]

def table_png(path, title, sub, items, approx=False, maxrows=40):
    from PIL import Image, ImageDraw, ImageFont
    fp, fb = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    f, fB, fs, fT = ImageFont.truetype(fp, 14), ImageFont.truetype(fb, 14), ImageFont.truetype(fp, 11), ImageFont.truetype(fb, 20)
    rows = items[:maxrows]
    cols = [("", 64, "l"), ("Artikul — nomi", 380, "l"), ("Soni", 60, "r"), ("Sotuv", 110, "r"), ("Rasxod", 110, "r"),
            ("Yakuniy", 115, "r"), ("Tannarx", 110, "r"), ("Foyda", 115, "r")]
    W = sum(c[1] for c in cols) + 40; rh = 80
    Hh = 96 + 30 + rh * (len(rows) + 1) + 40
    im = Image.new("RGB", (W, Hh), "#f7f7fa"); d = ImageDraw.Draw(im)
    d.text((20, 18), title, font=fT, fill="#17161c"); d.text((20, 48), sub, font=fs, fill="#6b6975")
    y = 82; x = 20
    d.rectangle((20, y, W - 20, y + 28), fill="#ece9fb")
    for n, w, a in cols:
        tw = d.textlength(n, font=fB); d.text((x + w - tw - 8 if a == "r" else x + 8, y + 6), n, font=fB, fill="#3b2a99"); x += w
    y += 30
    def line(vals, img=None, bold=False, red=False, shade=False):
        nonlocal y
        d.rectangle((20, y, W - 20, y + rh), fill="#fff1f0" if red else ("#ffffff" if not shade else "#fbfbfd"))
        x = 20
        for (n, w, a), v in zip(cols, vals):
            fo = fB if bold else f
            if n == "" and img is not None:
                im.paste(img, (x + 4, y + (rh - img.size[1]) // 2))
            elif n == "" and not bold:
                d.rectangle((x + 6, y + 8, x + 58, y + rh - 8), outline="#d9d6e6"); d.text((x + 18, y + rh // 2 - 7), "WB", font=fs, fill="#9a96ad")
            elif isinstance(v, tuple):
                d.text((x + 8, y + 14), v[0], font=fB, fill="#17161c"); d.text((x + 8, y + 36), v[1], font=fs, fill="#77757f")
                if len(v) > 2 and v[2]: d.text((x + 8, y + 54), v[2], font=fs, fill="#c2372f")
            elif v != "":
                col = "#c2372f" if str(v).startswith("-") else "#17161c"
                tw = d.textlength(str(v), font=fo); d.text((x + w - tw - 8 if a == "r" else x + 8, y + rh // 2 - 8), str(v), font=fo, fill=col)
            x += w
        y += rh; d.line((20, y, W - 20, y), fill="#e4e3ea")
    pre = "~" if approx else ""
    for i, it in enumerate(rows):
        rasxod = it["sotuv"] - it["yakuniy"]
        note = "tannarx yo'q" if it.get("no_cost") else ""
        line(["", (cut(f"{it['vc']}", 44), cut(it["title"] or "", 60), note), F(it["soni"] - it.get("vozvrat", 0)), F(it["sotuv"]), F(rasxod),
              pre + F(it["yakuniy"]), F(it["tannarx"]) if it["tannarx"] else "—", (pre if it["foyda"] >= 0 else "") + F(it["foyda"])],
             img=thumb(it.get("photo")), red=it["foyda"] < 0 and it["nm"] != 0, shade=i % 2)
    if len(items) > maxrows:
        d.text((24, y + 6), f"… yana {len(items) - maxrows} qator JSON/Excel'da", font=fs, fill="#77757f"); y += 24
    T = {k: sum(i[k] for i in items) for k in FIELDS + ["soni", "vozvrat"]}
    line(["", ("JAMI", ""), F(T["soni"] - T["vozvrat"]), F(T["sotuv"]), F(T["sotuv"] - T["yakuniy"]), pre + F(T["yakuniy"]),
          F(T["tannarx"]), F(T["foyda"])], bold=True, red=T["foyda"] < 0)
    im = im.crop((0, 0, W, y + 16)); im.save(path)

# ---------------------------------------------------------------- matn
def cab_block(cab, A, mode, approx=False, extra=None):
    T = A["tot"]; p = "~" if approx else ""
    L = [f"🟪 WB · {cab}"]
    L.append(f"  Sotuv: {F(T['sotuv'])} so'm · {F(T['soni'] - T['vozvrat'])} dona" + (f" (vozvrat {T['vozvrat']})" if T["vozvrat"] else ""))
    if mode != "daily":
        L.append(f"  Komissiya {S(T['komissiya'])} · logistika {S(T['logistika'])} · saqlash {S(T['saqlash'])} · obrabotka {S(T['obrabotka'])}"
                 + (f" · jarima {S(T['jarima'])}" if T["jarima"] else "") + (f" · ushlab qolish {S(T['ushlab'])}" if T["ushlab"] else ""))
    yk = f"{T['yakuniy']:,.2f}".replace(",", " ").replace(".", ",") if mode == "weekly" else F(T["yakuniy"])
    L.append(f"  {p}Yakuniy to'lov: {yk} so'm · tannarx {F(T['tannarx'])} · {p}FOYDA: {F(T['foyda'])} so'm")
    if extra: L += ["  " + e for e in extra]
    return L

# ---------------------------------------------------------------- rejimlar
def run_weekly(d0=None, d1=None):
    if not d0: d0, d1 = last_week()
    cost = load_cost()
    def one(cab):
        tok = TOK[cab]; note = None
        rows = fin_rows(tok, d0, d1, "weekly")
        if not rows:   # haftalik hisobot hali shakllanmagan bo'lsa — kunlik hisobotlar yig'indisi
            rows = fin_rows(tok, d0, d1, "daily")
            if rows: note = "haftalik hisobot hali tayyor emas — kunlik hisobotlar yig'indisi"
        return rows, cards(tok), note
    res = par(one, list(TOK))
    lab = f"{d0:%d.%m}–{d1:%d.%m.%Y}"
    out = dict(mode="weekly", lab=lab, dateFrom=f"{d0}", dateTo=f"{d1}", cabs={}, rows=[], errors={})
    for cab in TOK:
        r, err = res[cab]
        if err: out["errors"][cab] = err; continue
        rows, card, note = r
        A = aggregate(rows, cost, card)
        A["note"] = note; A["reports"] = sorted({(x.get("reportId"), x.get("dateFrom"), x.get("dateTo")) for x in rows})
        out["cabs"][cab] = A
        out["rows"] += std_rows(lab, cab, A["items"])
    return out

def run_monthly(today=None):
    t = today or dt.datetime.now(TZ).date()
    e = t.replace(day=1); s = (e - dt.timedelta(days=1)).replace(day=1)
    tag = f"{s:%Y-%m}"; ptag = f"{(s - dt.timedelta(days=1)):%Y-%m}"
    arch_p = os.path.join(H, "wb_archive.json")
    arch = json.load(open(arch_p)) if os.path.exists(arch_p) else {"months": {}}
    have = set(arch.get("months", {}))
    # arxivda yo'q oylar (BACKFILL_FROM dan) — API'dan orqaga yuklab olinadi
    need, m = [], BACKFILL_FROM.replace(day=1)
    while m <= s:
        mt = f"{m:%Y-%m}"
        if mt not in have or mt == tag: need.append(m)
        m = (m + dt.timedelta(days=32)).replace(day=1)
    d0 = min(need) if need else s
    cost = load_cost()
    def one(cab):
        return fin_rows(TOK[cab], d0, e - dt.timedelta(days=1), "weekly"), cards(TOK[cab])
    res = par(one, list(TOK))
    out = dict(mode="monthly", lab=f"{UZ_MONTHS[s.month].capitalize()} {s.year}", tag=tag, ptag=ptag, cabs={}, rows=[], errors={}, backfilled=[])
    for cab in TOK:
        r, err = res[cab]
        if err: out["errors"][cab] = err; continue
        rows, card = r
        bym = collections.defaultdict(list)
        for x in rows:
            bym[(x.get("dateFrom") or x.get("rrDate") or "")[:7]].append(x)
        for mt, rr in bym.items():
            if mt < f"{d0:%Y-%m}" or mt > tag: continue
            A = aggregate(rr, cost, card)
            arch.setdefault("months", {}).setdefault(mt, {})[cab] = dict(
                tot={k: round(v, 2) for k, v in A["tot"].items()}, rets=A["rets"],
                pen={k: round(sum(p["summa"] for p in A["pen"] if p["sabab"] == k), 2) for k in {p["sabab"] for p in A["pen"]}},
                ded={k: round(sum(p["summa"] for p in A["ded"] if p["sabab"] == k), 2) for k in {p["sabab"] for p in A["ded"]}},
                items=[{k: (round(v, 2) if isinstance(v, float) else v) for k, v in i.items() if k in ("nm", "vc", "title", "soni", "vozvrat", "sotuv", "yakuniy", "tannarx", "foyda")} for i in A["items"]])
            if mt != tag and mt not in have: out["backfilled"].append(f"{cab} {mt}")
            if mt == tag:
                out["cabs"][cab] = A
                out["rows"] += std_rows(out["lab"], cab, A["items"])
        if cab not in out["cabs"]:
            out["cabs"][cab] = aggregate([], cost, card)
    for m in need:   # ma'lumot bo'lmagan oylar ham "tekshirilgan" deb belgilanadi (qayta so'ralmaydi)
        if not out["errors"]: arch.setdefault("months", {}).setdefault(f"{m:%Y-%m}", {})
    arch["updated"] = dt.datetime.now(TZ).isoformat(timespec="minutes")
    out["archive"] = arch
    out["prev"] = {cab: (arch["months"].get(ptag) or {}).get(cab) for cab in TOK}
    os.makedirs(OUTD, exist_ok=True)
    json.dump(arch, open(os.path.join(OUTD, "wb_archive.json"), "w"), ensure_ascii=False, indent=1)
    return out

def run_daily(today=None):
    t = today or dt.datetime.now(TZ).date()
    y = t - dt.timedelta(days=1)
    w0, w1 = last_week(t)
    cost = load_cost()
    def one(cab):
        tok = TOK[cab]
        sales = stat(tok, "sales", f"{min(w0, y)}")
        time.sleep(1)
        orders = stat(tok, "orders", f"{y}", flag=1)
        rows = fin_rows(tok, w0, w1, "weekly")
        if not rows: rows = fin_rows(tok, w0, w1, "daily")
        return sales, orders, rows, cards(tok)
    res = par(one, list(TOK))
    rates = []
    for cab in TOK:
        r, err = res[cab]
        if r:
            rt, n = rate_from(r[2], r[0])
            if rt: rates += [rt] * n
    rate = statistics.median(rates) if rates else None
    out = dict(mode="daily", lab=f"{y:%d.%m.%Y}", date=f"{y}", rate=round(rate, 2) if rate else None, cabs={}, rows=[], errors={})
    for cab in TOK:
        r, err = res[cab]
        if err: out["errors"][cab] = err; continue
        sales, orders, rows, card = r
        W = aggregate(rows, cost, card)
        share = {i["nm"]: (i["yakuniy"] / i["sotuv"]) for i in W["items"] if i["sotuv"] > 0}
        base = (W["tot"]["yakuniy"] / W["tot"]["sotuv"]) if W["tot"]["sotuv"] > 0 else None
        items = collections.OrderedDict()
        for s_ in sales:
            if (s_.get("date") or "")[:10] != f"{y}": continue
            nm = s_.get("nmId"); ret = (s_.get("saleID") or "").startswith("R")
            it = items.setdefault(nm, dict(nm=nm, vc=s_.get("supplierArticle") or "", title=(card.get(nm) or {}).get("title") or s_.get("subject") or "",
                                           soni=0, vozvrat=0, rub=0.0, photo=(card.get(nm) or {}).get("photo")))
            if ret: it["vozvrat"] += 1
            else: it["soni"] += 1
            it["rub"] += (-1 if ret else 1) * abs(s_.get("finishedPrice") or 0)
        for it in items.values():
            it["sotuv"] = it["rub"] * (rate or 0)
            sh = share.get(it["nm"], base)
            it["share_src"] = "tovar" if it["nm"] in share else "kabinet"
            it["yakuniy"] = it["sotuv"] * sh if sh is not None else 0.0
            for k in ("komissiya", "logistika", "saqlash", "obrabotka", "jarima", "ushlab"):
                it[k] = 0.0
            it["komissiya"] = it["sotuv"] - it["yakuniy"]   # taxminiy: barcha rasxodlar bitta ulushda
            unit = cost[0].get(it["nm"]) or cost[1].get((it["vc"] or "").lower())
            it["tannarx"] = (unit or 0) * (it["soni"] - it["vozvrat"]); it["no_cost"] = bool(it["soni"] and not unit)
            it["foyda"] = it["yakuniy"] - it["tannarx"]
        L = sorted(items.values(), key=lambda i: -i["sotuv"])
        tot = {k: sum(i[k] for i in L) for k in FIELDS + ["soni", "vozvrat"]}
        od = [o for o in orders if (o.get("date") or "")[:10] == f"{y}"]
        yp = f"{y - dt.timedelta(days=1)}"; pv = dict(soni=0, vozvrat=0, rub=0.0)
        for s_ in sales:
            if (s_.get("date") or "")[:10] != yp: continue
            ret = (s_.get("saleID") or "").startswith("R")
            pv["vozvrat" if ret else "soni"] += 1; pv["rub"] += (-1 if ret else 1) * abs(s_.get("finishedPrice") or 0)
        pv["sotuv"] = pv["rub"] * (rate or 0)
        A = dict(prev=pv, items=L, tot=tot, orders=len(od), canc=sum(1 for o in od if o.get("isCancel")),
                 share=round(base, 4) if base is not None else None, week=f"{w0:%d.%m}–{w1:%d.%m}")
        out["cabs"][cab] = A
        out["rows"] += std_rows(out["lab"], cab, L, approx=True)
    return out

def ue_cab(out, ci, cab, card, cost, ex, rate):
    """Narx tekshiruvi: tarixiy komissiya/logistika, buyurtmalar (FBO+FBS) va FBS yig'ilayotganlar."""
    if ex.get("err"): out["errors"][cab + " narx"] = "; ".join(ex["err"])[:200]
    if ex.get("noscope"): out.setdefault("noscope", {})[cab] = ex["noscope"]
    def item(nm, vc="", title=""):
        if nm not in out["items"]:
            c = card.get(nm) or {}
            unit = cost[0].get(nm) or cost[1].get((vc or c.get("vc") or "").lower())
            out["items"][nm] = dict(c=ci, vc=c.get("vc") or vc or "", t=c.get("title") or title or "", cost=unit or 0, sh=0, ph=c.get("photo"))
        it = out["items"][nm]; c = card.get(nm) or {}
        it.setdefault("sub", c.get("sub")); it.setdefault("subn", c.get("subn")); it.setdefault("vol", c.get("vol") or 0)
        return it
    # tarix (8 hafta realizatsiya): tovar va kabinet bo'yicha komissiya ulushi, 1 dona logistika
    H_ = collections.defaultdict(lambda: dict(q=0, r=0, sotuv=0.0, forpay=0.0, log=0.0, pen=0.0))
    for x in ex.get("hist") or []:
        nm = x.get("nmId") or 0; s_ = sign(x); h = H_[nm]
        op = (x.get("sellerOperName") or "").lower(); q = int(x.get("quantity") or 0)
        if op in ("продажа", "возврат"):
            if s_ > 0: h["q"] += q
            else: h["r"] += q
        h["sotuv"] += s_ * num(x.get("retailAmount")); h["forpay"] += s_ * num(x.get("forPay"))
        h["log"] += num(x.get("deliveryService")); h["pen"] += num(x.get("penalty"))
    T = dict(q=0, sotuv=0.0, forpay=0.0, log=0.0, pen=0.0, lv=0.0)
    for nm, h in H_.items():
        for k in ("q", "sotuv", "forpay", "log", "pen"): T[k] += h[k]
        if nm:
            it = item(nm); net = h["q"] - h["r"]
            it["hq"] = net
            if h["sotuv"] > 0 and h["q"] >= 1: it["hk"] = round(1 - h["forpay"] / h["sotuv"], 4)
            if net >= 3: it["hl"] = round(h["log"] / net)
            T["lv"] += max(0, net) * (it.get("vol") or 0)
    out["ue"]["cab"][cab] = dict(q=T["q"], kom=round(1 - T["forpay"] / T["sotuv"], 4) if T["sotuv"] > 0 else None,
                                 logU=round(T["log"] / T["q"]) if T["q"] else None, logL=round(T["log"] / T["lv"]) if T["lv"] > 0 else None,
                                 penU=round(T["pen"] / T["q"]) if T["q"] else None, pen=round(T["pen"]), log=round(T["log"]))
    for nm, v in (ex.get("pr") or {}).items():
        if nm: item(nm)["pr"] = v
    for sub, v in (ex.get("comm") or {}).items():
        if sub is not None: out["ue"]["comm"][str(sub)] = v
    # buyurtmalar (statistika, 14 kun): [ts, kabinet, nm, so'm, bekor, FBS?, srid]
    for o in ex.get("ords") or []:
        try: ts = int(dt.datetime.fromisoformat(o["date"]).replace(tzinfo=MSK).timestamp())
        except Exception: continue
        nm = o.get("nmId"); item(nm, o.get("supplierArticle") or "", o.get("subject") or "")
        fbs = 1 if "продав" in (o.get("warehouseType") or "").lower() else 0
        out["ords"].append([ts, ci, nm, round((o.get("priceWithDisc") or 0) * (rate or 0)), 1 if o.get("isCancel") else 0, fbs, o.get("srid") or ""])
    # FBS yig'ish (marketplace, 7 kun): [id, kabinet, nm, ts, so'm, rid, artikul]
    for o in ex.get("asm") or []:
        try: ts = int(dt.datetime.fromisoformat((o.get("createdAt") or "").replace("Z", "+00:00")).timestamp())
        except Exception: ts = 0
        nm = o.get("nmId"); item(nm, o.get("article") or "")
        p = None
        for pk, ck in (("price", "currencyCode"), ("convertedPrice", "convertedCurrencyCode")):
            if o.get(ck) == 860 and o.get(pk): p = o[pk] / 100
        if p is None:
            for pk, ck in (("price", "currencyCode"), ("convertedPrice", "convertedCurrencyCode")):
                if o.get(ck) == 643 and o.get(pk) and rate: p = o[pk] / 100 * rate
        out["asm"].append([o.get("id"), ci, nm, ts, round(p or 0, 2), o.get("rid") or "", o.get("article") or ""])

def ue_glob(out):
    """Barcha kabinetlar bo'yicha o'rtacha 1 litr logistika (tovar tarixi yo'q bo'lsa ishlatiladi)."""
    L = [c for c in out["ue"]["cab"].values() if c.get("logL")]
    q = sum(c["q"] for c in L)
    out["ue"]["logL"] = round(sum(c["logL"] * c["q"] for c in L) / q) if q else None
    K = [c for c in out["ue"]["cab"].values() if c.get("kom") is not None and c["q"]]
    q = sum(c["q"] for c in K)
    out["ue"]["kom"] = round(sum(c["kom"] * c["q"] for c in K) / q, 4) if q else None
    out["ords"].sort(key=lambda r: -r[0]); out["asm"].sort(key=lambda r: -r[3])

def run_dash(days=90):
    """"Uzum Pult" dashboardi uchun WB ma'lumoti -> ~/dash/wb.json.
    Kunlik sotuv/vozvrat (statistika, ₽ -> so'm), har tovar ~to'lov va ~foyda (o'tgan hafta realizatsiyasidagi ulush), o'tgan hafta aniq realizatsiyasi."""
    import base64
    t = dt.datetime.now(TZ).date(); w0, w1 = last_week(t)
    cost = load_cost()
    def one(cab):
        tok = TOK[cab]
        sales = stat(tok, "sales", f"{t - dt.timedelta(days=days)}")
        rows = fin_rows(tok, w0, w1, "weekly")
        note = None
        if not rows:
            rows = fin_rows(tok, w0, w1, "daily"); note = "haftalik hisobot hali tayyor emas — kunlik hisobotlar yig'indisi"
        ex = {}
        for k, f in (("ords", lambda: stat(tok, "orders", f"{t - dt.timedelta(days=14)}")), ("asm", lambda: mp_orders(tok, 7)),
                     ("hist", lambda: fin_rows(tok, w1 - dt.timedelta(days=55), w1, "weekly")), ("comm", lambda: commission(tok)), ("pr", lambda: prices(tok))):
            try: ex[k] = f()
            except Exception as x:
                ex[k] = None
                if re.search(r"HTTP 40[13]", str(x)): ex.setdefault("noscope", []).append(k)   # token'da shu bo'lim ruxsati yo'q — xato emas
                else: ex.setdefault("err", []).append(f"{k}: {hide(x)[:80]}")
        return sales, rows, cards(tok), note, ex
    res = par(one, list(TOK))
    rates = []
    for cab in TOK:
        r, err = res[cab]
        if r:
            rt, n = rate_from(r[1], r[0])
            if rt: rates += [rt] * n
    rate = statistics.median(rates) if rates else None
    cabs = list(TOK); out = dict(gen=int(time.time()), rate=round(rate, 2) if rate else None, days=days, cabs=cabs, rows=[], items={}, week={}, errors={}, imgs={},
                                ords=[], asm=[], ue=dict(cab={}, comm={}))
    for ci, cab in enumerate(cabs):
        r, err = res[cab]
        if err: out["errors"][cab] = err; continue
        sales, rows, card, note, ex = r
        W = aggregate(rows, cost, card)
        share = {i["nm"]: (i["yakuniy"] / i["sotuv"]) for i in W["items"] if i["sotuv"] > 0}
        base = (W["tot"]["yakuniy"] / W["tot"]["sotuv"]) if W["tot"]["sotuv"] > 0 else None
        out["week"][cab] = dict(lab=f"{w0:%d.%m}–{w1:%d.%m}", note=note, tot={k: round(v) for k, v in W["tot"].items()},
                                items=[dict(nm=i["nm"], vc=i["vc"], q=i["soni"] - i["vozvrat"], sotuv=round(i["sotuv"]), yakuniy=round(i["yakuniy"]), foyda=round(i["foyda"]),
                                            tannarx=round(i["tannarx"])) for i in W["items"]],
                                pen=[dict(vc=p["vc"], sabab=p["sabab"], summa=round(p["summa"]), sana=p["sana"]) for p in W["pen"] + W["ded"]])
        agg_ = collections.defaultdict(lambda: [0, 0, 0.0])
        for s_ in sales:
            d = (s_.get("date") or "")[:10]; nm = s_.get("nmId")
            if not d or not nm: continue
            ret = (s_.get("saleID") or "").startswith("R")
            a = agg_[(d, nm)]
            if ret: a[1] += 1
            else: a[0] += 1
            a[2] += (-1 if ret else 1) * abs(s_.get("finishedPrice") or 0)
            if nm not in out["items"]:
                c = card.get(nm) or {}
                unit = cost[0].get(nm) or cost[1].get((s_.get("supplierArticle") or "").lower())
                out["items"][nm] = dict(c=ci, vc=c.get("vc") or s_.get("supplierArticle") or "", t=c.get("title") or s_.get("subject") or "",
                                        cost=unit or 0, sh=round(share.get(nm, base) or 0, 4), ph=c.get("photo"))
        for (d, nm), (q, rq, rub) in agg_.items():
            out["rows"].append([d, ci, nm, q, rq, round(rub * (rate or 0))])
        try: ue_cab(out, ci, cab, card, cost, ex, rate)
        except Exception as x: out["errors"][cab + " narx"] = hide(x)[:120]
    try: ue_glob(out)
    except Exception as x: out["errors"]["narx"] = hide(x)[:120]
    # rasmlar (wbbasket ruxsat etilgan bo'lsa) — kichik thumbnail, data URI
    act = {r[2] for r in out["rows"]} | {r[2] for r in out["ords"]} | {r[2] for r in out["asm"]}
    for nm, it in out["items"].items():
        if nm not in act and len(out["items"]) > 150: continue   # faqat sotilgan/buyurtma bo'lganlar rasmi (tezlik uchun)
        im = get_img(it.get("ph"))
        if im is not None:
            im = im.copy(); im.thumbnail((88, 117)); b = io.BytesIO(); im.save(b, "JPEG", quality=80)
            out["imgs"][str(nm)] = "data:image/jpeg;base64," + base64.b64encode(b.getvalue()).decode()
    for it in out["items"].values(): it.pop("ph", None)
    os.makedirs(os.path.join(H, "dash"), exist_ok=True)
    json.dump(out, open(os.path.join(H, "dash", "wb.json"), "w"), ensure_ascii=False, separators=(",", ":"))
    return out

def run_hourly():
    now = dt.datetime.now(TZ); d0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    w0, w1 = last_week(now.date())
    def one(cab):
        tok = TOK[cab]
        o = stat(tok, "orders", d0.astimezone(MSK).strftime("%Y-%m-%dT%H:%M:%S"))
        return o
    res = par(one, list(TOK))
    # kurs: birinchi savdosi bor kabinetdan (realizatsiya + statistika)
    rate = None
    for cab in TOK:
        try:
            rows = fin_rows(TOK[cab], w0, w1, "weekly")
            sales = stat(TOK[cab], "sales", f"{w0}")
            rate, n = rate_from(rows, sales)
            if rate: break
        except Exception:
            continue
    out = dict(mode="hourly", lab=f"{now:%d.%m.%Y %H:%M}", rate=round(rate, 2) if rate else None, cabs={}, errors={})
    for cab in TOK:
        o, err = res[cab]
        if err: out["errors"][cab] = err; continue
        today = [x for x in o if dt.datetime.fromisoformat(x["date"]).replace(tzinfo=MSK) >= d0]
        ok = [x for x in today if not x.get("isCancel")]
        rub = sum(x.get("priceWithDisc") or 0 for x in ok)
        top = collections.Counter(x.get("supplierArticle") for x in ok).most_common(5)
        out["cabs"][cab] = dict(orders=len(ok), canc=len(today) - len(ok), rub=rub, uzs=rub * rate if rate else None, top=top)
    return out

# ---------------------------------------------------------------- matn yig'ish, birlashtirish
def text_of(R, uz=None):
    m = R["mode"]; L = []
    if m == "hourly":
        L.append(f"🟪 Wildberries · bugun {R['lab']} gacha")
        for cab, A in R["cabs"].items():
            L.append(f"• {cab}: {A['orders']} buyurtma" + (f" (+{A['canc']} bekor)" if A["canc"] else "") +
                     (f", ≈{F(A['uzs'])} so'm" if A.get("uzs") else f", {F(A['rub'])} ₽"))
            if A["top"]: L.append("   " + ", ".join(f"{a} {q}" for a, q in A["top"]))
        if R.get("rate"): L.append(f"(kurs ≈ {R['rate']:.1f} so'm/₽, o'tgan hafta realizatsiyasidan)")
    else:
        kind = {"daily": "Kunlik (~taxminiy)", "weekly": "Haftalik (aniq realizatsiya)", "monthly": "Oylik"}[m]
        L += [f"📊 WILDBERRIES · {kind} · {R['lab']}", ""]
        for cab, A in R["cabs"].items():
            extra = []
            if m == "daily":
                extra.append(f"buyurtmalar {A['orders']}" + (f", bekor {A['canc']}" if A["canc"] else "") +
                             (f" · rasxod ulushi {A['week']} haftasidan" if A.get("share") is not None else " · o'tgan hafta realizatsiyasi yo'q"))
            if m == "weekly":
                if A.get("note"): extra.append("⚠ " + A["note"])
                loss = [i for i in A["items"] if i["foyda"] < 0 and i["nm"] and i["soni"] - i["vozvrat"] > 0]
                if loss:
                    extra.append("🔴 ZARARGA SOTILGANLAR:")
                    extra += [f"   🔴 {i['vc']}: {i['soni'] - i['vozvrat']} dona, sotuv {F(i['sotuv'])}, yakuniy {F(i['yakuniy'])}, tannarx {F(i['tannarx'])} → {F(i['foyda'])} so'm"
                              for i in sorted(loss, key=lambda i: i["foyda"])[:10]]
                idle = [i for i in A["items"] if i["foyda"] < 0 and i["nm"] and i["soni"] - i["vozvrat"] <= 0]
                if idle:
                    extra.append(f"🔴 Sotuvsiz rasxod (logistika/obrabotka/jarima): {len(idle)} tovar, jami {F(sum(i['foyda'] for i in idle))} so'm — "
                                 + ", ".join(f"{i['vc']} {S(i['foyda'])}" for i in sorted(idle, key=lambda i: i["foyda"])[:6]))
                for p in A["pen"]:
                    extra.append(f"⚠ Jarima {F(p['summa'])} so'm — {p['sabab']} ({p['vc']}, {p['sana']})")
                for p in A["ded"]:
                    extra.append(f"⚠ Ushlab qolish {F(p['summa'])} so'm — {cut(p['sabab'], 90)} ({p['sana']})")
                nc = [i["vc"] for i in A["items"] if i.get("no_cost")]
                if nc: extra.append("tannarx yo'q: " + ", ".join(nc[:8]))
            if m == "monthly":
                P = (R.get("prev") or {}).get(cab)
                if P:
                    pt = P["tot"]
                    extra.append(f"o'tgan oyga nisbatan: sotuv {arrow(A['tot']['sotuv'], pt['sotuv'])}, yakuniy {arrow(A['tot']['yakuniy'], pt['yakuniy'])}, foyda {arrow(A['tot']['foyda'], pt['foyda'])}")
                pv = prev_items(R, cab)
                top = sorted([i for i in A["items"] if i["nm"] and i["soni"] - i["vozvrat"] > 0], key=lambda i: -i["sotuv"])[:5]
                if top:
                    extra.append("🏆 TOP-5: " + "; ".join(f"{i['vc']} {i['soni'] - i['vozvrat']} dona, {S(i['sotuv'])}"
                                                          + (f" ({delta_s(i['sotuv'], (pv.get(i['nm']) or {}).get('sotuv'))[0]})" if pv else "") for i in top))
                if A["rets"]: extra.append("vozvratlar: " + "; ".join(f"{k} — {v}" for k, v in A["rets"].items()))
                pens = collections.Counter()
                for p in A["pen"]: pens[p["sabab"]] += p["summa"]
                for k, v in pens.items(): extra.append(f"⚠ Jarima: {k} — {F(v)} so'm")
                for p in A["ded"]: extra.append(f"⚠ Ushlab qolish: {cut(p['sabab'], 90)} — {F(p['summa'])} so'm")
            L += cab_block(cab, A, m, approx=(m == "daily"), extra=extra) + [""]
        if m == "daily" and R.get("rate"):
            L.append(f"Kurs: {R['rate']:.1f} so'm/₽ (o'tgan hafta realizatsiyasi, bir xil srid bo'yicha). ~ — taxminiy.")
    for cab, e in R.get("errors", {}).items():
        L.append(f"❌ WB {cab}: {e}")
    if uz:
        L += [""] + combined_lines(R, uz)
    return "\n".join(L).rstrip()

def wb_totals(R):
    T = collections.Counter()
    for A in R["cabs"].values():
        T.update({k: A["tot"].get(k, 0) for k in FIELDS + ["soni", "vozvrat"]})
    return T

def combined_lines(R, uz):
    """uz: dict(sales, payout, cost, profit) — Uzum jami (shu davr)."""
    T = wb_totals(R); p = "~" if R["mode"] == "daily" else ""
    s, pay, fo = uz.get("sales", 0) + T["sotuv"], uz.get("payout", 0) + T["yakuniy"], uz.get("profit", 0) + T["foyda"]
    L = ["🌐 BARCHA MARKETPLACE'LAR JAMI (Uzum + WB)",
         f"  Savdo: {F(s)} so'm (Uzum {S(uz.get('sales', 0))} · WB {S(T['sotuv'])})",
         f"  To'lovga/yakuniy: {p}{F(pay)} so'm (Uzum {S(uz.get('payout', 0))} · WB {p}{S(T['yakuniy'])})",
         f"  FOYDA: {p}{F(fo)} so'm (Uzum {S(uz.get('profit', 0))} · WB {p}{S(T['foyda'])})"]
    if s: L.append(f"  Ulush: Uzum {uz.get('sales', 0) / s * 100:.0f}% · WB {T['sotuv'] / s * 100:.0f}%")
    return L

# ---------------------------------------------------------------- oylik grafiklar
def charts_monthly(R, uz_hist, path):
    """1) oyma-oy dinamika (sotuv va foyda, Uzum + WB), 2) marketplace ulushi, 3) WB rasxodlar tarkibi."""
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    months = sorted(m for m in set(R["archive"]["months"]) | set(uz_hist or {})
                    if any((v.get("tot") or {}).get("sotuv") for v in (R["archive"]["months"].get(m) or {}).values()) or (uz_hist or {}).get(m))[-12:]
    wb_s = [sum((R["archive"]["months"].get(m, {}).get(c) or {}).get("tot", {}).get("sotuv", 0) for c in TOK) for m in months]
    wb_f = [sum((R["archive"]["months"].get(m, {}).get(c) or {}).get("tot", {}).get("foyda", 0) for c in TOK) for m in months]
    uz_s = [((uz_hist or {}).get(m) or {}).get("sales", 0) for m in months]
    uz_f = [((uz_hist or {}).get(m) or {}).get("profit", 0) for m in months]
    fig = plt.figure(figsize=(12, 13.5), dpi=100); fig.patch.set_facecolor("#F6F5FB")
    fig.suptitle(f"Barcha marketplace'lar · {R['lab']}", fontsize=22, weight="bold", x=0.05, ha="left", y=0.985)
    ax = fig.add_axes([0.07, 0.66, 0.9, 0.27]); x = range(len(months))
    ax.bar([i - 0.2 for i in x], [v / 1e6 for v in uz_s], 0.4, color="#7000FF", label="Uzum sotuv")
    ax.bar([i + 0.2 for i in x], [v / 1e6 for v in wb_s], 0.4, color="#CB11AB", label="WB sotuv")
    ax.plot(list(x), [(a + b) / 1e6 for a, b in zip(uz_f, wb_f)], "o-", color="#12805c", label="Jami foyda")
    ax.set_xticks(list(x)); ax.set_xticklabels([f"{UZ_MONTHS[int(m[5:])][:4 if int(m[5:]) in (6, 7) else 3]} {m[2:4]}" for m in months], fontsize=10)
    ax.set_ylabel("mln so'm"); ax.set_title("Oyma-oy dinamika", loc="left", fontsize=15, weight="bold"); ax.legend(frameon=False)
    for sp in ("top", "right"): ax.spines[sp].set_visible(False)
    T = wb_totals(R); uzc = (uz_hist or {}).get(R["tag"]) or {}
    ax2 = fig.add_axes([0.05, 0.31, 0.4, 0.27])
    vals = [uzc.get("sales", 0), T["sotuv"]]
    if sum(vals) > 0:
        ax2.pie(vals, labels=[f"Uzum\n{S(vals[0])}", f"WB\n{S(vals[1])}"], colors=["#7000FF", "#CB11AB"], autopct="%1.0f%%",
                textprops=dict(color="#1D1B2C", fontsize=12), wedgeprops=dict(width=0.45))
    ax2.set_title("Marketplace ulushi (savdo)", loc="left", fontsize=15, weight="bold")
    ax3 = fig.add_axes([0.55, 0.31, 0.4, 0.27])
    parts = [("Komissiya", T["komissiya"]), ("Logistika", T["logistika"]), ("Saqlash", T["saqlash"]), ("Obrabotka", T["obrabotka"]),
             ("Jarima", T["jarima"]), ("Ushlab qolish", T["ushlab"])]
    parts = [p for p in parts if p[1] > 0]
    if parts:
        ax3.barh([p[0] for p in parts][::-1], [p[1] / 1e3 for p in parts][::-1], color="#CB11AB")
        for i, p in enumerate(parts[::-1]):
            ax3.text(p[1] / 1e3, i, f" {S(p[1])}", va="center", fontsize=11)
    ax3.set_title("WB rasxodlar tarkibi (ming so'm)", loc="left", fontsize=15, weight="bold")
    for sp in ("top", "right"): ax3.spines[sp].set_visible(False)
    ax4 = fig.add_axes([0.05, 0.02, 0.9, 0.22]); ax4.axis("off")
    hdr = ["Kabinet", "Sotuv", "Sotuv Δ", "Yakuniy", "Tannarx", "Foyda", "O'tgan oy", "Foyda Δ"]
    cell = []
    for cab, A in R["cabs"].items():
        P = ((R.get("prev") or {}).get(cab) or {}).get("tot") or {}
        cell.append([f"WB {cab}", S(A["tot"]["sotuv"]), delta_s(A["tot"]["sotuv"], P.get("sotuv"))[0] or "—", S(A["tot"]["yakuniy"]), S(A["tot"]["tannarx"]),
                     S(A["tot"]["foyda"]), S(P.get("foyda", 0)) if P else "—", delta_s(A["tot"]["foyda"], P.get("foyda"))[0] or "—"])
    if uzc:
        up = (uz_hist or {}).get(R["ptag"]) or {}
        cell.append(["Uzum (jami)", S(uzc.get("sales", 0)), delta_s(uzc.get("sales", 0), up.get("sales"))[0] or "—", S(uzc.get("payout", 0)), S(uzc.get("cost", 0)),
                     S(uzc.get("profit", 0)), S(up.get("profit", 0)) if up else "—", delta_s(uzc.get("profit", 0), up.get("profit"))[0] or "—"])
    if cell:
        tb = ax4.table(cellText=cell, colLabels=hdr, loc="upper center", cellLoc="right", colLoc="right")
        tb.auto_set_font_size(False); tb.set_fontsize(12); tb.scale(1, 2)
    ax4.set_title("Kabinetlar bo'yicha", loc="left", fontsize=15, weight="bold")
    fig.savefig(path, facecolor=fig.get_facecolor()); plt.close(fig)

def prev_items(R, cab):
    P = (R.get("prev") or {}).get(cab) or {}
    return {i["nm"]: i for i in P.get("items", []) if i.get("nm")}

def monthly_compare_png(R, uz_hist, path):
    """Oylik taqqoslash: KPI (Jami / Uzum / WB) o'tgan oyga nisbatan, TOP-10 WB tovar (bu oy vs o'tgan oy), eng foydali va zarardagilar."""
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.family": "DejaVu Sans", "axes.spines.top": False, "axes.spines.right": False})
    T = wb_totals(R); arch = R["archive"]["months"]
    TP = collections.Counter()
    for c in TOK:
        TP.update({k: ((arch.get(R["ptag"]) or {}).get(c) or {}).get("tot", {}).get(k, 0) for k in ("sotuv", "yakuniy", "foyda", "soni", "vozvrat")})
    uz, uzp = (uz_hist or {}).get(R["tag"]) or {}, (uz_hist or {}).get(R["ptag"]) or {}
    cols = [("JAMI (Uzum + WB)", uz.get("sales", 0) + T["sotuv"], uz.get("profit", 0) + T["foyda"],
             (uzp.get("sales", 0) + TP["sotuv"]) if (uzp or TP["sotuv"]) else None, (uzp.get("profit", 0) + TP["foyda"]) if (uzp or TP["sotuv"]) else None, "#1D1B2C"),
            ("Uzum", uz.get("sales", 0), uz.get("profit", 0), uzp.get("sales") if uzp else None, uzp.get("profit") if uzp else None, "#7000FF"),
            ("Wildberries", T["sotuv"], T["foyda"], TP["sotuv"] if TP["sotuv"] else None, TP["foyda"] if TP["sotuv"] else None, "#CB11AB")]
    fig = plt.figure(figsize=(12, 15), dpi=100, facecolor="#F6F5FB")
    pm = UZ_MONTHS[int(R["ptag"][5:])]
    fig.text(0.04, 0.975, f"Oylik taqqoslash · {R['lab']}", fontsize=24, weight="bold", va="top")
    fig.text(0.04, 0.948, f"o'tgan oy ({pm}) bilan · savdo, sof foyda, marja", fontsize=13, color="#6E6A85", va="top")
    for j, (nm, s, f, ps, pf, col) in enumerate(cols):
        x0 = 0.04 + j * 0.315
        ax = fig.add_axes([x0, 0.80, 0.29, 0.125]); ax.axis("off")
        ax.add_patch(plt.Rectangle((0, 0), 1, 1, transform=ax.transAxes, facecolor="white", edgecolor="#E6E3F0"))
        ax.text(0.06, 0.88, nm, fontsize=13, weight="bold", color=col, transform=ax.transAxes, va="top")
        ax.text(0.06, 0.66, f"Savdo {S(s)}", fontsize=15, weight="bold", transform=ax.transAxes, va="top")
        ds, dc = delta_s(s, ps); ax.text(0.94, 0.66, ds, fontsize=13, weight="bold", color=dc, transform=ax.transAxes, va="top", ha="right")
        ax.text(0.06, 0.40, f"Foyda {S(f)}", fontsize=15, weight="bold", color="#14A660" if f >= 0 else "#E5484D", transform=ax.transAxes, va="top")
        ds, dc = delta_s(f, pf); ax.text(0.94, 0.40, ds, fontsize=13, weight="bold", color=dc, transform=ax.transAxes, va="top", ha="right")
        mj = f"Marja {f / s * 100:.1f}%" if s else "Marja —"
        if ps and pf is not None: mj += f"  (o'tgan oy {pf / ps * 100:.1f}%)"
        ax.text(0.06, 0.14, mj, fontsize=11, color="#6E6A85", transform=ax.transAxes, va="top")
    # TOP-10 WB tovar: bu oy vs o'tgan oy
    cur = []
    for cab, A in R["cabs"].items():
        pv = prev_items(R, cab)
        for i in A["items"]:
            if i["nm"] and i["sotuv"] > 0:
                p = pv.get(i["nm"]) or {}
                cur.append((f"{cut(i['vc'], 26)} ({cab})", i["sotuv"], p.get("sotuv", 0), i["soni"] - i["vozvrat"], i["foyda"]))
    cur.sort(key=lambda z: -z[1]); top = cur[:10][::-1]
    ax = fig.add_axes([0.25, 0.42, 0.68, 0.33])
    if top:
        y = range(len(top))
        ax.barh([k + 0.2 for k in y], [z[1] / 1e3 for z in top], 0.4, color="#CB11AB", label=f"{UZ_MONTHS[int(R['tag'][5:])]}")
        ax.barh([k - 0.2 for k in y], [z[2] / 1e3 for z in top], 0.4, color="#D9D3EC", label=pm)
        ax.set_yticks(list(y)); ax.set_yticklabels([z[0] for z in top], fontsize=10)
        mx = max(z[1] for z in top) / 1e3
        for k, z in enumerate(top):
            ax.text(z[1] / 1e3 + mx * 0.01, k + 0.2, f"{z[3]} dona · foyda {S(z[4])}", va="center", fontsize=9, color="#14A660" if z[4] >= 0 else "#E5484D")
        ax.set_xlim(0, mx * 1.45); ax.legend(frameon=False, loc="lower right")
    ax.set_xlabel("ming so'm"); ax.set_title("WB TOP-10 tovar (savdo) — bu oy va o'tgan oy", loc="left", fontsize=15, weight="bold")
    # Eng foydali / zarardagi
    allit = [(cab, i) for cab, A in R["cabs"].items() for i in A["items"] if i["nm"]]
    best = sorted([z for z in allit if z[1]["foyda"] > 0], key=lambda z: -z[1]["foyda"])[:6]
    worst = sorted([z for z in allit if z[1]["foyda"] < 0], key=lambda z: z[1]["foyda"])[:6]
    for k, (ttl, L, col) in enumerate((("Eng ko'p foyda keltirgan", best, "#14A660"), ("Zararda", worst, "#E5484D"))):
        ax = fig.add_axes([0.04 + k * 0.48, 0.05, 0.44, 0.30]); ax.axis("off")
        ax.add_patch(plt.Rectangle((0, 0), 1, 1, transform=ax.transAxes, facecolor="white", edgecolor="#E6E3F0"))
        ax.text(0.05, 0.93, ttl, fontsize=14, weight="bold", color=col, transform=ax.transAxes, va="top")
        if not L: ax.text(0.05, 0.78, "yo'q", fontsize=12, color="#6E6A85", transform=ax.transAxes, va="top")
        for r, (cab, i) in enumerate(L):
            yy = 0.78 - r * 0.125; q = i["soni"] - i["vozvrat"]
            ax.text(0.05, yy, cut(i["vc"], 24), fontsize=11, weight="bold", transform=ax.transAxes, va="top")
            ax.text(0.05, yy - 0.055, f"{cab} · {q} dona" if q else f"{cab} · sotuvsiz rasxod", fontsize=9, color="#6E6A85", transform=ax.transAxes, va="top")
            ax.text(0.95, yy, S(i["foyda"]), fontsize=12, weight="bold", color=col, transform=ax.transAxes, va="top", ha="right")
    fig.savefig(path, facecolor=fig.get_facecolor()); plt.close(fig)

# ---------------------------------------------------------------- Excel varag'i
def excel_sheet(wb, R):
    from openpyxl.styles import Font, PatternFill
    ws = wb.create_sheet("Wildberries")
    hdr = ["Sana", "Kabinet", "Artikul", "Nomi", "Soni", "Vozvrat", "Sotuv", "Komissiya", "Logistika", "Saqlash", "Obrabotka", "Jarima",
           "Ushlab qolish", "Yakuniy to'lov", "Tannarx", "FOYDA", "Rasm"]
    for j, h_ in enumerate(hdr, 1):
        c = ws.cell(1, j, h_); c.fill = PatternFill("solid", fgColor="CB11AB"); c.font = Font(bold=True, color="FFFFFF")
    for i, r in enumerate(R["rows"], 2):
        vals = [r["sana"], r["kabinet"], r["artikul"], r["nomi"], r["soni"], r["vozvrat"], r["sotuv"], r["komissiya"], r["logistika"], r["saqlash"],
                r["obrabotka"], r["jarima"], r["ushlab"], r["yakuniy"], r["tannarx"], r["foyda"], r["rasm"]]
        for j, v in enumerate(vals, 1):
            c = ws.cell(i, j, v)
            if 7 <= j <= 16: c.number_format = '#,##0;[Red]-#,##0'
        if r["foyda"] < 0: ws.cell(i, 16).font = Font(bold=True, color="E5484D")
    for j, w in enumerate([12, 11, 22, 44, 7, 8, 13, 12, 12, 10, 11, 10, 12, 14, 12, 13, 40], 1):
        ws.column_dimensions[ws.cell(1, j).column_letter].width = w
    ws.freeze_panes = "E2"; ws.auto_filter.ref = f"A1:Q{max(2, len(R['rows']) + 1)}"
    if R.get("mode") != "monthly": return
    # O'tgan oy bilan taqqoslash (har tovar)
    ws = wb.create_sheet("WB taqqoslash")
    hdr = ["Kabinet", "Artikul", "Nomi", "Soni", "Soni (o'tgan oy)", "Sotuv", "Sotuv (o'tgan oy)", "Sotuv Δ%", "Foyda", "Foyda (o'tgan oy)", "Foyda Δ"]
    for j, h_ in enumerate(hdr, 1):
        c = ws.cell(1, j, h_); c.fill = PatternFill("solid", fgColor="CB11AB"); c.font = Font(bold=True, color="FFFFFF")
    r_ = 2
    for cab, A in R["cabs"].items():
        pv = prev_items(R, cab); seen = set()
        rows = [(i, pv.get(i["nm"]) or {}) for i in A["items"] if i["nm"]]
        rows += [(dict(nm=nm, vc=p.get("vc"), title=p.get("title"), soni=0, vozvrat=0, sotuv=0.0, foyda=0.0), p) for nm, p in pv.items()
                 if nm not in {i["nm"] for i in A["items"]} and p.get("sotuv")]
        for i, p in sorted(rows, key=lambda z: -z[0]["sotuv"]):
            ps = p.get("sotuv") or 0
            vals = [cab, i["vc"], i["title"], i["soni"] - i.get("vozvrat", 0), (p.get("soni") or 0) - (p.get("vozvrat") or 0), i["sotuv"], ps,
                    (i["sotuv"] - ps) / ps if ps else None, i["foyda"], p.get("foyda") or 0, i["foyda"] - (p.get("foyda") or 0)]
            for j, v in enumerate(vals, 1):
                c = ws.cell(r_, j, v)
                if j in (6, 7, 9, 10, 11): c.number_format = '#,##0;[Red]-#,##0'
                if j == 8: c.number_format = '0%;[Red]-0%'
            r_ += 1
    for j, w in enumerate([11, 24, 44, 8, 10, 13, 13, 9, 13, 13, 13], 1):
        ws.column_dimensions[ws.cell(1, j).column_letter].width = w
    ws.freeze_panes = "D2"; ws.auto_filter.ref = f"A1:K{max(2, r_ - 1)}"

# ---------------------------------------------------------------- Uzum hisobotiga qo'shish (uzum_report.py chaqiradi)
def integrate(mode, uz_tot, uz_month_tag=None, d0=None, d1=None):
    """mode: weekly|monthly. uz_tot: Uzum jami dict(sales,payout,cost,profit). Qaytaradi: R, matn, png ro'yxati."""
    os.makedirs(OUTD, exist_ok=True)
    R = run_weekly(d0, d1) if mode == "weekly" else run_monthly()
    pngs, album = [], []
    for i, (cab, A) in enumerate(R["cabs"].items()):
        if not A["items"]: continue
        T_ = A["tot"]; pv = prev_items(R, cab) if mode == "monthly" else None
        P_ = ((R.get("prev") or {}).get(cab) or {}).get("tot") if mode == "monthly" else None
        sub = (f"{R['lab']} · sotuv {S(T_['sotuv'])} · {F(T_['soni'] - T_['vozvrat'])} dona · yakuniy {S(T_['yakuniy'])} · foyda {S(T_['foyda'])}"
               + (f" · o'tgan oyga: sotuv {delta_s(T_['sotuv'], P_.get('sotuv'))[0]}, foyda {delta_s(T_['foyda'], P_.get('foyda'))[0]}" if P_ else ""))
        p = os.path.join(OUTD, f"wb_{mode}_{cab}_kartochka.png")
        cards_png(p, f"Wildberries · {cab}", sub, A["items"], prev=pv); pngs.append(p)
        p = os.path.join(OUTD, f"wb_{mode}_{cab}.png")
        table_png(p, f"Wildberries · {cab} · {R['lab']}", "Aniq realizatsiya (so'm). Yakuniy = к перечислению − logistika − saqlash − obrabotka − jarima − ushlab. Qizil — zarar.", A["items"])
        pngs.append(p)
        album += [(u, f"WB {cab} · {c}") for u, c in album_of(A["items"])]
    if mode == "monthly":
        arch = R["archive"]
        if uz_month_tag:
            arch.setdefault("uzum", {})[uz_month_tag] = {k: round(v, 2) for k, v in uz_tot.items()}
        json.dump(arch, open(os.path.join(OUTD, "wb_archive.json"), "w"), ensure_ascii=False, indent=1)
        p = os.path.join(OUTD, "wb_monthly_charts.png")
        charts_monthly(R, arch.get("uzum"), p); pngs.insert(0, p)
        p = os.path.join(OUTD, "wb_monthly_taqqoslash.png")
        monthly_compare_png(R, arch.get("uzum"), p); pngs.insert(0, p)
    # rasmlar yuklanmagan bo'lsa (wbbasket.ru yopiq) — Telegram albom uchun URL ro'yxati
    ap = os.path.join(OUTD, "wb_album.json")
    if IMGSTAT["fail"] and not IMGSTAT["ok"] and album:
        json.dump(album[:20], open(ap, "w"), ensure_ascii=False)
    elif os.path.exists(ap):
        os.remove(ap)
    txt = text_of(R, uz_tot)
    json.dump({k: v for k, v in R.items() if k not in ("archive", "cabs")} | {"cabs_tot": {c: A["tot"] for c, A in R["cabs"].items()}},
              open(os.path.join(OUTD, f"wb_{mode}.json"), "w"), ensure_ascii=False, indent=1, default=str)
    open(os.path.join(OUTD, f"wb_{mode}.txt"), "w").write(txt)
    return R, txt, pngs

# ---------------------------------------------------------------- Telegram
def tg_album(album):
    """Rasmlarni Telegram o'zi URL'dan oladi (10 tadan). Xato bo'lsa jim o'tadi — qaytaradi: yuborilgan soni."""
    tok, chat = TG; n = 0
    for c0 in range(0, len(album), 10):
        part = album[c0:c0 + 10]
        media = [{"type": "photo", "media": u, "caption": c[:1000]} for u, c in part]
        try:
            if len(media) == 1:
                r = requests.post(f"https://api.telegram.org/bot{tok}/sendPhoto", data={"chat_id": chat, "photo": part[0][0], "caption": part[0][1]}, timeout=60)
            else:
                r = requests.post(f"https://api.telegram.org/bot{tok}/sendMediaGroup", data={"chat_id": chat, "media": json.dumps(media)}, timeout=90)
            if r.ok: n += len(part)
        except Exception:
            pass
    return n

def tg_send(text, pngs=(), album=None):
    tok, chat = TG
    if not tok or not chat: return "TELEGRAM: sozlanmagan"
    try:
        for p in pngs:
            r = requests.post(f"https://api.telegram.org/bot{tok}/sendPhoto", data={"chat_id": chat},
                              files={"photo": (os.path.basename(p), open(p, "rb"), "image/png")}, timeout=60)
            if not r.ok: raise Exception(f"HTTP {r.status_code} {r.text[:100]}")
        if album:
            tg_album(album)
        m = text
        while m:
            c = m.rfind("\n", 0, 4000) if len(m) > 4000 else len(m); c = c if c > 0 else 4000
            r = requests.post(f"https://api.telegram.org/bot{tok}/sendMessage", data={"chat_id": chat, "text": m[:c]}, timeout=30)
            if not r.ok: raise Exception(f"HTTP {r.status_code} {r.text[:100]}")
            m = m[c:].lstrip("\n")
        return "TELEGRAM: yuborildi"
    except Exception as x:
        return "TELEGRAM XATO: " + hide(x)[:150]

# ---------------------------------------------------------------- CLI
def main():
    a = sys.argv[1:]
    mode = a[0] if a else "daily"
    notg = "--no-tg" in a
    arg = lambda k: a[a.index(k) + 1] if k in a and a.index(k) + 1 < len(a) else None
    if mode == "album":   # haftalik/oylik: rasm serveri yopiq bo'lsa, uzum_report deliver'dan keyin tovar rasmlari albomi
        ap = os.path.join(OUTD, "wb_album.json")
        if not os.path.exists(ap): print("WB ALBOM: kerak emas (rasmlar hisobot ichida)"); return
        print(f"WB ALBOM: {tg_album([tuple(x) for x in json.load(open(ap))])} ta rasm yuborildi"); return
    if not TOK:
        print("WB: kalitlar muhitda topilmadi (WB_CLEO, WB_NASIROV)"); return
    os.makedirs(OUTD, exist_ok=True)
    pngs = []
    if mode == "dash":
        o = run_dash()
        print(f"WB DASH: ~/dash/wb.json · {len(o['rows'])} qator, {len(o['items'])} tovar, rasm {len(o['imgs'])}, kurs {o['rate']}"
              + ("" if not o["errors"] else " | XATO: " + "; ".join(f"{c}: {e}" for c, e in o["errors"].items())))
        return
    if mode == "weekly":
        d0 = dt.date.fromisoformat(arg("--from")) if arg("--from") else None
        d1 = dt.date.fromisoformat(arg("--to")) if arg("--to") else None
        R, txt, pngs = integrate("weekly", None, d0=d0, d1=d1)
    elif mode == "monthly":
        R, txt, pngs = integrate("monthly", None)
    elif mode == "hourly":
        R = run_hourly(); txt = text_of(R)
        json.dump(R, open(os.path.join(OUTD, "wb_hourly.json"), "w"), ensure_ascii=False, indent=1, default=str)
    else:
        R = run_daily(dt.date.fromisoformat(arg("--date")) + dt.timedelta(days=1) if arg("--date") else None)
        uzp = os.path.join(H, "uzum_daily.json")
        uz = json.load(open(uzp)) if os.path.exists(uzp) else None
        txt = text_of(R, uz)
        album = []
        for cab, A in R["cabs"].items():
            if A["items"]:
                T_ = A["tot"]
                p = os.path.join(OUTD, f"wb_daily_{cab}.png")
                cards_png(p, f"Wildberries · {cab} · {R['lab']}",
                          f"sotuv {S(T_['sotuv'])} · {F(T_['soni'] - T_['vozvrat'])} dona · ~foyda {S(T_['foyda'])}  (₽ × {R.get('rate') or 0:.1f}; foyda ~ o'tgan hafta rasxod ulushidan)",
                          A["items"], approx=True, n=20)
                pngs.append(p)
                album += [(u, f"WB {cab} · {c}") for u, c in album_of(A["items"], approx=True)]
        if IMGSTAT["fail"] and not IMGSTAT["ok"]:
            R["album"] = album[:20]
        json.dump({k: v for k, v in R.items() if k != "cabs"} | {"cabs_tot": {c: A["tot"] for c, A in R["cabs"].items()},
                   "cabs_prev": {c: A.get("prev", {}) for c, A in R["cabs"].items()}, "cabs_orders": {c: A.get("orders") for c, A in R["cabs"].items()}},
                  open(os.path.join(OUTD, "wb_daily.json"), "w"), ensure_ascii=False, indent=1, default=str)
        open(os.path.join(OUTD, "wb_daily.txt"), "w").write(txt)
        # kunlik Uzum fayllariga qo'shish (Obsidian va Gmail zaxirasi uchun)
        for fn, wrap in (("daily.txt", lambda s: "\n\n" + s + "\n"), ("report.md", lambda s: "\n## Wildberries\n\n```\n" + s + "\n```\n")):
            if os.path.exists(os.path.join(H, fn)):
                open(os.path.join(H, fn), "a").write(wrap(txt))
    st = "TELEGRAM: o'tkazib yuborildi (--no-tg)" if notg else (tg_send(txt, pngs, R.get("album")) if mode in ("daily", "hourly") else "TELEGRAM: uzum_report deliver orqali")
    T = wb_totals(R) if mode != "hourly" else None
    print(st)
    print("WB QISQA: " + (" | ".join(f"{c}: {A['orders']} buyurtma" for c, A in R["cabs"].items()) if mode == "hourly" else
                          " | ".join(f"{c}: sotuv {S(A['tot']['sotuv'])}, {'~' if mode == 'daily' else ''}foyda {S(A['tot']['foyda'])}" for c, A in R["cabs"].items()))
          + ("" if not R.get("errors") else " | XATO: " + "; ".join(f"{c}: {e}" for c, e in R["errors"].items())))
    print(txt)

if __name__ == "__main__":
    main()
