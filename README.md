# Uzum Pult — Claude'siz avtomatik hisobot

Hamma narsani GitHub Actions bajaradi:

- **Soatlik** (07:07–23:07): Telegram'ga soatlik hisobot va jadval rasmi yuboriladi, Pult'dagi "Bugun" yangilanadi.
- **Kunlik** (taxminan 07:40): kechagi qisqa hisobot va diagramma Telegram'ga yuboriladi. Pult to'liq yangilanadi: Uzum, WB, ostatka, hisob-kitob. Kunlik matn `hisobotlar/` papkasiga saqlanadi.
- Biror qadam ishlamasa, Telegram'ga "⚠️ ... ishlamadi" degan xabar keladi.
- Pult manzili: `https://<github-login>.github.io/uzum-pult/`

## O'rnatish (bir marta)

1. github.com'da akkaunt oching. **New repository** ni bosing: nomi `uzum-pult`, turi **Private**.
2. **Add file → Upload files** ni bosing. Arxivdagi barcha fayl va papkalarni tortib tashlang, keyin **Commit**.
   - `.github/workflows/` papkasi yashirin bo'lgani uchun yuklanmay qolishi mumkin. Unda **Add file → Create new file** ni bosing. Nomiga `.github/workflows/soatlik.yml` yozing va fayl matnini qo'ying. `kunlik.yml` uchun ham shunday qiling.
3. **Settings → Secrets and variables → Actions → New repository secret** ga kiring. Har birini alohida qo'shing, qiymatlari Claude'dagi "Uzum" muhitidagi bilan bir xil:
   `UZUM_SA_TIMSON`, `UZUM_CLEO`, `WB_CLEO`, `WB_NASIROV`, `TG_TOKEN`, `TG_CHAT`.
4. **Settings → Pages → Build and deployment → Source: GitHub Actions** ni tanlang.
   - Repo yopiq (Private) bo'lsa, Pages faqat **GitHub Pro** (oyiga 4$) bilan ishlaydi.
   - Bepul yo'li: repo'ni ochiq (Public) qilish. Lekin unda `data/` va `seed/` fayllarini (tannarxlar) hamma ko'ra oladi.
5. **Actions** bo'limiga kiring: avval **Uzum kunlik → Run workflow**, keyin **Uzum soatlik → Run workflow**. Telegram va Pult manzilini tekshiring.

## Tannarxni yangilash
- `data/tannarx.csv` (Uzum) va `data/wb_tannarx.csv` (WB) ni GitHub'da ochib ✏️ bilan tahrirlang.
- Yoki Google Sheets'da **Fayl → Ulashish → Internetda chop etish → CSV** ni tanlang. Hosil bo'lgan havolani `TANNARX_URL` / `WB_TANNARX_URL` secret qilib qo'shing — har ishga tushishda o'sha jadvaldan olinadi.

## Eslatma
- GitHub jadvaldagi vaqtni 5–15 daqiqa kechiktirishi mumkin.
- Faqat o'qish so'rovlari yuboriladi; kalitlar faqat Secrets'da turadi va hech qayerga yozilmaydi.
- Haftalik va oylik tahliliy hisobotlarni hozircha Claude tayyorlaydi.
