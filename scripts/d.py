#!/usr/bin/env python3
# Uzum KUNLIK hisobot v5 (v4 + ~/uzum_daily.json — WB hisobotidagi umumiy jami uchun): SKU jadvali (kamdan ko'pga), o'z ostatka hisobi vs Uzum, vozvrat sabablari,
# do'kon bo'yicha yig'ilayotgan sof summa, kamayayotgan variantlar signali.
# Kirish:  kalitlar env (UZUM_SA_TIMSON, UZUM_CLEO, TG_TOKEN, TG_CHAT) yoki ~/uzum_key.txt
#          ~/state.json (oldingi kun holati, bo'lmasa — birinchi ishga tushirish), ~/tannarx.csv (ixtiyoriy)
# Chiqish: ~/state_new.json, ~/daily.png, ~/daily.txt, ~/report.md ; Telegram'ga rasm + matn
# Ishlatish: python3 d.py [--no-tg]
import os, io, re, sys, csv, json, math, time, textwrap, collections, datetime as dt, requests

H = os.path.expanduser("~")
B = "https://api-seller.uzum.uz/api/seller-openapi"
TZ = dt.timezone(dt.timedelta(hours=5))
ALERT_DAYS = 14          # shundan kam kunga yetadigan variant -> signal
TOL = 0                  # ostatka farqiga ruxsat (dona)
AD_WORDS = ("реклам", "продвиж", "буст", "boost", "reklam", "promo", "маркетинг", "marketing", "advert")

# ------------------------------------------------------------ sozlamalar
keys, cfg = [], {}
ENV = [("SA & Timson", "UZUM_SA_TIMSON"), ("CLEO", "UZUM_CLEO"), ("TG_TOKEN", "TG_TOKEN"), ("TG_CHAT", "TG_CHAT")]
lines = [f"{n}:{os.environ[v]}" for n, v in ENV if os.environ.get(v)]
SRC = "env"
if not any(not n.startswith("TG") for n, v in ENV if os.environ.get(v)) and os.path.exists(os.path.join(H, "uzum_key.txt")):
    lines = open(os.path.join(H, "uzum_key.txt")).read().splitlines(); SRC = "fayl"
for l in lines:
    n, sep, k = l.strip().partition(":")
    if not sep or not k.strip() or n.strip().startswith("#"):
        continue
    if n.strip().upper().startswith("TG_"):
        cfg[n.strip().upper()] = k.strip()
    else:
        keys.append((n.strip(), k.strip()))

def hide(s):
    s = str(s)
    for _, k in keys:
        s = s.replace(k, "***")
    t = cfg.get("TG_TOKEN")
    return s.replace(t, "***") if t else s

class Err(Exception):
    pass

def g(K, p, q):
    e = ""
    for a in range(7):   # sekin/uzilgan javobda kutib qayta urinadi (~3 daqiqa)
        try:
            r = requests.get(B + p, headers={"Authorization": K}, params=q, timeout=(15, 90))
            if r.ok:
                return r.json()
            e = f"HTTP {r.status_code} {r.text[:120]}"
            if r.status_code in (401, 403, 404):
                break
        except Exception as x:
            e = str(x)[:120]
        if a < 6:
            time.sleep([3, 6, 12, 20, 30, 45][a])
    raise Err(f"{p}: {e}")

def pages(K, p, q, f, maxp=200):
    o, n = [], 0
    while True:
        it = f(g(K, p, {**q, "size": 100, "page": n})) or []
        o += it
        if len(it) < 100 or n > maxp:
            return o
        n += 1

ms = lambda d: int(d.timestamp() * 1000)
F = lambda n: f"{int(round(n or 0)):,}".replace(",", " ")
def S(n):
    a = abs(n or 0)
    if a >= 1e6: return f"{n/1e6:.1f} mln".replace(".", ",")
    if a >= 1e3: return f"{n/1e3:.0f} ming"
    return f"{n:.0f}"
cut = lambda x, n: x if len(x) <= n else x[:n - 1] + "…"

now = dt.datetime.now(TZ)
t0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
ys, ye = t0 - dt.timedelta(days=1), t0                      # hisobot kuni (kecha)

# ------------------------------------------------------------ holat
sp = os.path.join(H, "state.json")
ST = json.load(open(sp)) if os.path.exists(sp) else {}
FIRST = not ST.get("shops")
ST.setdefault("start", f"{t0:%Y-%m-%d}")
ST.setdefault("shops", {})

# ------------------------------------------------------------ tannarx (Google Sheets CSV)
def num(c):
    c = re.sub(r"[\s\xa0']", "", c or "").replace("so'm", "")
    if re.fullmatch(r"-?\d{1,3}(,\d{3})+(\.\d+)?", c):
        c = c.replace(",", "")
    try:
        return float(c.replace(",", "."))
    except ValueError:
        return None
TN, VN = {}, {}
p = os.path.join(H, "tannarx.csv")
if os.path.exists(p):
    rows = list(csv.reader(open(p, encoding="utf-8-sig")))
    if rows:
        hd = [h.lower() for h in rows[0]]
        iu = next((i for i, h in enumerate(hd) if "uzum" in h and "tannarx" in h), 3)
        iy = next((i for i, h in enumerate(hd) if "sizning" in h), 4)
        iv = next((i for i, h in enumerate(hd) if "variant" in h), 2)
        for r in rows[1:]:
            if not r or not r[0].strip():
                continue
            v = (num(r[iy]) if len(r) > iy else None) or (num(r[iu]) if len(r) > iu else None)
            if v and v > 0:
                TN[r[0].strip()] = v
            if len(r) > iv and r[iv].strip():
                VN[r[0].strip()] = r[iv].strip()

def article(code):
    pr = (code or "").split("-")
    return pr[1] if len(pr) > 1 else (code or "?")

# ------------------------------------------------------------ nakladnoy yordamchilari (maydon nomlari moslashuvchan)
def _first_list(js):
    if isinstance(js, list):
        return js if (not js or isinstance(js[0], dict)) else []
    if isinstance(js, dict):
        for k in ("payload", "data", "result", "items", "content", "invoices", "returns", "list", "products"):
            v = js.get(k)
            if isinstance(v, list):
                return v
            if isinstance(v, dict):
                r = _first_list(v)
                if r:
                    return r
        for v in js.values():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                return v
    return []

def _to_dt(v):
    try:
        if isinstance(v, (int, float)) and v > 1e9:
            return dt.datetime.fromtimestamp(v / 1000 if v > 1e11 else v, TZ)
        if isinstance(v, str) and len(v) >= 10 and v[4] == "-":
            d = dt.datetime.fromisoformat(v.replace("Z", "+00:00")[:26])
            return d if d.tzinfo else d.replace(tzinfo=TZ)
    except Exception:
        return None

def _date_of(d):
    for k in ("dateAccepted", "acceptedDate", "dateReceived", "receivedDate", "dateDelivered", "dateCompleted", "dateUpdated", "dateCreated", "createdAt", "date"):
        if k in d:
            x = _to_dt(d[k])
            if x:
                return x
    return None

def _qty(d, accepted=True):
    ks = ("quantityAccepted", "acceptedQuantity", "acceptedAmount", "quantityReceived", "receivedQuantity", "quantity", "amount", "count", "qty") if accepted \
        else ("quantity", "amount", "count", "qty", "quantityReturned", "returnedQuantity")
    for k in ks:
        v = d.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return v
    return 0

def _sku(d):
    for k in ("skuTitle", "skuFullTitle", "sku", "article", "barcode"):
        v = d.get(k)
        if isinstance(v, str) and v:
            return ("t", v)
    for k in ("skuId", "skuID"):
        if d.get(k) is not None:
            return ("i", d[k])
    return (None, None)

def moves(K, sid, since, until, seen):
    """Uzum qabul qilgan postavkalar (+) va sotuvchiga qaytarilgan (−) dona. seen: allaqachon hisoblangan hujjatlar."""
    sup, back, docs, err = [], [], [], []
    try:
        inv = []
        for pg in range(20):
            lst = _first_list(g(K, f"/v1/shop/{sid}/invoice", {"page": pg, "size": 100}))
            inv += lst
            if len(lst) < 100:
                break
        for iv in inv:
            st = str(iv.get("status") or iv.get("invoiceStatus") or "").upper()
            iid = iv.get("id") or iv.get("invoiceId")
            key = f"inv{sid}:{iid}"
            if key in seen or not any(w in st for w in ("ACCEPT", "DONE", "COMPLET", "RECEIV", "CLOSED")):
                continue
            d = _date_of(iv)
            if not d or d < since - dt.timedelta(days=3) or d >= until:
                continue
            items = _first_list(g(K, f"/v1/shop/{sid}/invoice/products", {"invoiceId": iid}))
            for it in items:
                sup.append((_sku(it), _qty(it)))
            docs.append(key)
    except Exception as x:
        err.append(f"postavka: {hide(x)[:100]}")
    try:
        rl = []
        for pg in range(20):
            lst = _first_list(g(K, f"/v1/shop/{sid}/return", {"page": pg, "size": 100}))
            rl += lst
            if len(lst) < 100:
                break
        for rv in rl:
            rid = rv.get("id") or rv.get("returnId")
            key = f"ret{sid}:{rid}"
            st = str(rv.get("status") or "").upper()
            if key in seen or (st and any(w in st for w in ("CANCEL", "DRAFT"))):
                continue
            d = _date_of(rv)
            if not d or d < since - dt.timedelta(days=3) or d >= until:
                continue
            items = _first_list(g(K, f"/v1/shop/{sid}/return/{rid}", {}))
            for it in items:
                back.append((_sku(it), _qty(it, False)))
            docs.append(key)
    except Exception as x:
        err.append(f"qaytarish: {hide(x)[:100]}")
    return sup, back, docs, err

# ------------------------------------------------------------ asosiy hisob
ROWS, SHOPS, ALERTS, ERRS = [], [], [], []
for nm, K in keys:
    ss = ST["shops"].setdefault(nm, {})
    first = not ss.get("ledger")
    sh = dict(name=nm, err=None)
    try:
        ids = [x["id"] for x in g(K, "/v1/shops", {})]
        PR = []
        for sid in ids:
            PR += pages(K, f"/v1/product/shop/{sid}", {}, lambda r: r.get("productList"))
        since_ts = ss.get("ts") or ms(now)
        since = dt.datetime.fromtimestamp(since_ts / 1000, TZ)
        acc_from = dt.datetime.fromisoformat(ss["acc_day"]).replace(tzinfo=TZ) if ss.get("acc_day") else ys
        o_from = min(t0 - dt.timedelta(days=30), since, acc_from)
        OA = pages(K, "/v1/finance/orders", {"shopIds": ids, "dateFrom": ms(o_from), "dateTo": ms(now), "group": "false"}, lambda r: r.get("orderItems"))
        XA = pages(K, "/v1/finance/expenses", {"shopIds": ids, "dateFrom": ms(min(acc_from, ys)), "dateTo": ms(t0)}, lambda r: (r.get("payload") or {}).get("payments"))
    except Err as x:
        sh["err"] = hide(x)[:150]; SHOPS.append(sh); ERRS.append(f"{nm}: {sh['err']}")
        continue

    # SKU ma'lumotnomasi
    SK, id2c = {}, {}
    for p_ in PR:
        for k in p_.get("skuList") or []:
            c = k["skuFullTitle"]
            fbo = (k.get("quantityAvailableByStockType") or {}).get("fbo", k.get("quantityActive") or 0) or 0
            SK[c] = dict(title=p_["title"], var=VN.get(c) or (k.get("characteristics") or "").strip() or k.get("skuTitle") or c,
                         fbo=max(0, fbo), fbs=max(0, k.get("quantityFbs") or 0), archived=bool(k.get("archived")))
            if k.get("skuId") is not None:
                id2c[k["skuId"]] = c
    fbo_mode = any(v["fbo"] > 0 for v in SK.values())
    stock_of = lambda c: (SK[c]["fbo"] if fbo_mode else SK[c]["fbs"]) if c in SK else 0
    lab = lambda c, o=None: (SK[c]["var"] if c in SK else VN.get(c) or (c or "").split("-")[-1])
    ttl = lambda c, o=None: SK[c]["title"] if c in SK else (o or {}).get("productTitle", "")

    # ---- kechagi savdo (jadval uchun)
    Y = [o for o in OA if ms(ys) <= o["date"] < ms(ye)]
    sold = [o for o in Y if o["status"] != "CANCELED" and o["amount"] > 0]
    for o in sold:
        c = o.get("skuTitle")
        cost = TN.get(c) or o.get("purchasePrice") or 0
        ROWS.append(dict(shop=nm, art=article(c), code=c, title=ttl(c, o), var=lab(c, o), q=o["amount"], rev=o["sellPrice"] * o["amount"],
                         pay=o["sellerProfit"], com=o.get("commission") or 0, log=o.get("logisticDeliveryFee") or 0, cost=cost * o["amount"]))
    canc = [o for o in Y if o["status"] == "CANCELED"]

    # ---- har bir buyurtma qatori kuzatuvi (bekor/vozvrat keyin bo'lsa ham tutish uchun)
    seen_items = ss.get("items", {})          # id -> [counted_qty, returns_counted, canceled_flag, unit_profit, date]
    sold_win, ret_win, canc_win = collections.Counter(), collections.Counter(), collections.Counter()
    RETS = []                                  # yangi aniqlangan vozvratlar
    profit_adj = 0.0
    new_items = {}
    for o in OA:
        iid = str(o.get("id") or f"{o.get('orderId')}:{o.get('skuTitle')}")
        c = o.get("skuTitle")
        prev = seen_items.get(iid)
        a, rr, cn = o["amount"], o.get("amountReturns") or 0, o["status"] == "CANCELED"
        unit = (o["sellerProfit"] / a) if a else 0
        if prev is None:
            if o["date"] >= since_ts and not first:
                if not cn:
                    sold_win[c] += a
                if rr:
                    ret_win[c] += rr
                    RETS.append((nm, c, rr, o))
            new_items[iid] = [a, rr, int(cn), unit, o["date"]]
        else:
            pa, pr, pc, pu, pdate = prev
            if cn and not pc and not first:
                canc_win[c] += pa - pr               # sotilgan deb hisoblangan edi -> skladga qaytdi
                if o["date"] < ms(ys):               # oldingi kunlarda summaga qo'shilgan edi
                    profit_adj -= pu * (pa - pr)
            if rr > pr and not first:
                ret_win[c] += rr - pr
                RETS.append((nm, c, rr - pr, o))
                if o["date"] < ms(ys):               # oldingi kunlardagi sotuv -> yig'ilgan summadan ayiramiz
                    profit_adj -= pu * (rr - pr)
            new_items[iid] = [a, rr, int(cn), unit, o["date"]]
    # 35 kundan eskilarini saqlamaymiz
    lim = ms(t0 - dt.timedelta(days=35))
    ss["items"] = {k: v for k, v in new_items.items() if v[4] >= lim}

    # ---- postavka / sotuvchiga qaytarish nakladnoylari
    sup_c, back_c = collections.Counter(), collections.Counter()
    seen_docs = set(ss.get("docs", []))
    mv_err = []
    if not first:
        for sid in ids:
            sup, back, docs, err = moves(K, sid, since, now, seen_docs)
            key = lambda s: id2c.get(s[1], str(s[1])) if s[0] == "i" else s[1]
            for s_, q in sup:
                sup_c[key(s_)] += q
            for s_, q in back:
                back_c[key(s_)] += q
            seen_docs |= set(docs); mv_err += err
    else:
        for sid in ids:   # birinchi marta: mavjud hujjatlarni "ko'rilgan" deb belgilaymiz
            _, _, docs, err = moves(K, sid, now - dt.timedelta(days=60), now, set())
            seen_docs |= set(docs); mv_err += err
    ss["docs"] = sorted(seen_docs)[-2000:]
    if mv_err:
        ERRS += [f"{nm} {e}" for e in mv_err]

    # ---- o'z ostatka hisobi
    led = ss.get("ledger", {})
    prev_diff = ss.get("diff", {})
    new_led, diff, lost, extra = {}, {}, [], []
    codes = set(SK) | set(led)
    for c in codes:
        u = stock_of(c)
        if first or c not in led:
            new_led[c] = u
            continue
        exp = led[c] - sold_win[c] + canc_win[c] + ret_win[c] + sup_c[c] - back_c[c]
        new_led[c] = exp
        d = u - exp
        if abs(d) > TOL:
            diff[c] = d
            if d != prev_diff.get(c, 0):
                (lost if d < prev_diff.get(c, 0) else extra).append((c, exp, u, d - prev_diff.get(c, 0), d))
    ss["ledger"] = new_led
    ss["diff"] = diff
    ss["ts"] = ms(now)

    # ---- kamayayotgan variantlar (30 kunlik tezlik)
    s30 = collections.Counter()
    for o in OA:
        if o["date"] >= ms(t0 - dt.timedelta(days=30)) and o["status"] != "CANCELED" and o["amount"] > 0:
            s30[o.get("skuTitle")] += o["amount"]
    low = []
    for c, k in SK.items():
        if k["archived"] or s30[c] < 3:
            continue
        st = stock_of(c); avg = s30[c] / 30; days = st / avg if avg else math.inf
        if days < ALERT_DAYS:
            low.append(dict(code=c, art=article(c), var=k["var"], title=k["title"], stock=st, avg=avg, days=days, need=max(0, math.ceil(avg * 30 - st))))
    low.sort(key=lambda z: (z["days"], -z["avg"]))

    # ---- pul: kecha va start kunidan beri yig'ilgan sof summa
    def is_ad(x):
        s_ = (x.get("source") or "").lower() + " " + (x.get("name") or x.get("description") or "").lower()
        return any(w in s_ for w in AD_WORDS)
    ad_y = sum(x["paymentPrice"] * (-1 if x.get("type") == "INCOME" else 1) for x in XA if is_ad(x) and ms(ys) <= (x.get("dateService") or x.get("dateCreated") or 0) < ms(ye))
    rev_y = sum(o["sellPrice"] * o["amount"] for o in sold)
    com_y = sum(o.get("commission") or 0 for o in sold)
    log_y = sum(o.get("logisticDeliveryFee") or 0 for o in sold)
    ret_y = sum((o.get("amountReturns") or 0) * o["sellPrice"] for o in Y)
    # kechagi sof: sotilgan (qaytmaganlari) bo'yicha sellerProfit (= tushum − komissiya − logistika) − reklama
    net_y = sum(o["sellerProfit"] * (o["amount"] - (o.get("amountReturns") or 0)) / o["amount"] for o in sold if o["amount"]) - ad_y
    cost_y = sum(r["cost"] for r in ROWS if r["shop"] == nm)
    _pd = [o for o in OA if ms(ys - dt.timedelta(days=1)) <= o["date"] < ms(ys) and o["status"] != "CANCELED" and o["amount"] > 0]
    prev_rev = sum(o["sellPrice"] * o["amount"] for o in _pd); prev_q = sum(o["amount"] for o in _pd)

    acc = ss.get("acc", 0.0)
    acc_day = ss.get("acc_day")   # oxirgi qo'shilgan kun
    if acc_day != f"{ys:%Y-%m-%d}":
        # o'tkazib yuborilgan kunlar bo'lsa, ularni ham qo'shamiz
        d0 = (dt.datetime.fromisoformat(acc_day).replace(tzinfo=TZ) + dt.timedelta(days=1)) if acc_day else ys
        add = 0.0
        for o in OA:
            if ms(d0) <= o["date"] < ms(ye) and o["status"] != "CANCELED" and o["amount"] > 0:
                add += o["sellerProfit"] * (o["amount"] - (o.get("amountReturns") or 0)) / o["amount"]
        add -= sum(x["paymentPrice"] * (-1 if x.get("type") == "INCOME" else 1) for x in XA if is_ad(x) and ms(d0) <= (x.get("dateService") or x.get("dateCreated") or 0) < ms(ye))
        acc += add
        ss["acc_day"] = f"{ys:%Y-%m-%d}"
    acc += profit_adj                         # avvalgi kunlar sotuvidan keyin bo'lgan vozvrat/bekor -> ayiriladi
    ss["acc"] = acc
    ad_src = sorted({x.get("source") or "?" for x in XA if is_ad(x)})

    sh.update(prev_rev=prev_rev, prev_q=prev_q, ret_new=sum(q for _, _, q, _ in RETS), ret_new_s=sum(q * o["sellPrice"] for _, _, q, o in RETS), rev=rev_y, com=com_y, log=log_y, ad=ad_y, net=net_y, cost=cost_y, sold=sum(o["amount"] for o in sold),
              orders=len({o["orderId"] for o in sold}), canc=len(canc), ret_q=sum(o.get("amountReturns") or 0 for o in Y), ret_s=ret_y,
              acc=acc, start=ST["start"], low=low, lost=lost, extra=extra, diff=diff, RETS=RETS, first=first, fbo=fbo_mode,
              sup=sum(sup_c.values()), back=sum(back_c.values()), ad_src=ad_src, lab=lab, ttl=ttl)
    SHOPS.append(sh)
    for c, exp, u, dd, tot in lost:
        ALERTS.append(f"🔴 {nm}: {article(c)} — {lab(c)}: hisob bo'yicha {exp}, Uzum'da {u} → {dd:+d} dona yo'qolgan")
    for c, exp, u, dd, tot in extra:
        ALERTS.append(f"🟡 {nm}: {article(c)} — {lab(c)}: hisob bo'yicha {exp}, Uzum'da {u} → {dd:+d} dona ortiq (ostatka o'ynadi)")

ST["ts"] = ms(now)
json.dump(ST, open(os.path.join(H, "state_new.json"), "w"), ensure_ascii=False, separators=(",", ":"))
# Wildberries / "Barcha marketplace'lar jami" uchun kechagi Uzum jami (wb_report.py daily o'qiydi)
_ok = [s_ for s_ in SHOPS if not s_.get("err")]
json.dump(dict(date=f"{ys:%Y-%m-%d}", sales=sum(s_["rev"] for s_ in _ok), payout=sum(s_["net"] for s_ in _ok), cost=sum(s_["cost"] for s_ in _ok),
               profit=sum(s_["net"] - s_["cost"] for s_ in _ok),
               shops=[dict(name=s_["name"], err=s_.get("err"), rev=s_.get("rev", 0), qty=s_.get("sold", 0), orders=s_.get("orders", 0),
                           ret_q=s_.get("ret_new", 0), ret_s=s_.get("ret_new_s", 0), canc=s_.get("canc", 0), net=s_.get("net", 0), cost=s_.get("cost", 0),
                           prev_rev=s_.get("prev_rev", 0), prev_q=s_.get("prev_q", 0)) for s_ in SHOPS]), open(os.path.join(H, "uzum_daily.json"), "w"))

# ------------------------------------------------------------ jadval: artikul bo'yicha, KAMDAN KO'PGA
G = {}
for r in ROWS:
    k = (r["shop"], r["art"])
    a = G.setdefault(k, dict(shop=r["shop"], art=r["art"], title=r["title"], vars=collections.Counter(), q=0, rev=0, pay=0, cost=0, nocost=False))
    a["vars"][r["var"]] += r["q"]; a["q"] += r["q"]; a["rev"] += r["rev"]; a["pay"] += r["pay"]; a["cost"] += r["cost"]
    if not r["cost"]:
        a["nocost"] = True
TBL = sorted(G.values(), key=lambda a: (a["q"], a["rev"]))

def table_png(path):
    from PIL import Image, ImageDraw, ImageFont
    fp = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"; fb = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    f = ImageFont.truetype(fp, 15); fB = ImageFont.truetype(fb, 15); fs = ImageFont.truetype(fp, 12); fT = ImageFont.truetype(fb, 20)
    cols = [("SKU — kartochka", 600, "l"), ("Soni", 70, "r"), ("Tushum", 125, "r"), ("To'lovga", 125, "r"), ("Sof", 115, "r"), ("ROI", 85, "r")]
    W = sum(c[1] for c in cols) + 40; rh = 48
    Hh = 100 + rh * (len(TBL) + 1) + 30
    im = Image.new("RGB", (W, Hh), "#f7f7fa"); d = ImageDraw.Draw(im)
    d.text((20, 20), f"Kunlik hisobot — {ys:%d.%m.%Y}", font=fT, fill="#17161c")
    d.text((20, 50), "Artikul bo'yicha, kamdan ko'pga. To'lovga = tushum − komissiya − logistika. Sof = to'lovga − tannarx. ROI = sof / tannarx.", font=fs, fill="#6b6975")
    y = 78; x = 20
    d.rectangle((20, y, W - 20, y + 30), fill="#ececf1")
    for n, w, a in cols:
        tw = d.textlength(n, font=fB); d.text((x + w - tw - 10 if a == "r" else x + 8, y + 7), n, font=fB, fill="#17161c"); x += w
    y += 30
    def row(vals, bold=False, shade=False):
        nonlocal y
        d.rectangle((20, y, W - 20, y + rh), fill="#ffffff" if not shade else "#fbfbfd")
        x = 20
        for (n, w, a), v in zip(cols, vals):
            fo = fB if bold else f
            if isinstance(v, tuple):
                d.text((x + 8, y + 6), v[0], font=fB, fill="#17161c"); d.text((x + 8, y + 27), v[1], font=fs, fill="#77757f")
            else:
                col = "#17161c"
                if isinstance(v, str) and v.startswith("-"): col = "#c2372f"
                elif n == "ROI" and v not in ("—", ""): col = "#2e7d32"
                tw = d.textlength(v, font=fo); d.text((x + w - tw - 10 if a == "r" else x + 8, y + 15), v, font=fo, fill=col)
            x += w
        y += rh; d.line((20, y, W - 20, y), fill="#e4e3ea")
    for i, a in enumerate(TBL):
        n = a["pay"] - a["cost"]
        roi = "—" if a["nocost"] or not a["cost"] else f"{n / a['cost'] * 100:.1f}%"
        vs = ", ".join(f"{v} {q}" if len(a["vars"]) > 1 else v for v, q in a["vars"].most_common())
        row([(f"{a['art']} — {cut(vs, 50)}", cut(f"{a['shop']} · {a['title']}", 80)), F(a["q"]), F(a["rev"]), F(a["pay"]),
             F(n) if not a["nocost"] else "—", roi], shade=i % 2)
    tq = sum(a["q"] for a in TBL); tr = sum(a["rev"] for a in TBL); tp = sum(a["pay"] for a in TBL); tc = sum(a["cost"] for a in TBL)
    nc = any(a["nocost"] for a in TBL)
    row([("Jami:", "tannarxi yo'q SKU bor — Sof/ROI to'liq emas" if nc else ""), F(tq), F(tr), F(tp), F(tp - tc) if tc else "—", f"{(tp - tc) / tc * 100:.1f}%" if tc else "—"], bold=True)
    im = im.crop((0, 0, W, y + 20)); im.save(path)

# ------------------------------------------------------------ matn
L = [f"UZUM KUNLIK HISOBOT — {ys:%d.%m.%Y}", ""]
ok = [s for s in SHOPS if not s.get("err")]
L.append("💰 PUL (kecha) va START KUNIDAN BERI YIG'ILGAN SOF SUMMA")
for s in ok:
    L.append(f"• {s['name']}: savdo {F(s['rev'])} − komissiya {F(s['com'])} − logistika {F(s['log'])}" + (f" − reklama {F(s['ad'])}" if s["ad"] else "")
             + f" = {F(s['net'] + 0)} so'm sof | yig'ilgan ({s['start']} dan): {F(s['acc'])} so'm")
if len(ok) > 1:
    L.append(f"• JAMI: kecha {F(sum(s['net'] for s in ok))} so'm | yig'ilgan: {F(sum(s['acc'] for s in ok))} so'm")
for s in SHOPS:
    if s.get("err"):
        L.append(f"• {s['name']}: XATO {s['err']}")
L += ["", "📦 OSTATKA NAZORATI (o'z hisobim vs Uzum skladi)"]
if any(s.get("first") for s in ok):
    L.append("  Birinchi ishga tushirish: hozirgi Uzum ostatkasi boshlang'ich qoldiq sifatida yozib olindi. Farqlar ertadan boshlab tekshiriladi.")
if ALERTS:
    L += ["  " + a for a in ALERTS[:40]] + (["  … yana " + str(len(ALERTS) - 40)] if len(ALERTS) > 40 else [])
    L.append("  ⚠ Yo'qolgan tovar bo'yicha Uzum'ga murojaat qiling (artikul, variant va farq yuqorida).")
elif not any(s.get("first") for s in ok):
    L.append("  Farq yo'q — hisob Uzum ostatkasi bilan mos.")
for s in ok:
    old = {c: v for c, v in s["diff"].items()} if s["diff"] else {}
    if old and not (s["lost"] or s["extra"]):
        L.append(f"  {s['name']}: avvaldan ochiq farqlar {len(old)} variantda (jami {sum(old.values()):+d} dona) — hal qilinmagan")
    if s["sup"] or s["back"]:
        L.append(f"  {s['name']}: Uzum qabul qilgan postavka +{s['sup']} dona" + (f", sizga qaytarilgan −{s['back']} dona" if s['back'] else ""))
L += ["", f"📉 KAMAYAYOTGAN VARIANTLAR ({ALERT_DAYS} kundan kam qoldi)"]
anylow = False
for s in ok:
    for z in s["low"][:20]:
        anylow = True
        dd = "tugagan" if z["stock"] == 0 else f"{z['days']:.0f} kunga"
        L.append(f"  {'🔴' if z['days'] < 7 else '🟡'} {s['name']}: {z['art']} — {z['var']}: qoldiq {z['stock']}, kuniga {z['avg']:.1f} → {dd} | 30 kunga olib borish: {z['need']} dona")
if not anylow:
    L.append("  Hammasi yetarli")
L += ["", "↩️ VOZVRATLAR (yangi aniqlangan)"]
anyret = False
for s in ok:
    for nm, c, q, o in s["RETS"]:
        anyret = True
        why = (o.get("returnCause") or "Sabab ko'rsatilmagan") + (f" ({o['comment'].strip()})" if o.get("comment") else "")
        L.append(f"  • {nm}: {article(c)} — {s['lab'](c)}: {q} dona, {F(q * o['sellPrice'])} so'm — {why} (buyurtma {o['date'] and dt.datetime.fromtimestamp(o['date']/1000, TZ):%d.%m})")
if not anyret:
    L.append("  Yo'q")
canc = sum(s["canc"] for s in ok)
if canc:
    L.append(f"  Kecha bekor qilingan buyurtma qatorlari: {canc}")
for s in ok:
    if s["ad_src"]:
        L.append(f"  ({s['name']} reklama manbalari: {', '.join(s['ad_src'])})")
if ERRS:
    L += ["", "⚠ XATOLAR: " + "; ".join(ERRS)[:600]]
text = "\n".join(L)
open(os.path.join(H, "daily.txt"), "w").write(text)

# Obsidian markdown
roi_s = lambda a: "—" if a["nocost"] or not a["cost"] else f"{(a['pay'] - a['cost']) / a['cost'] * 100:.1f}%"
md = [f"---\ntur: uzum-kunlik\nsana: {ys:%Y-%m-%d}\ndokonlar: [{', '.join(s['name'] for s in SHOPS)}]\n---", f"# Uzum kunlik hisobot — {ys:%d.%m.%Y}", "",
      "## Sotuv (artikul bo'yicha, kamdan ko'pga)", "", "| SKU | Variantlar | Do'kon | Soni | Tushum | To'lovga | Sof | ROI |", "|---|---|---|--:|--:|--:|--:|--:|"]
for a in TBL:
    n = a["pay"] - a["cost"]
    md.append(f"| {a['art']} | {', '.join(f'{v} {q}' for v, q in a['vars'].most_common())} | {a['shop']} | {a['q']} | {F(a['rev'])} | {F(a['pay'])} | {F(n) if not a['nocost'] else '—'} | {roi_s(a)} |")
md += ["", "## Signallar va pul", "", "```", text, "```"]
open(os.path.join(H, "report.md"), "w").write("\n".join(md) + "\n")

if TBL:
    table_png(os.path.join(H, "daily.png"))

# ------------------------------------------------------------ Telegram
out = "TELEGRAM: sozlanmagan"
if cfg.get("TG_TOKEN") and "--no-tg" not in sys.argv:
    try:
        tok, chat = cfg["TG_TOKEN"], cfg.get("TG_CHAT")
        if TBL:
            r = requests.post(f"https://api.telegram.org/bot{tok}/sendPhoto", data={"chat_id": chat, "caption": f"Uzum — {ys:%d.%m.%Y}: {sum(a['q'] for a in TBL)} dona, {F(sum(a['rev'] for a in TBL))} so'm"},
                              files={"photo": ("t.png", open(os.path.join(H, "daily.png"), "rb"), "image/png")}, timeout=60)
            if not r.ok:
                raise Exception(f"HTTP {r.status_code} {r.text[:100]}")
        m = text
        while m:
            c = m.rfind("\n", 0, 4000) if len(m) > 4000 else len(m)
            c = c if c > 0 else 4000
            r = requests.post(f"https://api.telegram.org/bot{tok}/sendMessage", data={"chat_id": chat, "text": m[:c]}, timeout=30)
            if not r.ok:
                raise Exception(f"HTTP {r.status_code} {r.text[:100]}")
            m = m[c:].lstrip("\n")
        out = "TELEGRAM: yuborildi"
    except Exception as x:
        out = "TELEGRAM XATO: " + hide(x)[:150]

# Qisqa xulosa (push uchun)
short = [f"{s['name']}: kecha sof {S(s['net'])}, yig'ilgan {S(s['acc'])}" if not s.get("err") else f"{s['name']}: XATO" for s in SHOPS]
print(f"MAVZU: Uzum kunlik hisobot — {', '.join(s['name'] for s in SHOPS)} — {ys:%d.%m.%Y}")
print(out)
print("QISQA: " + " | ".join(short) + (f" | ⚠ ostatka farqi: {len(ALERTS)}" if ALERTS else "") + (f" | 📉 kam qolgan: {sum(len(s['low']) for s in ok)}" if any(s['low'] for s in ok) else ""))
print(f"KALITLAR: {SRC}")
print(text)
