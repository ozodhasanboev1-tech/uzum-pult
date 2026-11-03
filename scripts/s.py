#!/usr/bin/env python3
# Uzum PULLIK SAQLASH signali: Uzum skladida (FBO) pul yeb yotgan tovarlar.
# 1) Haqiqiy xarajat: finance/expenses dagi "Ombor"/saqlash to'lovlari (kecha, 7 kun, 30 kun, oylik prognoz).
# 2) SKU bo'yicha: paidStoragePriceItem (1 dona uchun kunlik tarif, so'm) x Uzum skladidagi qoldiq,
#    30 kunlik sotuv tezligi -> qoldiq necha kunga yetadi, sotilib bo'lguncha saqlashga taxminan qancha ketadi,
#    60 kundan ortiq zaxira (ortiqcha) va 30 kunda sotilmaganlar.
#    Eslatma: Uzum bepul saqlash muddatini bergani uchun haqiqiy to'lov SKU tarif x qoldiqdan kam bo'lishi mumkin
#    (shuning uchun SKU summalari "eng ko'pi bilan" deb ko'rsatiladi; aniq jami — 1-bo'limda).
# Kirish: kalitlar env (UZUM_SA_TIMSON, UZUM_CLEO, TG_TOKEN, TG_CHAT) yoki ~/uzum_key.txt
# Chiqish: 1-qator "OMBOR: <qisqa xulosa>", 2-qator "TELEGRAM: ...", keyin matn. ~/storage.txt ham yoziladi.
# Ishlatish: python3 uzum_storage.py [--no-tg]
import os, sys, math, time, json, collections, datetime as dt, requests

H = os.path.expanduser("~")
B = "https://api-seller.uzum.uz/api/seller-openapi"
TZ = dt.timezone(dt.timedelta(hours=5))
EXCESS_DAYS = 60      # shundan ko'p kunga yetadigan qoldiq "ortiqcha" hisoblanadi
TOP = 12              # signalda ko'rsatiladigan SKU soni
MIN_MONTH = 15000     # SKU oylik saqlash (eng ko'pi) shundan kam bo'lsa ro'yxatga kiritilmaydi
STORAGE_WORDS = ("ombor", "хранен", "storage", "saqlash", "склад")

keys, cfg = [], {}
ENV = [("SA & Timson", "UZUM_SA_TIMSON"), ("CLEO", "UZUM_CLEO"), ("TG_TOKEN", "TG_TOKEN"), ("TG_CHAT", "TG_CHAT")]
lines = [f"{n}:{os.environ[v]}" for n, v in ENV if os.environ.get(v)]
if not any(not n.startswith("TG") for n, v in ENV if os.environ.get(v)) and os.path.exists(os.path.join(H, "uzum_key.txt")):
    lines = open(os.path.join(H, "uzum_key.txt")).read().splitlines()
for l in lines:
    n, sep, k = l.strip().partition(":")
    if not sep or not k.strip() or n.strip().startswith("#"):
        continue
    (cfg.__setitem__(n.strip().upper(), k.strip()) if n.strip().upper().startswith("TG_") else keys.append((n.strip(), k.strip())))

def hide(s):
    s = str(s)
    for _, k in keys:
        s = s.replace(k, "***")
    return s.replace(cfg["TG_TOKEN"], "***") if cfg.get("TG_TOKEN") else s

def g(K, p, q):
    e = ""
    for a in range(7):   # sekin/uzilgan javobda kutib qayta urinadi (~3 daqiqa)
        try:
            r = requests.get(B + p, headers={"Authorization": K}, params=q, timeout=(15, 90))
            if r.ok:
                return r.json()
            e = f"HTTP {r.status_code} {r.text[:100]}"
            if r.status_code in (401, 403, 404):
                break
        except Exception as x:
            e = str(x)[:100]
        if a < 6:
            time.sleep([3, 6, 12, 20, 30, 45][a])
    raise Exception(f"{p}: {e}")

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
cut = lambda x, n: x if len(x) <= n else x[:n - 1] + "…"
now = dt.datetime.now(TZ)
t0 = now.replace(hour=0, minute=0, second=0, microsecond=0)

def is_storage(x):
    s = ((x.get("source") or "") + " " + (x.get("name") or "") + " " + (x.get("description") or "")).lower()
    return any(w in s for w in STORAGE_WORDS)

def analyze(nm, PR, OA, XA):
    """PR: product list, OA: 30 kunlik buyurtma qatorlari, XA: 30 kunlik xarajatlar. Natija: dict."""
    # --- haqiqiy saqlash xarajati (kunlar bo'yicha)
    day = collections.Counter()
    names = collections.Counter()
    for x in XA:
        if not is_storage(x):
            continue
        ts = x.get("dateService") or x.get("dateCreated") or 0
        v = x["paymentPrice"] * (-1 if x.get("type") == "INCOME" else 1)
        dd = dt.datetime.fromtimestamp(ts / 1000, TZ).date()
        if not ((t0 - dt.timedelta(days=30)).date() <= dd < t0.date()):
            continue
        day[dd] += v
        names[x.get("name") or x.get("source") or "?"] += v
    # Uzum saqlash to'lovini 1-2 kun kechikib yozadi -> "oxirgi hisoblangan kun" ko'rsatiladi
    ld = max((k for k, v in day.items() if v), default=None)
    d7 = sum(v for k, v in day.items() if k >= (t0 - dt.timedelta(days=7)).date())
    d30 = sum(day.values())
    # oylik prognoz: oxirgi 7 ta to'lovli kun medianasi x 30 (bir martalik katta to'lovlar prognozni buzmasin)
    lastv = [day[k] for k in sorted(k for k, v in day.items() if v > 0)[-7:]]
    proj = sorted(lastv)[len(lastv) // 2] * 30 if lastv else 0
    # --- SKU bo'yicha
    s30 = collections.Counter()
    for o in OA:
        if o["status"] != "CANCELED" and o["amount"] > 0 and o["date"] >= ms(t0 - dt.timedelta(days=30)):
            s30[o.get("skuTitle")] += o["amount"] - (o.get("amountReturns") or 0)
    rows = []
    for p in PR:
        for k in p.get("skuList") or []:
            rate = k.get("paidStoragePriceItem") or 0
            fbo = max(0, (k.get("quantityAvailableByStockType") or {}).get("fbo", 0) or 0)
            if not rate or not fbo:
                continue
            c = k["skuFullTitle"]
            avg = max(0, s30[c]) / 30
            days = fbo / avg if avg > 0 else math.inf
            daily = rate * fbo
            # sotilib bo'lguncha (chiziqli kamayadi) saqlash; sotilmasa — 90 kunlik
            till = rate * fbo * min(days, 90) / (2 if days < math.inf else 1)
            excess = max(0, math.ceil(fbo - avg * EXCESS_DAYS)) if avg > 0 else fbo
            rows.append(dict(shop=nm, code=c, art=(c.split("-")[1] if len(c.split("-")) > 1 else c), title=p["title"],
                             var=(k.get("characteristics") or "").strip() or k.get("skuTitle") or c,
                             rate=rate, fbo=fbo, s30=s30[c], avg=avg, days=days, daily=daily, month=daily * 30,
                             till=till, excess=excess, excess_m=excess * rate * 30, archived=bool(k.get("archived")),
                             active=bool(p.get("isActive"))))
    rows.sort(key=lambda r: (-(r["excess_m"]), -r["month"]))
    return dict(name=nm, ld=ld, yd=day.get(ld, 0) if ld else 0, d7=d7, d30=d30, proj=proj, names=names, rows=rows,
                pot=sum(r["daily"] for r in rows))

def fetch(nm, K):
    ids = [x["id"] for x in g(K, "/v1/shops", {})]
    PR = []
    for sid in ids:
        PR += pages(K, f"/v1/product/shop/{sid}", {}, lambda r: r.get("productList"))
    OA = pages(K, "/v1/finance/orders", {"shopIds": ids, "dateFrom": ms(t0 - dt.timedelta(days=30)), "dateTo": ms(t0), "group": "false"}, lambda r: r.get("orderItems"))
    XA = pages(K, "/v1/finance/expenses", {"shopIds": ids, "dateFrom": ms(t0 - dt.timedelta(days=31)), "dateTo": ms(t0)}, lambda r: (r.get("payload") or {}).get("payments"))
    return analyze(nm, PR, OA, XA)

def render(R, errs):
    L = [f"💸 PULLIK SAQLASH — Uzum skladi ({(t0 - dt.timedelta(days=1)):%d.%m.%Y} holatiga)", ""]
    L.append("HAQIQIY TO'LOV (Uzum yechgan, «Ombor»):")
    for r in R:
        if not r["d30"] and not r["rows"]:
            L.append(f"• {r['name']}: 30 kunda saqlash to'lovi yo'q")
            continue
        L.append(f"• {r['name']}: oxirgi kun ({r['ld']:%d.%m}) {F(r['yd'])} | 7 kun {F(r['d7'])} | 30 kun {F(r['d30'])} so'm | oyiga ≈ {F(r['proj'])} so'm"
                 if r["ld"] else f"• {r['name']}: 30 kunda to'lov yozilmagan")
    if len(R) > 1:
        L.append(f"• JAMI: 30 kun {F(sum(r['d30'] for r in R))} so'm | oyiga ≈ {F(sum(r['proj'] for r in R))} so'm")
    for r in R:
        if r["ld"] and r["yd"] > 3 * max(1, r["proj"] / 30):
            L.append(f"  ⚠ {r['name']}: {r['ld']:%d.%m} dagi to'lov odatdagidan ancha katta ({F(r['yd'])} so'm) — Uzum kabinetida tekshiring")
    big = [(r["name"], k, v) for r in R for k, v in r["names"].most_common() if v >= 100000]
    if big:
        L.append("  30 kundagi turlari: " + "; ".join(f"{n}: {k} {F(v)}" for n, k, v in big[:6]))
    rows = [x for r in R for x in r["rows"]]
    dead = sorted([x for x in rows if x["s30"] <= 0], key=lambda x: -x["month"])
    exc = sorted([x for x in rows if x["s30"] > 0 and x["excess"] > 0 and x["excess_m"] >= MIN_MONTH], key=lambda x: -x["excess_m"])
    L += ["", f"🔴 30 KUNDA SOTILMAGAN, LEKIN SKLADDA PULLIK TURIBDI: {len(dead)} SKU, {sum(x['fbo'] for x in dead)} dona, oyiga eng ko'pi {F(sum(x['month'] for x in dead))} so'm"]
    for x in [x for x in dead if x["month"] >= MIN_MONTH][:TOP]:
        L.append(f"  • {x['shop']}: {x['art']} — {cut(x['var'], 22)} ({cut(x['title'], 30)}): {x['fbo']} dona × {x['rate']} so'm/kun = oyiga {F(x['month'])}")
    rest = [x for x in dead if x["month"] < MIN_MONTH]
    if rest:
        L.append(f"  … va yana {len(rest)} ta mayda SKU (har biri oyiga {F(MIN_MONTH)} dan kam), jami {F(sum(x['month'] for x in rest))} so'm")
    L += ["", f"🟡 ORTIQCHA ZAXIRA ({EXCESS_DAYS} kundan ko'pga yetadi) — ortig'i oyiga eng ko'pi {F(sum(x['excess_m'] for x in exc))} so'm"]
    for x in exc[:TOP]:
        L.append(f"  • {x['shop']}: {x['art']} — {cut(x['var'], 22)}: qoldiq {x['fbo']}, 30 kunda {x['s30']} sotilgan → {x['days']:.0f} kunga yetadi | ortiqcha {x['excess']} dona, oyiga {F(x['excess_m'])} so'm")
    if not exc:
        L.append("  Yo'q")
    L += ["", "💡 Nima qilish kerak: sotilmayotganlarni Uzum skladidan qaytarib oling (vozvrat) yoki aksiya/chegirma bilan tez soting; "
          f"ortiqcha zaxirani keyingi postavkada kamaytiring ({EXCESS_DAYS} kundan ortiq tovar olib bormang).",
          "ℹ️ SKU summalari = Uzum tarifi × qoldiq (eng ko'pi). Bepul saqlash muddati tufayli haqiqiy to'lov kamroq bo'lishi mumkin — aniq jami yuqorida."]
    if errs:
        L += ["", "⚠ XATO: " + "; ".join(errs)[:400]]
    return "\n".join(L), dead, exc

def main():
    R, errs = [], []
    for nm, K in keys:
        try:
            R.append(fetch(nm, K))
        except Exception as x:
            errs.append(f"{nm}: {hide(x)[:150]}")
    text, dead, exc = render(R, errs)
    open(os.path.join(H, "storage.txt"), "w").write(text)
    tg = "TELEGRAM: sozlanmagan"
    if cfg.get("TG_TOKEN") and "--no-tg" not in sys.argv:
        try:
            m = text
            while m:
                c = m.rfind("\n", 0, 4000) if len(m) > 4000 else len(m)
                c = c if c > 0 else 4000
                r = requests.post(f"https://api.telegram.org/bot{cfg['TG_TOKEN']}/sendMessage", data={"chat_id": cfg.get("TG_CHAT"), "text": m[:c]}, timeout=30)
                if not r.ok:
                    raise Exception(f"HTTP {r.status_code} {r.text[:100]}")
                m = m[c:].lstrip("\n")
            tg = "TELEGRAM: yuborildi"
        except Exception as x:
            tg = "TELEGRAM XATO: " + hide(x)[:150]
    short = f"OMBOR: oyiga ≈ {F(sum(r['proj'] for r in R))} so'm saqlash; sotilmay pullik turgan {len(dead)} SKU ({sum(x['fbo'] for x in dead)} dona)"
    if errs:
        short += f" | xato: {', '.join(e.split(':')[0] for e in errs)}"
    print(short); print(tg); print(text)

if __name__ == "__main__":
    main()
