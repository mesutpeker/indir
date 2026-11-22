# Mesut Video İndirici (`indir.mesutpeker.com`)

**YouTube, X (Twitter), Instagram ve Facebook** bağlantılarını yapıştırıp video veya ses olarak indirmenizi sağlayan, **GitHub Pages + Cloudflare Tunnel + `yt-dlp` / `ffmpeg`** tabanlı kişisel video indirme uygulaması.

- **Ön Yüz (GitHub Pages — `https://indir.mesutpeker.com`):** Statik PWA arayüzü. Hiçbir gizli anahtar barındırmaz; kendi API anahtarınız yalnızca tarayıcınızın `localStorage` alanında saklanır.
- **Arka Uç (Mac veya 7/24 Sunucu — `https://api-indir.mesutpeker.com`):** FastAPI + `yt-dlp` + `ffmpeg` tabanlı asenkron indirme servisi. İndirilen dosyalar en fazla 15 dakika sonra (veya "Sunucudan Sil"e bastığınızda) otomatik silinir.

---

## Proje Yapısı

```text
mesut-video-downloader/
├── .github/workflows/deploy-pages.yml  # GitHub Pages otomatik yayınlama
├── frontend/                           # GitHub Pages'e giden statik web uygulaması (PWA)
│   ├── CNAME                           # indir.mesutpeker.com
│   ├── index.html
│   ├── styles.css
│   ├── app.js
│   ├── manifest.webmanifest
│   ├── sw.js
│   └── icon.svg
├── backend/                            # yt-dlp + ffmpeg API sunucusu
│   ├── app.py
│   ├── config.py
│   ├── downloader.py
│   ├── start-mac.sh                    # Mac için tek komutla başlatma betiği
│   ├── Dockerfile
│   ├── docker-compose.yml              # Opsiyonel cloudflared & PO Token yan servisi
│   ├── .env.example
│   └── requirements.txt
└── README.md
```

---

## 1. Mac’te Hemen Yerel Test

İlk kurulumda `start-mac.sh` otomatik olarak `backend/.env` dosyasını ve güçlü bir `API_KEY` üretip ekrana yazar:

```bash
cd backend
./start-mac.sh
```

İkinci bir terminalde ön yüzü yerelde açın:

```bash
cd frontend
python3 -m http.server 5500
```

Tarayıcıdan `http://localhost:5500` adresine gidin:
- **Sunucu Adresi:** `http://localhost:8000`
- **API Anahtarı:** Terminale yazdırılan `API_KEY` değeri.

---

## 2. GitHub’a Yükleme ve GitHub Pages (`indir.mesutpeker.com`)

1. GitHub’da yeni bir depo oluşturun (ör. `video-downloader`). Public repo kullanabilirsiniz — arayüzde hiçbir gizli bilgi yoktur (`API_KEY` yalnızca kendi sunucunuzda ve kendi tarayıcınızda durur).
2. Projeyi gönderin:

```bash
git init
git add .
git commit -m "Kişisel video indirici ilk sürüm"
git branch -M main
git remote add origin https://github.com/<KULLANICI_ADINIZ>/video-downloader.git
git push -u origin main
```

3. GitHub deposunda **Settings → Pages → Build and deployment** bölümünden **Source: GitHub Actions** seçin.
4. **Custom domain** alanına `indir.mesutpeker.com` yazıp kaydedin (TLS sertifikası DNS yayıldıktan sonra oluşunca **Enforce HTTPS** seçeneğini işaretleyin).

---

## 3. Cloudflare DNS + Cloudflare Tunnel Kurulumu

### A) `indir.mesutpeker.com` için DNS Kaydı (GitHub Pages)
Cloudflare Dashboard → `mesutpeker.com` → **DNS → Records** bölümünden ekleyin:

- **Type:** `CNAME`
- **Name:** `indir`
- **Target:** `<KULLANICI_ADINIZ>.github.io`
- **Proxy status:** Proxied (Turuncu bulut) — *(Cloudflare Access kullanacaksanız Proxied olmalı; aksi halde DNS only de çalışır.)*

### B) `api-indir.mesutpeker.com` için Cloudflare Tunnel (Mac / Ev Sunucusu)
Port açmadan güvenli HTTPS tüneli için:

1. Mac’e `cloudflared` kurun ve giriş yapın:
   ```bash
   brew install cloudflared
   cloudflared tunnel login
   ```
2. Tüneli oluşturun ve DNS kaydını bağlayın:
   ```bash
   cloudflared tunnel create mesut-video-api
   cloudflared tunnel route dns mesut-video-api api-indir.mesutpeker.com
   ```
3. `~/.cloudflared/config.yml` dosyasını oluşturun (`<TUNNEL_UUID>` değerini yukarıdaki çıktıdan alın):
   ```yaml
   tunnel: <TUNNEL_UUID>
   credentials-file: /Users/mehmetmesutpeker/.cloudflared/<TUNNEL_UUID>.json

   ingress:
     - hostname: api-indir.mesutpeker.com
       service: http://127.0.0.1:8000
     - service: http_status:404
   ```
4. İki terminalle (veya arka plan servisi olarak) çalıştırın:
   ```bash
   # Terminal 1 (API)
   cd backend && ./start-mac.sh

   # Terminal 2 (Tünel)
   cloudflared tunnel run mesut-video-api
   ```
   *(İsterseniz `sudo cloudflared service install` veya Cloudflare Zero Trust Dashboard → Networks → Tunnels üzerinden token ile yönetilen tünel kurabilirsiniz.)*

---

## 4. (İsteğe Bağlı) Cloudflare Zero Trust Access ile Arayüzü Kilitleme

`https://indir.mesutpeker.com` sayfasını internette başkalarının görmesini bile istemiyorsanız (Cloudflare Free planda 50 kullanıcıya kadar ücretsizdir):

1. **Cloudflare Zero Trust → Access → Applications → Add an application → Self-hosted** seçin.
2. Application domain olarak **`indir.mesutpeker.com`** girin.
3. Policy olarak sadece kendi e-posta adresinize izin verin (ör. `Emails: sizin@email.com` veya Google OAuth).

> **ÖNEMLİ:** Access politikasını **yalnızca `indir.mesutpeker.com` için** aktif edin; **`api-indir.mesutpeker.com` için Access login sayfası açmayın.** Aksi halde tarayıcıdaki CORS ön istekleri (`OPTIONS`) Cloudflare giriş ekranına yönlendirilir ve API çağrıları engellenir. API tarafı zaten `X-API-Key` ve sıkı `ALLOWED_ORIGINS` (`https://indir.mesutpeker.com`) ile korunmaktadır.

---

## 5. İsteğe Bağlı Çerez Ayarı (Giriş Gerektiren IG / FB / YT Videoları)

Yaş sınırlı YouTube videoları veya giriş gerektiren Instagram/Facebook gönderileri için `backend/.env` içinde:

- **Mac’te doğrudan tarayıcı çerezi kullanmak için:**
  ```env
  COOKIES_FROM_BROWSER=chrome
  ```
  *(Desteklenen değerler: `chrome`, `safari`, `firefox`, `edge`, `brave`)*
- **Docker / Sunucu ortamında `cookies.txt` kullanmak için:**
  ```env
  COOKIES_FILE=./cookies.txt
  ```

---

## 6. Mac Kapalıyken 7/24 Kullanım (Docker / Raspberry Pi / VPS)

Aynı projeyi evdeki sürekli açık bir Raspberry Pi’ye veya VPS’e taşımak için:

```bash
cd backend
cp .env.example .env
# .env icinde API_KEY ve isterseniz CLOUDFLARE_TUNNEL_TOKEN ayarlayin
docker compose --profile tunnel up -d
```

Bulut/VPS IP adresinde YouTube bot kontrolü (`Sign in to confirm you're not a bot`) çıkarsa `backend/.env` içinde `PO_TOKEN_BASE_URL=http://pot-provider:4416` satırını açıp PO Token yan servisiyle birlikte başlatabilirsiniz:

```bash
docker compose --profile tunnel --profile pot up -d
```

Ön yüz tarafında (`indir.mesutpeker.com`) hiçbir değişiklik yapmanız gerekmez; Cloudflare Tunnel aynı `api-indir.mesutpeker.com` adresini yeni sunucuya yönlendirdiğiniz anda tüm cihazlarınızdan çalışmaya devam eder.
