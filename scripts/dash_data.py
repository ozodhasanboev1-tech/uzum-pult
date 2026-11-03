import os,json,time,base64,datetime as dt,requests,concurrent.futures as cf
# Uzum dashboard uchun ma'lumot: ~/dash/data.json va ~/dash/imgs.json
B="https://api-seller.uzum.uz/api/seller-openapi";TZ=dt.timezone(dt.timedelta(hours=5));DAYS=90
keys=[]
# o'z tannarxingiz: ~/tannarx.csv ("Sizning tannarx (to'ldiring)" ustuni) — bo'lmasa bo'sh
TR={}
try:
    import csv,re
    rows=list(csv.reader(open(os.path.expanduser("~/tannarx.csv"),encoding="utf-8-sig")))
    hd=[h.lower() for h in rows[0]];iy=next((i for i,h in enumerate(hd) if "sizning" in h),4)
    for r in rows[1:]:
        if len(r)>iy and r[0].strip():
            v=re.sub(r"[^0-9.,]","",r[iy]).replace(",",".")
            if v:
                try: TR[r[0].strip()]=float(v)
                except ValueError: pass
except Exception: pass
for n,v in [("SA & Timson","UZUM_SA_TIMSON"),("CLEO","UZUM_CLEO")]:
    if os.environ.get(v,"").strip(): keys.append((n,os.environ[v].strip()))
def g(K,p,q):
    for a in range(7):   # sekin/uzilgan javobda kutib qayta urinadi (~3 daqiqa)
        try:
            r=requests.get(B+p,headers={"Authorization":K},params=q,timeout=(15,90))
            if r.ok: return r.json()
            e=f"HTTP {r.status_code}"
            if r.status_code in (401,403,404): break
        except Exception as x: e=str(x)[:120]
        if a<6: time.sleep([3,6,12,20,30,45][a])
    raise Exception(f"{p}: {e}")
def pages(K,p,q,f):
    o,n=[],0
    while True:
        it=f(g(K,p,{**q,"size":100,"page":n})) or [];o+=it
        if len(it)<100 or n>400: return o
        n+=1
ms=lambda d:int(d.timestamp()*1000)
now=dt.datetime.now(TZ);t0=now.replace(hour=0,minute=0,second=0,microsecond=0)-dt.timedelta(days=DAYS)
ST={"CANCELED":0,"PROCESSING":1,"TO_WITHDRAW":2,"WITHDRAWN":3}
shops,skus,skuix,orders,causes,cix,exps,srcs,six,prods,imgurl,errors,rets,enames,enix,invs=[],[],{},[],[],{},[],[],{},[],{},[],[],[],{},[]
def lst(j):
    if isinstance(j,list): return j
    if isinstance(j,dict):
        for k in ("payload","data","content","items","returns","list","result"):
            v=j.get(k)
            if isinstance(v,list): return v
            if isinstance(v,dict):
                r=lst(v)
                if r: return r
        for v in j.values():
            if isinstance(v,list) and v and isinstance(v[0],dict): return v
    return []
def ix(lst,d,v):
    if v not in d: d[v]=len(lst);lst.append(v)
    return d[v]
for si,(nm,K) in enumerate(keys):
    try:
        sh=g(K,"/v1/shops",{});ids=[x["id"] for x in sh]
        PR=[]
        for sid in ids: PR+=pages(K,f"/v1/product/shop/{sid}",{},lambda r:r.get("productList"))
        for p in PR:
            prods.append(dict(s=si,pid=p["productId"],t=p["title"],cat=p.get("category"),v=p.get("viewers"),cv=p.get("conversion"),
                r=p.get("rating"),fb=p.get("feedbackQuantity"),rp=p.get("returnedPercentage"),rk=(p.get("rankInfo") or {}).get("rank"),
                act=bool(p.get("isActive")),img=(p.get("previewImg") or "").split("/t_")[0].rsplit("/",1)[-1]))
            for k in p.get("skuList") or []:
                im=(k.get("previewImage") or p.get("image") or "").split("/t_")[0].rsplit("/",1)[-1]
                if im: imgurl[im]=f"https://images.uzum.uz/{im}/t_product_240_low.jpg"
                skuix[k["skuFullTitle"]]=len(skus)
                skus.append(dict(s=si,pid=p["productId"],c=k["skuFullTitle"],t=p["title"],v=(k.get("characteristics") or "").strip() or k["skuTitle"],
                    fbo=max(0,(k.get("quantityAvailableByStockType") or {}).get("fbo",k.get("quantityActive") or 0) or 0),fbs=max(0,k.get("quantityFbs") or 0),
                    p=k.get("price") or 0,ar=bool(k.get("archived")),im=im,rank=(k.get("rankInfo") or {}).get("rank"),ps=k.get("paidStoragePriceItem"),
                    df=k.get("quantityDefected") or 0,ms=k.get("quantityMissing") or 0,cm=k.get("commission"),bc=k.get("barcode"),
                    psa=k.get("paidStorageAmount"),pp=k.get("purchasePrice"),tr=TR.get(k["skuFullTitle"]),pst=k.get("pstorage"),dg=k.get("paidStorageDimensionalGroup") or k.get("dimensionalGroup")))
        O=pages(K,"/v1/finance/orders",{"shopIds":ids,"dateFrom":ms(t0),"dateTo":ms(now),"group":"false"},lambda r:r.get("orderItems"))
        for o in O:
            c=o.get("skuTitle")
            if c not in skuix:
                skuix[c]=len(skus);skus.append(dict(s=si,pid=o.get("productId"),c=c,t=o["productTitle"],v=(c or "").split("-")[-1],fbo=0,fbs=0,p=o["sellPrice"],ar=True,im="",rank=None,ps=None))
            cause=ix(causes,cix,(o.get("returnCause") or "Sabab ko'rsatilmagan")+(f" ({o['comment'].strip()})" if o.get("comment") else "")) if o.get("amountReturns") else -1
            orders.append([o["date"]//1000,skuix[c],ST.get(o["status"],1),o["amount"],o["sellPrice"],o["sellerProfit"],o.get("purchasePrice") or 0,
                o.get("commission") or 0,o.get("logisticDeliveryFee") or 0,o.get("amountReturns") or 0,cause,1 if o.get("withdrawnProfit") else 0,o.get("orderId")])
        X=pages(K,"/v1/finance/expenses",{"shopIds":ids,"dateFrom":ms(t0),"dateTo":ms(now)},lambda r:(r.get("payload") or {}).get("payments"))
        for x in X:
            d=x.get("dateService") or x.get("dateCreated") or 0
            nm_=(x.get("name") or "").strip();import re as _re
            m_=_re.search(r"IDsi\D{0,5}(\d+)",nm_);ref=("p",int(m_.group(1))) if m_ else None
            if not ref:
                m_=_re.search(r"№\s*(\d+)",nm_);ref=("o",int(m_.group(1))) if m_ else None
            lb=_re.sub(r"\s*\d[\d .,:\-]*\d|\s*\d","#",nm_)
            lb=_re.sub(r"(№|IDsi\s*—|sana\s*—|Namoyish\s*—|foiz\s*—)\s*#%?","",lb);lb=_re.sub(r"#\s*so‘m|#","",lb);lb=_re.sub(r"\s+([,.])","\\1",_re.sub(r"\s{2,}"," ",lb)).strip(" ,.")
            lb=_re.sub(r",?\s*tovar$","",_re.sub(r"\[\s*\]|\(\s*\)","",lb.split(". ")[0])).strip(" ,.")
            exps.append([d//1000,si,ix(srcs,six,x.get("source") or "Boshqa"),(-1 if x.get("type")=="INCOME" else 1)*x["paymentPrice"],ix(enames,enix,(lb or x.get("source") or "")[:120]),
                (ref[1] if ref and ref[0]=="o" else -ref[1] if ref else 0),x.get("amount") or 0])
        # Postavkalar (Uzum skladiga topshirilgan nakladnoylar) va tarkibi
        try:
            for sid in ids:
                IV=[]
                for pg in range(30):
                    it=lst(g(K,f"/v1/shop/{sid}/invoice",{"page":pg,"size":100}));IV+=it
                    if len(it)<100: break
                IV.sort(key=lambda v:str(v.get("dateCreated") or ""),reverse=True)
                for iv in IV[:150]:
                    dd=iv.get("dateAccepted")
                    st_=iv.get("invoiceStatus") or iv.get("status");st_=(st_.get("value") or st_.get("text")) if isinstance(st_,dict) else st_
                    items=[]
                    try:
                        for pr in lst(g(K,f"/v1/shop/{sid}/invoice/products",{"invoiceId":iv.get("id")})):
                            for k in (pr.get("skuForInvoiceDtoList") or [pr]):
                                items.append([k.get("skuTitle"),k.get("quantityAccepted") or 0,k.get("quantityToStock") or 0,k.get("purchasePrice") or pr.get("purchasePrice") or 0])
                    except Exception: pass
                    tsr=iv.get("timeSlotReservation") or {};stk=iv.get("stock") or {}
                    invs.append(dict(s=si,id=iv.get("id"),no=iv.get("invoiceNumber") or iv.get("externalNumber"),d=dd,dc=iv.get("dateCreated"),st=st_,stt=(iv.get("invoiceStatus") or {}).get("text") if isinstance(iv.get("invoiceStatus"),dict) else None,
                        acc=iv.get("totalAccepted"),send=iv.get("totalToStock"),fp=iv.get("fullPrice"),tf=tsr.get("timeFrom") if isinstance(tsr,dict) else None,tt=tsr.get("timeTo") if isinstance(tsr,dict) else None,
                        wh=stk.get("title") if isinstance(stk,dict) else None,it=items))
        except Exception as x:
            errors.append(f"{nm} postavka: {str(x)[:80]}")
        # Uzum skladidan qaytarish aktlari (DEFECTED = brak): akt raqami, sana, holat, tarkibi
        try:
            for sid in ids:
                R_=[]
                for pg in range(20):
                    it=lst(g(K,f"/v1/shop/{sid}/return",{"page":pg,"size":100}));R_+=it
                    if len(it)<100: break
                R_.sort(key=lambda v:str(v.get("dateCreated") or ""),reverse=True)
                for r in R_[:300]:
                    rid=r.get("id")
                    try:
                        dj=g(K,f"/v1/shop/{sid}/return/{rid}",{});pl=(dj.get("payload") if isinstance(dj,dict) else None) or dj
                        items=(pl.get("returnItems") if isinstance(pl,dict) else None) or lst(pl)
                        if items and isinstance(items[0],dict) and "returnItems" in items[0]: items=items[0]["returnItems"] or []
                    except Exception: items=[]
                    stk=r.get("stock") or {}
                    rets.append(dict(s=si,id=rid,no=r.get("externalNumber"),d=r.get("dateCreated"),st=r.get("status"),ty=r.get("type"),
                        wh=stk.get("title") if isinstance(stk,dict) else None,ex=r.get("executionDate"),cd=r.get("completedDate"),
                        it=[[x.get("skuTitle"),x.get("amount") or 0,x.get("packedAmount"),x.get("purchasePrice") or 0] for x in items if isinstance(x,dict)]))
        except Exception as x:
            errors.append(f"{nm} aktlar: {str(x)[:80]}")
        shops.append(dict(n=nm,ids=ids,names=[x["name"] for x in sh],fbo=any(k["fbo"]>0 for k in skus if k["s"]==si)))
    except Exception as x:
        shops.append(dict(n=nm,ids=[],names=[],fbo=False,err=str(x)[:120]));errors.append(nm)
os.makedirs(os.path.expanduser("~/dash"),exist_ok=True)
json.dump(dict(gen=int(now.timestamp()),days=DAYS,shops=shops,skus=skus,orders=orders,causes=causes,exps=exps,srcs=srcs,enames=enames,prods=prods,rets=rets,invs=invs),
          open(os.path.expanduser("~/dash/data.json"),"w"),ensure_ascii=False,separators=(",",":"))
def fetch(item):
    k,u=item
    try:
        r=requests.get(u,timeout=20)
        if r.ok and len(r.content)<60000: return k,"data:image/jpeg;base64,"+base64.b64encode(r.content).decode()
    except Exception: pass
    return k,None
with cf.ThreadPoolExecutor(8) as ex: imgs={k:v for k,v in ex.map(fetch,imgurl.items()) if v}
json.dump(imgs,open(os.path.expanduser("~/dash/imgs.json"),"w"),separators=(",",":"))
print(f"OK shops={len(shops)} skus={len(skus)} orders={len(orders)} exps={len(exps)} imgs={len(imgs)}/{len(imgurl)} rets={len(rets)} invs={len(invs)} xato={errors}")
