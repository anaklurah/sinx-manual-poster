# 🚀 Sin'X Manual Poster

Aplikasi khusus untuk **publikasi video yang sudah diedit secara manual** langsung ke berbagai platform media sosial secara serentak (YouTube Shorts, TikTok, Instagram Reels, Facebook Reels, Twitter/X, Febspot, Upscrolled) dengan dukungan **Jadwal Tayang (Scheduler)** dan **Multi-Akun Karyawan**.

Berbeda dengan bot auto-scraper, aplikasi ini didesain khusus untuk alur kerja kreator & editor video:
1. **Upload Video Manual (.mp4, .mov, .webm)** via browser (drag & drop).
2. **Form Konten Lengkap**: Masukkan Judul, Caption/Deskripsi, Hashtags, dan centang platform tujuan yang diinginkan.
3. **Pilihan Waktu**:
   - ⚡ **Post Sekarang (Instan)**: Langsung mengunggah serentak ke platform yang dipilih.
   - ⏰ **Jadwalkan Post**: Pilih tanggal dan jam tayang, background scheduler otomatis memposting saat waktunya tiba.
4. **Multi-User / Karyawan**: Akun admin dan karyawan terpisah dengan antrean dan cookies masing-masing.
5. **Notifikasi Telegram**: Laporan otomatis dengan tautan langsung ke video yang berhasil dipublikasi.
6. **Live Logs**: Pemantauan real-time proses browser Playwright.

---

## 📁 Struktur Direktori

```
sinx-manual-poster/
├── assets/
│   └── profiles/           # File cookies (.json / .txt) & profil sesi browser
├── data/                   # Database SQLite (manual_poster.db)
├── uploads/                # Berkas video yang diunggah
├── poster/
│   ├── config.py           # Konfigurasi sistem
│   ├── auth.py             # Otentikasi user & audit log
│   ├── db/
│   │   ├── models.py       # Skema database SQLite
│   │   └── queue.py        # Query operasi antrean posting
│   ├── modules/
│   │   ├── publisher/      # Browser automation Playwright per platform
│   │   ├── uploader.py     # Orkestrator upload multi-platform
│   │   ├── scheduler.py    # Background worker pemantau jadwal
│   │   └── telegram_notifier.py # Notifikasi Telegram
│   └── utils/
│       ├── logger.py       # Logging sistem
│       └── human_delay.py  # Anti-deteksi delay interaksi manusia
├── web/
│   ├── server.py           # Backend FastAPI & REST API
│   └── static/             # Frontend Dashboard (3D Dark Claymorphism)
├── config.yaml             # File konfigurasi
├── requirements.txt        # Dependensi Python
├── manage.py               # CLI runner
└── run.bat                 # 1-klik jalan di Windows
```

---

## 🛠️ Instalasi & Menjalankan

### 1. Di Komputer Lokal (Windows)

1. Pastikan Python 3.10+ sudah terpasang.
2. Buka terminal di folder project dan pasang dependensi:
   ```powershell
   pip install -r requirements.txt
   playwright install chromium firefox
   ```
3. Jalankan aplikasi:
   ```powershell
   python manage.py run-web
   # atau klik ganda berkas run.bat
   ```
4. Buka browser di alamat:
   👉 **`http://localhost:8090`**

### 2. Login Pertama Kali (Default Admin)

- **Username**: `admin`
- **Password**: `admin123`
*(Anda dapat mengganti password atau membuat akun karyawan baru di tab Kelola Karyawan).*

---

## 📱 Panduan Akun & Cookies Sosmed

Sebelum memposting video, pastikan sesi login atau cookies platform sudah diunggah:
1. Buka tab **Akun & Cookies**.
2. Pada kartu platform (misal **YouTube**, **TikTok**, atau **Instagram**):
   - Klik tombol **Upload Cookies (.json / .txt)** untuk mengunggah cookies dari browser Anda.
   - Atau klik **Upload Profil (.zip)** jika menggunakan sesi browser persisten utuh.
3. Setelah terunggah, status akan otomatis berubah menjadi **Sesi Aktif**.

---

## 🤖 Konfigurasi Bot Telegram (Opsional)

Untuk menerima tautan langsung postingan yang berhasil diunggah:
1. Masuk ke tab **Konfigurasi**.
2. Aktifkan **Notifikasi Bot Telegram**.
3. Masukkan **Bot Token** (dari @BotFather) dan **Chat ID**.
4. Klik **Tes Kirim Pesan** untuk memverifikasi koneksi.
5. Klik **Simpan Pengaturan**.

---

## 💻 Perintah CLI (manage.py)

| Perintah | Deskripsi |
| :--- | :--- |
| `python manage.py run-web` | Menjalankan Web Dashboard dan background scheduler |
| `python manage.py create-user -u <user> -p <pass>` | Membuat akun karyawan baru |
| `python manage.py list-users` | Menampilkan daftar akun terdaftar |
| `python manage.py status` | Menampilkan statistik jumlah postingan |
| `python manage.py reset-stuck` | Meriset antrean yang terhenti |
| `python manage.py info` | Menampilkan info hardware dan direktori |
