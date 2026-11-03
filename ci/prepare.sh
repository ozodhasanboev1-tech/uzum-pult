#!/usr/bin/env bash
# Ish joyini tayyorlaydi: skriptlar va tannarx -> $HOME, joriy Pult fayllari -> _site/
# Kalitlar faqat GitHub Secrets'dan (env) o'qiladi, hech qayerga yozilmaydi.
set -u
cd "$GITHUB_WORKSPACE"

cp scripts/*.py "$HOME/"
cp data/tannarx.csv "$HOME/tannarx.csv"
cp data/wb_tannarx.csv "$HOME/wb_tannarx.csv"

# Ixtiyoriy: Google Sheets "Internetda chop etish -> CSV" havolasi (Secrets: TANNARX_URL, WB_TANNARX_URL)
fetch_csv() {  # $1 = url, $2 = manzil
  [ -n "$1" ] || return 0
  if curl -fsSL --retry 3 --max-time 60 "$1" -o /tmp/t.csv && head -1 /tmp/t.csv | grep -qi "sku\|nmid\|kabinet"; then
    cp /tmp/t.csv "$2"; echo "tannarx yangilandi: $(basename "$2")"
  else
    echo "::warning::$(basename "$2") havoladan olinmadi — repodagi nusxa ishlatiladi"
  fi
}
fetch_csv "${TANNARX_URL:-}" "$HOME/tannarx.csv"
fetch_csv "${WB_TANNARX_URL:-}" "$HOME/wb_tannarx.csv"

# Pult: sahifa repodan, ma'lumot fayllari — hozirgi saytdan (bo'lmasa seed/ dan)
rm -rf _site && mkdir -p _site
cp site/* _site/
for f in data.json wb.json imgs.json today.json state.json; do
  if curl -fsSL --retry 3 --max-time 120 "${PULT_URL%/}/$f?nocache=$(date +%s)" -o "_site/$f" && python3 -c "import json,sys;json.load(open(sys.argv[1]))" "_site/$f" 2>/dev/null; then
    echo "saytdan olindi: $f"
  elif [ -f "seed/$f" ]; then
    cp "seed/$f" "_site/$f"; echo "seed'dan olindi: $f"
  else
    rm -f "_site/$f"
  fi
done
mkdir -p "$HOME/dash"
