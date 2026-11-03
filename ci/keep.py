#!/usr/bin/env python3
# Yangi faylni Pult'ga faqat u to'g'ri bo'lsa ko'chiradi (API ishlamasa yaxshi ma'lumot bo'sh fayl bilan almashmasin).
# Ishlatish: python3 ci/keep.py <manba> <manzil>
import json, os, shutil, sys

src, dst = sys.argv[1], sys.argv[2]
name = os.path.basename(dst)
try:
    d = json.load(open(src, encoding="utf-8"))
except Exception as x:
    print(f"o'tkazildi {name}: fayl yo'q yoki buzuq ({type(x).__name__})"); sys.exit(0)

ok = {
    "data.json": lambda d: bool(d.get("shops")) and bool(d.get("skus")),
    "imgs.json": lambda d: len(d) > 0,
    "wb.json": lambda d: bool(d.get("cabs")) and bool(d.get("rows") or d.get("items")),
    "today.json": lambda d: bool(d.get("shops")),
    "state.json": lambda d: bool(d.get("shops")),
}.get(name, lambda d: True)

try: good = ok(d)
except Exception: good = False
if good:
    shutil.copyfile(src, dst); print(f"yangilandi: {name}")
else:
    print(f"::warning::{name} bo'sh chiqdi — eski nusxa qoldirildi")
