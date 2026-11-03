#!/usr/bin/env bash
# Ish bajarilmasa Telegram'ga qisqa ogohlantirish. $1 = matn
[ -n "${TG_TOKEN:-}" ] && [ -n "${TG_CHAT:-}" ] || exit 0
URL="${GITHUB_SERVER_URL}/${GITHUB_REPOSITORY}/actions/runs/${GITHUB_RUN_ID}"
curl -fsS --max-time 30 "https://api.telegram.org/bot${TG_TOKEN}/sendMessage" \
  --data-urlencode "chat_id=${TG_CHAT}" \
  --data-urlencode "text=⚠️ $1
Tafsilot: ${URL}" >/dev/null || true
