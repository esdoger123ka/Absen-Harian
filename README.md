# Bot Absensi Morning Briefing RJW

Teknisi kirim foto ke bot (chat pribadi) → bot catat absensi ke Google Sheets +
simpan foto ke Drive → tiap hari kerja jam 09:00 bot kirim rekap ke grup.

---

## 1. Siapkan Google Sheet

Buat 1 spreadsheet baru. Bot akan otomatis membuat tab yang belum ada, tapi
minimal isi tab **`teknisi`** dengan daftar teknisi Anda:

| nama          | nik      | user_id | sektor |
|---------------|----------|---------|--------|
| Budi Santoso  | 12345    |         | 1      |
| Andi Wijaya   | 67890    |         | 2      |

- Kolom **user_id dikosongkan** — terisi otomatis saat teknisi daftar via bot.
- Ambil **SHEET_ID** dari URL: `docs.google.com/spreadsheets/d/`**`SHEET_ID`**`/edit`

## 2. Siapkan folder Drive untuk foto

Buat folder di Google Drive. Ambil **DRIVE_FOLDER_ID** dari URL folder:
`drive.google.com/drive/folders/`**`FOLDER_ID`**

## 3. Service Account (Google Cloud)

1. Buka console.cloud.google.com → buat project (atau pakai yang sudah ada).
2. Aktifkan **Google Sheets API** dan **Google Drive API**.
3. IAM & Admin → Service Accounts → buat baru → buat **key JSON** → unduh.
4. **Share Sheet dan folder Drive** ke email service account (…@….iam.gserviceaccount.com)
   dengan akses **Editor**. Tanpa langkah ini bot tidak bisa akses.

## 4. Bot Telegram

1. Chat @BotFather → `/newbot` → simpan **BOT_TOKEN**.
2. Set `/setprivacy` → **Disable** hanya jika ingin bot baca pesan grup.
   Untuk kasus ini (foto via chat pribadi) tidak wajib.

## 5. Deploy ke Railway

1. Push folder ini ke GitHub, hubungkan ke Railway (atau Railway CLI).
2. Di **Variables**, isi:

| Variable          | Nilai                                             |
|-------------------|---------------------------------------------------|
| `BOT_TOKEN`       | token dari BotFather                              |
| `SHEET_ID`        | ID Google Sheet                                   |
| `DRIVE_FOLDER_ID` | ID folder Drive                                   |
| `GOOGLE_CREDS_JSON` | **seluruh isi file JSON** service account (paste as-is) |
| `TIMEZONE`        | `Asia/Jakarta` (opsional)                         |
| `CUTOFF_HOUR`     | `9` (jam kirim rekap)                             |
| `ONTIME_HOUR`     | `8` (batas hadir tepat waktu)                     |
| `ONTIME_MINUTE`   | `30`                                              |
| `WORK_DAYS`       | `0,1,2,3,4,5` (Sen–Sab; 0=Senin)                  |
| `GROUP_CHAT_ID`   | kosongkan → pakai /setgrup                        |

3. Railway pakai `Procfile` (worker) otomatis. Deploy.

## 6. Aktivasi

1. Sebar link bot ke semua teknisi: minta mereka ketik **/start** lalu pilih nama.
2. Tambahkan bot ke grup morning briefing, lalu ketik **/setgrup** di grup itu.
3. Selesai. Teknisi kirim foto → tercatat. Jam 9 rekap otomatis masuk grup.

## Command
- `/start` — daftar / mulai
- `/status` — cek absen sendiri
- `/setgrup` — set grup tujuan report (ketik di grup)
- `/rekap` — kirim rekap sekarang (manual/test)

---

## Batasan yang perlu diketahui (jujur, bukan menakut-nakuti)
- Teknisi **wajib** /start bot dulu. Yang belum, tidak bisa kirim apa pun ke bot.
  Ini batasan API Telegram, bukan pilihan desain.
- Bot mengandalkan **satu foto = satu absen/hari**. Foto kedua ditolak.
- Foto tidak diverifikasi isinya (bot tidak cek apakah benar foto briefing).
  Kalau butuh anti-titip-absen, perlu tambahan (mis. cek lokasi/waktu EXIF) —
  belum termasuk di versi ini.
- Rekap dikirim sekali di jam cutoff. Teknisi yang absen setelah jam 9 tetap
  tercatat di Sheet, tapi tidak ikut di rekap yang sudah terkirim.
