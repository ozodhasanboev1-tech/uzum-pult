import os,io,sys,time,html,textwrap,collections,datetime as dt,requests
# Soatlik Uzum hisobot v3 (SKU bo'yicha, kamdan ko'pga) -> Telegram (matn + kartochkalar jadvali + dashboard tugmasi). Kalitlarni env dan o'qiydi.
B="https://api-seller.uzum.uz/api/seller-openapi";TZ=dt.timezone(dt.timedelta(hours=5))
DASH=(os.environ.get("PULT_URL") or "https://claude.ai/artifact/7KKL91np9JgoCv6R1sRscJ").rstrip("/")+"/#bugun"
keys,cfg=[],{}
for l in "\n".join(f"{n}:{os.environ[v]}" for n,v in [("SA & Timson","UZUM_SA_TIMSON"),("CLEO","UZUM_CLEO"),("TG_TOKEN","TG_TOKEN"),("TG_CHAT","TG_CHAT")] if os.environ.get(v)).splitlines():
    n,sep,k=l.strip().partition(":")
    if not sep or not k.strip(): continue
    if n.strip().upper().startswith("TG_"): cfg[n.strip().upper()]=k.strip()
    else: keys.append((n.strip(),k.strip()))
# Uzum API sekin javob bersa / 429 / 5xx / tarmoq uzilsa — kutib qayta urinadi (jami ~3 daqiqagacha)
WAIT=[3,6,12,20,30,45]
def g(K,p,q):
    e="?"
    for a,w in enumerate(WAIT+[None]):
        try:
            r=requests.get(B+p,headers={"Authorization":K},params=q,timeout=(15,90))
            if r.ok: return r.json()
            e=f"HTTP {r.status_code}"
            if r.status_code in (400,401,403,404): break   # kalit/so'rov xato — kutish foyda bermaydi
            ra=r.headers.get("Retry-After")
            if ra and ra.isdigit() and w is not None: w=max(w,min(int(ra),60))
        except Exception as x: e=type(x).__name__+": "+str(x)[:60]
        if w is None: break
        time.sleep(w)
    raise Exception(f"{p}: {e}")
def pages(K,p,q,f):
    o,n=[],0
    while True:
        it=f(g(K,p,{**q,"size":100,"page":n})) or [];o+=it
        if len(it)<100 or n>50: return o
        n+=1
import csv,re
TN,VN={},{}
_p=os.path.expanduser("~/tannarx.csv")
if os.path.exists(_p):
    _r=list(csv.reader(open(_p,encoding="utf-8-sig")))
    if _r:
        _h=[x.lower() for x in _r[0]];_iu=next((i for i,x in enumerate(_h) if "uzum" in x and "tannarx" in x),3);_iy=next((i for i,x in enumerate(_h) if "sizning" in x),4);_iv=next((i for i,x in enumerate(_h) if "variant" in x),2)
        def _n(c):
            c=re.sub(r"[\s\xa0']","",c or "")
            try: return float(c.replace(",","."))
            except ValueError: return None
        for x in _r[1:]:
            if not x or not x[0].strip(): continue
            v=(_n(x[_iy]) if len(x)>_iy else None) or (_n(x[_iu]) if len(x)>_iu else None)
            if v and v>0: TN[x[0].strip()]=v
            if len(x)>_iv and x[_iv].strip(): VN[x[0].strip()]=x[_iv].strip()
ART=lambda c:(c or "?").split("-")[1] if len((c or "").split("-"))>1 else (c or "?")
VAR=lambda c:VN.get(c) or (c or "").split("-")[-1]
F=lambda n:f"{int(round(n)):,}".replace(","," ")
now=dt.datetime.now(TZ);d0=now.replace(hour=0,minute=0,second=0,microsecond=0)
h1=now.replace(minute=0,second=0,microsecond=0);h0=h1-dt.timedelta(hours=1)
if h1<=d0: h1=now;h0=d0   # 00:xx da ishga tushsa
ms=lambda d:int(d.timestamp()*1000)
Z=lambda:dict(q=0,rev=0,pay=0,cost=0,canc=set(),cs=0)
H,T,rows,shopT,errs=Z(),Z(),{},[],[]
def add(a,o):
    a["q"]+=o["amount"];a["rev"]+=o["amount"]*o["sellPrice"];a["pay"]+=o["sellerProfit"];a["cost"]+=o["amount"]*(TN.get(o.get("skuTitle")) or o.get("purchasePrice") or 0)
    if o["status"]=="CANCELED" or o.get("amountReturns"): a["canc"].add(o["orderId"]);a["cs"]+=(o.get("amountReturns") or 0)*o["sellPrice"]
TD=[]
def shop(si,nm,K):
    if True:
        sh=g(K,"/v1/shops",{});ids=[x["id"] for x in sh];S=Z()
        for o in pages(K,"/v1/finance/orders",{"shopIds":ids,"dateFrom":ms(d0),"dateTo":ms(now),"group":"false"},lambda r:r.get("orderItems")):
            ts=o["date"]/1000
            TD.append([int(ts),si,o.get("skuTitle"),o["productTitle"],o.get("productId"),{"CANCELED":0,"PROCESSING":1,"TO_WITHDRAW":2}.get(o["status"],1),o["amount"],o["sellPrice"],o["sellerProfit"],o.get("purchasePrice") or 0,
                o.get("commission") or 0,o.get("logisticDeliveryFee") or 0,o.get("amountReturns") or 0,((o.get("returnCause") or "Sabab ko'rsatilmagan")+(f" ({o['comment'].strip()})" if o.get("comment") else "")) if o.get("amountReturns") else ""])
            if ts>=h1.timestamp(): continue
            add(T,o);add(S,o)
            inh=ts>=h0.timestamp()
            if inh: add(H,o)
            if o["amount"]>0:
                sk=o.get("skuTitle");c=(nm,ART(sk))
                r=rows.setdefault(c,dict(t=o["productTitle"],art=ART(sk),vs=collections.Counter(),shop=nm,q=0,hq=0,rev=0,pay=0,cost=0))
                r["vs"][VAR(sk)]+=o["amount"];r["q"]+=o["amount"];r["rev"]+=o["amount"]*o["sellPrice"];r["pay"]+=o["sellerProfit"];r["cost"]+=o["amount"]*(TN.get(sk) or o.get("purchasePrice") or 0)
                if inh: r["hq"]+=o["amount"]
        shopT.append((nm,S))
failed=[]
for si,(nm,K) in enumerate(keys):
    try: shop(si,nm,K)
    except Exception as x: failed.append((si,nm,K,x))
if failed: time.sleep(30)   # xato bergan do'konlarni 30 soniyadan keyin yana bir bor urinib ko'rish
for si,nm,K,x0 in failed:
    try: shop(si,nm,K)
    except Exception as x: errs.append(f"{nm}: {x}")
shopT.sort(key=lambda z:[n for n,_ in keys].index(z[0]))
net=lambda a:a["pay"]-a["cost"]
b=lambda s:f"<b>{s}</b>"
def block(title,a):
    s=[f"🗓 {b(title)}","",f"🛍 {b('Sotildi:')} {F(a['q'])} dona",f"🏦 {b('Tushum:')} {F(a['rev'])} so'm",f"💰 {b('To`lovga:')} {F(a['pay'])} so'm".replace("`","'"),f"💵 {b('Sof foyda:')} {F(net(a))} so'm"]
    if a["canc"]: s+=["",f"❌ {b('Bekor qilingan:')} {len(a['canc'])} ta buyurtma, {F(a['cs'])} so'm"]
    return s
msg=["🟣 <b>Uzum Market</b>",""]+block(f"{h0:%H:%M} – {h1:%H:%M}",H)+[""]+block(f"Bugun, 00:00 – {h1:%H:%M}",T)+[""]
msg+=[f"• {html.escape(nm)}: {F(a['q'])} dona, {F(a['rev'])} so'm" for nm,a in shopT]
if errs: msg+=["","⚠️ "+html.escape("; ".join(errs))[:300]]
caption="\n".join(msg)

# Jadval-rasm
def table_png():
    from PIL import Image,ImageDraw,ImageFont
    fp="/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf";fb="/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    f=ImageFont.truetype(fp,15);fB=ImageFont.truetype(fb,15);fs=ImageFont.truetype(fp,12);fT=ImageFont.truetype(fb,19)
    R=sorted(rows.values(),key=lambda r:(r["q"],r["rev"]));more=max(0,len(R)-45);R=R[:45]
    cols=[("SKU — variant",560,"l"),("Bugun",70,"r"),("Soatda",75,"r"),("Tushum",120,"r"),("To'lovga",120,"r"),("Sof",110,"r"),("ROI",80,"r")]
    W=sum(c[1] for c in cols)+40;rh=46;Hh=90+rh*(len(R)+1)+40+(24 if more else 0)
    im=Image.new("RGB",(W,Hh),"white");d=ImageDraw.Draw(im)
    d.text((20,18),f"Bugungi sotuv — {now:%d.%m.%Y}, {h1:%H:%M} gacha",font=fT,fill="#17161c")
    d.text((20,48),"Artikul (SKU) bo'yicha, kamdan ko'pga. Soatda = oxirgi soatda sotilgan dona. Sof = to'lovga − tannarx. ROI = sof / tannarx.",font=fs,fill="#6b6975")
    y=76;x=20
    for n,w,a in cols:
        tw=d.textlength(n,font=fs);d.text((x+(w-tw-10 if a=="r" else 0),y+6),n.upper(),font=fs,fill="#8a8894");x+=w
    y+=28;d.line((20,y,W-20,y),fill="#e4e3ea")
    def row(vals,bold=False,shade=False):
        nonlocal y
        if shade: d.rectangle((20,y,W-20,y+rh),fill="#f6f2ff")
        x=20
        for (n,w,a),v in zip(cols,vals):
            fo=fB if bold else f
            if isinstance(v,tuple): d.text((x,y+5),v[0],font=fo,fill="#17161c");d.text((x,y+25),v[1],font=fs,fill="#8a8894")
            else:
                col="#17161c"
                if isinstance(v,str) and v.startswith("-"): col="#c2372f"
                if isinstance(v,str) and v.startswith("+"): col="#12805c"
                tw=d.textlength(v,font=fo);d.text((x+w-tw-10 if a=="r" else x,y+14),v,font=fo,fill=col)
            x+=w
        y+=rh;d.line((20,y,W-20,y),fill="#efeef3")
    for r in R:
        n=net(r);roi=f"{n/r['cost']*100:.1f}%" if r["cost"] else "—"
        vs=", ".join(f"{v} {q}" if len(r["vs"])>1 else v for v,q in r["vs"].most_common())
        title=textwrap.shorten(f"{r['art']} — {vs}",60,placeholder="…")
        row([(title,textwrap.shorten(f"{r['shop']} · {r['t']}",80,placeholder="…")),F(r["q"]),f"+{r['hq']}" if r["hq"] else "",F(r["rev"]),F(r["pay"]),F(n),roi],shade=r["hq"]>0)
    tn=net(T);row([("Jami",""),F(T["q"]),f"+{H['q']}" if H["q"] else "",F(T["rev"]),F(T["pay"]),F(tn),f"{tn/T['cost']*100:.1f}%" if T["cost"] else "—"],bold=True)
    if more: d.text((20,y+8),f"… yana {more} kartochka dashboardda",font=fs,fill="#8a8894")
    bio=io.BytesIO();im.save(bio,"PNG");bio.seek(0);return bio

# Dashboard uchun bugungi buyurtmalar -> ~/dash/today.json
import json;os.makedirs(os.path.expanduser("~/dash"),exist_ok=True)
json.dump(dict(gen=int(now.timestamp()),day0=int(d0.timestamp()),orders=TD,shops=[n for n,_ in keys]),open(os.path.expanduser("~/dash/today.json"),"w"),ensure_ascii=False,separators=(",",":"))
out="TELEGRAM: sozlanmagan"
def tg(method,data,files=None):
    tok=cfg["TG_TOKEN"];last="?"
    for w in (0,5,15,30):
        time.sleep(w)
        try:
            if files: files={k:(v[0],io.BytesIO(v[1]),v[2]) for k,v in files.items()}
            r=requests.post(f"https://api.telegram.org/bot{tok}/{method}",data=data,files=files,timeout=60)
            if r.ok: return None
            last=f"HTTP {r.status_code} {r.text[:120]}"
            if r.status_code==400: break
        except Exception as x: last=str(x).replace(tok,"***")[:150]
    return last
if cfg.get("TG_TOKEN") and "--no-tg" not in sys.argv:
    chat=cfg.get("TG_CHAT")
    kb='{"inline_keyboard":[[{"text":"📊 Dashboardni ochish","url":"'+DASH+'"}]]}'
    png=None
    if rows:
        try: png=table_png().read()
        except Exception as x: errs.append("jadval rasmi: "+str(x)[:60])
    e1=tg("sendPhoto",{"chat_id":chat,"caption":caption[:1024],"parse_mode":"HTML","reply_markup":kb},{"photo":("t.png",png,"image/png")}) if png else "rasm yo'q"
    if e1:   # rasm ketmasa — oddiy matn bilan
        e2=tg("sendMessage",{"chat_id":chat,"text":caption[:4000],"parse_mode":"HTML","reply_markup":kb})
        if e2: e2=tg("sendMessage",{"chat_id":chat,"text":re.sub(r"<[^>]+>","",caption)[:4000]})
        out="TELEGRAM: yuborildi" if not e2 else f"TELEGRAM XATO: {e2}"
    else: out="TELEGRAM: yuborildi"
elif "--no-tg" in sys.argv and rows: open(os.path.expanduser("~/h_table.png"),"wb").write(table_png().read())
print(out);print(f"SOAT {h0:%H:%M}-{h1:%H:%M}: {H['q']} dona, {F(H['rev'])} so'm | BUGUN: {T['q']} dona, {F(T['rev'])} so'm"+(f" | XATO: {'; '.join(errs)}" if errs else ""))
if "--no-tg" in sys.argv: print(caption)
