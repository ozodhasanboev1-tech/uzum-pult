#!/usr/bin/env python3
# QISQA KUNLIK hisobot: kechagi savdo do'konlar bo'yicha (Uzum + Wildberries), vozvratlar va oldingi kun bilan solishtiruv diagrammasi.
# Kirish: env UZUM_SA_TIMSON, UZUM_CLEO, WB_CLEO, WB_NASIROV, TG_TOKEN, TG_CHAT.
#         ~/wb_report.py (WB funksiyalari), ~/out_wb/wb_daily.json (rubl kursi; avval "wb_report.py daily --no-tg").
# Chiqish: Telegram'ga bitta rasm + qisqa matn; ~/brief.txt, ~/brief.png. 1-qator "BRIEF: ...", 2-qator "TELEGRAM: ...".
# Ishlatish: python3 brief.py [--no-tg] [--date YYYY-MM-DD]
import os, sys, json, time, datetime as dt, requests

H = os.path.expanduser("~")
TZ = dt.timezone(dt.timedelta(hours=5))
B = "https://api-seller.uzum.uz/api/seller-openapi"
UZ = [("SA & Timson", "UZUM_SA_TIMSON"), ("CLEO", "UZUM_CLEO")]
WB = [("CLEO", "WB_CLEO"), ("NASIROV", "WB_NASIROV")]
TG = (os.environ.get("TG_TOKEN", "").strip(), os.environ.get("TG_CHAT", "").strip())
SECRETS = [os.environ.get(v, "").strip() for _, v in UZ + WB] + [TG[0]]
WD = ["dushanba", "seshanba", "chorshanba", "payshanba", "juma", "shanba", "yakshanba"]

def hide(s):
    s = str(s)
    for k in SECRETS:
        if k: s = s.replace(k, "***")
    return s

F = lambda n: f"{int(round(n or 0)):,}".replace(",", " ")
def M(n):
    a = abs(n or 0)
    if a >= 1e6: return f"{n / 1e6:.1f} mln".replace(".", ",")
    if a >= 1e3: return f"{n / 1e3:.0f} ming"
    return f"{n:.0f}"
def pct(a, b):
    if not b: return "yangi" if a else "—"
    d = (a - b) / b * 100
    if abs(d) < 0.5: return "±0%"
    return f"{'▲' if d >= 0 else '▼'}{abs(d):.0f}%"

a = sys.argv[1:]
day = dt.date.fromisoformat(a[a.index("--date") + 1]) if "--date" in a else dt.datetime.now(TZ).date() - dt.timedelta(days=1)
prev = day - dt.timedelta(days=1)
ms = lambda d: int(dt.datetime(d.year, d.month, d.day, tzinfo=TZ).timestamp() * 1000)

# ------------------------------------------------------------ Uzum
def ug(K, p, q):
    e = ""
    for i in range(4):
        try:
            r = requests.get(B + p, headers={"Authorization": K}, params=q, timeout=60)
            if r.ok: return r.json()
            e = f"HTTP {r.status_code}"
            if r.status_code in (401, 403): break
        except Exception as x: e = str(x)[:80]
        time.sleep(3 * (i + 1))
    raise Exception(f"{p}: {hide(e)}")

def uzum(K):
    ids = [x["id"] for x in ug(K, "/v1/shops", {})]
    O, n = [], 0
    while True:
        it = ug(K, "/v1/finance/orders", {"shopIds": ids, "dateFrom": ms(prev), "dateTo": ms(day + dt.timedelta(days=1)),
                                          "group": "false", "size": 100, "page": n}).get("orderItems") or []
        O += it
        if len(it) < 100 or n > 60: break
        n += 1
    out = {}
    for d in (prev, day):
        Y = [o for o in O if ms(d) <= o["date"] < ms(d + dt.timedelta(days=1))]
        S = [o for o in Y if o["status"] != "CANCELED" and o["amount"] > 0]
        out[d] = dict(sum=sum(o["sellPrice"] * o["amount"] for o in S), q=sum(o["amount"] for o in S),
                      ret=sum(o.get("amountReturns") or 0 for o in Y if o["status"] != "CANCELED"),
                      canc=sum(o.get("amountReturns") or 1 for o in Y if o["status"] == "CANCELED"))
    return out

# ------------------------------------------------------------ Wildberries (statistika: S = sotuv, R = vozvrat)
rate = None
try: rate = json.load(open(os.path.join(H, "out_wb", "wb_daily.json"))).get("rate")
except Exception: pass

def wb(tok):
    sys.path.insert(0, H)
    import wb_report
    sales = wb_report.stat(tok, "sales", f"{prev}")
    out = {}
    for d in (prev, day):
        X = [s for s in sales if (s.get("date") or "")[:10] == f"{d}"]
        R = [s for s in X if (s.get("saleID") or "").startswith("R")]
        Sx = [s for s in X if not (s.get("saleID") or "").startswith("R")]
        rub = sum(abs(s.get("finishedPrice") or 0) for s in Sx)
        out[d] = dict(sum=rub * (rate or 1), q=len(Sx), ret=len(R), retsum=sum(abs(s.get("finishedPrice") or 0) for s in R) * (rate or 1), canc=0)
    return out

rows, errs = [], []
for mp, lst, fn in (("Uzum", UZ, uzum), ("WB", WB, wb)):
    for nm, var in lst:
        k = os.environ.get(var, "").strip()
        if not k: continue
        try: rows.append(dict(mp=mp, nm=nm, **{"y": (r := fn(k))[day], "p": r[prev]}))
        except Exception as x: errs.append(f"{mp} {nm}: {hide(x)[:100]}")

# ------------------------------------------------------------ matn
cur = "so'm" if rate or not any(r["mp"] == "WB" for r in rows) else "so'm*"
L = [f"📊 Kunlik · {day:%d.%m.%Y} ({WD[day.weekday()]})"]
for mp, title in (("Uzum", "🟣 UZUM"), ("WB", "🟪 WILDBERRIES")):
    R = [r for r in rows if r["mp"] == mp]
    if not R: continue
    L += ["", title]
    for r in R:
        y, p = r["y"], r["p"]
        extra = []
        if y["ret"]: extra.append(f"vozvrat {y['ret']}")
        if y["canc"]: extra.append(f"bekor {y['canc']}")
        L.append(f"• {r['nm']}: {F(y['sum'])} · {y['q']} dona" + (" · " + ", ".join(extra) if extra else "") + f"  {pct(y['sum'], p['sum'])}")
    ty, tp = sum(r["y"]["sum"] for r in R), sum(r["p"]["sum"] for r in R)
    L.append(f"  Jami: {F(ty)} so'm  {pct(ty, tp)}")
TY, TP = sum(r["y"]["sum"] for r in rows), sum(r["p"]["sum"] for r in rows)
L += ["", f"💰 HAMMASI: {F(TY)} so'm (oldingi kun {M(TP)}, {pct(TY, TP)})"]
if any(r["mp"] == "WB" for r in rows) and not rate:
    L.append("* WB kursi topilmadi — WB summalari rublda")
if errs: L.append("⚠ " + "; ".join(errs)[:300])
text = "\n".join(L)
open(os.path.join(H, "brief.txt"), "w").write(text)

# ------------------------------------------------------------ diagramma: kecha vs oldingi kun (gorizontal juft ustunlar)
png = os.path.join(H, "brief.png")
try:
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    SURF, INK, INK2, MUTE, CUR, PRV = "#fcfcfb", "#0b0b0b", "#52514e", "#8a8984", "#2a78d6", "#c9c8c2"
    labels = [f"{'Uzum' if r['mp'] == 'Uzum' else 'WB'} · {r['nm']}" for r in rows][::-1]
    yv = [r["y"]["sum"] for r in rows][::-1]; pv = [r["p"]["sum"] for r in rows][::-1]
    n = len(rows); h = 0.36
    fig, ax = plt.subplots(figsize=(9, 0.62 * n + 1.5), dpi=150)
    fig.patch.set_facecolor(SURF); ax.set_facecolor(SURF)
    ys = list(range(n))
    ax.barh([i + h / 2 + 0.02 for i in ys], pv, height=h, color=PRV, label=f"{prev:%d.%m}", zorder=2)
    ax.barh([i - h / 2 - 0.02 for i in ys], yv, height=h, color=CUR, label=f"{day:%d.%m} (kecha)", zorder=2)
    mx = max(yv + pv + [1])
    for i, (v, p_) in enumerate(zip(yv, pv)):
        ax.text(v + mx * 0.01, i - h / 2 - 0.02, f"{M(v)}  {pct(v, p_)}", va="center", fontsize=9, color=INK)
    ax.set_yticks(ys); ax.set_yticklabels(labels, fontsize=10, color=INK)
    ax.set_xlim(0, mx * 1.28)
    ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: M(v)))
    ax.tick_params(axis="x", colors=MUTE, labelsize=8); ax.tick_params(axis="y", length=0)
    ax.grid(axis="x", color="#e6e5e0", linewidth=0.8, zorder=0)
    for s in ax.spines.values(): s.set_visible(False)
    nu = sum(1 for r in rows if r["mp"] == "Uzum")
    if 0 < nu < n: ax.axhline(n - nu - 0.5, color="#d6d5cf", linewidth=1)
    ax.set_title(f"Savdo, so'm — kecha vs oldingi kun · jami {M(TY)} ({pct(TY, TP)})", loc="left", fontsize=11, color=INK, pad=22)
    ax.legend(loc="lower right", bbox_to_anchor=(1, 1.0), ncol=2, frameon=False, fontsize=9, labelcolor=INK2)
    fig.tight_layout(); fig.savefig(png, facecolor=SURF); plt.close(fig)
except Exception as x:
    errs.append(f"diagramma: {hide(x)[:80]}"); png = None

# ------------------------------------------------------------ Telegram
st = "TELEGRAM: sozlanmagan"
if TG[0] and "--no-tg" not in a:
    try:
        if png and len(text) <= 1000:
            r = requests.post(f"https://api.telegram.org/bot{TG[0]}/sendPhoto", data={"chat_id": TG[1], "caption": text},
                              files={"photo": ("kunlik.png", open(png, "rb"), "image/png")}, timeout=60)
        else:
            if png:
                requests.post(f"https://api.telegram.org/bot{TG[0]}/sendPhoto", data={"chat_id": TG[1]},
                              files={"photo": ("kunlik.png", open(png, "rb"), "image/png")}, timeout=60)
            r = requests.post(f"https://api.telegram.org/bot{TG[0]}/sendMessage", data={"chat_id": TG[1], "text": text}, timeout=30)
        st = "TELEGRAM: yuborildi" if r.ok else f"TELEGRAM XATO: HTTP {r.status_code}"
    except Exception as x:
        st = "TELEGRAM XATO: " + hide(x)[:120]

print("BRIEF: " + " | ".join(f"{r['mp']} {r['nm']} {M(r['y']['sum'])}" for r in rows) + f" | jami {M(TY)} {pct(TY, TP)}" + (" | xato: " + "; ".join(errs) if errs else ""))
print(st)
print(text)
