#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "==> Mesut Video İndirici Backend Başlatılıyor..."

if ! command -v python3 >/dev/null 2>&1; then
  echo "HATA: python3 bulunamadı. Homebrew ile kurun: brew install python"
  exit 1
fi

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "HATA: ffmpeg bulunamadı. Video/ses birleştirme için gerekli."
  echo "Kurulum: brew install ffmpeg"
  exit 1
fi

if ! command -v node >/dev/null 2>&1 && ! command -v deno >/dev/null 2>&1; then
  echo "UYARI: node veya deno bulunamadı. YouTube bazı videolarda JS runtime isteyebilir (brew install deno)."
fi

# Check Python dependencies
if ! python3 -c "import fastapi, uvicorn, yt_dlp" >/dev/null 2>&1; then
  echo "==> Eksik Python paketleri tespit edildi. requirements.txt yükleniyor..."
  python3 -m pip install --upgrade -r requirements.txt
fi

# Create .env with a strong random API_KEY if not present
if [ ! -f ".env" ]; then
  if [ ! -f ".env.example" ]; then
    echo "HATA: .env.example dosyası bulunamadı."
    exit 1
  fi
  GENERATED_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
  python3 -c '
from pathlib import Path
import sys
key = sys.argv[1]
text = Path(".env.example").read_text(encoding="utf-8")
text = text.replace("API_KEY=buraya-guclu-bir-sifre-yazin", f"API_KEY={key}", 1)
Path(".env").write_text(text, encoding="utf-8")
' "$GENERATED_KEY"
  chmod 600 .env
  echo ""
  echo "================================================================="
  echo " İlk kurulum tamamlandı! backend/.env dosyası oluşturuldu."
  echo " Arayüzde (indir.mesutpeker.com) kullanacağınız API Anahtarı:"
  echo ""
  echo "   $GENERATED_KEY"
  echo ""
  echo " (Bu anahtarı güvenli bir yere kopyalayın.)"
  echo "================================================================="
  echo ""
fi

HOST_VAL="$(python3 -c '
from config import Settings
s = Settings.from_env(require_api_key=True)
print(s.host)
')"
PORT_VAL="$(python3 -c '
from config import Settings
s = Settings.from_env(require_api_key=True)
print(s.port)
')"

echo "==> Dinleniyor: http://${HOST_VAL}:${PORT_VAL}"
echo "==> Durdurmak için Ctrl+C tuşlayın."
exec python3 -m uvicorn app:app --host "$HOST_VAL" --port "$PORT_VAL"
