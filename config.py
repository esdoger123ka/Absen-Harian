"""
Konfigurasi terpusat. Semua nilai sensitif diambil dari environment variable
(diset di Railway → Variables), bukan hardcode di kode.
"""
import os

# --- Wajib diisi di Railway Variables ---
BOT_TOKEN = os.environ["BOT_TOKEN"]                 # token dari @BotFather
SHEET_ID = os.environ["SHEET_ID"]                   # ID Google Sheet (dari URL)
# credentials service account: isi seluruh JSON sebagai satu env var
GOOGLE_CREDS_JSON = os.environ["GOOGLE_CREDS_JSON"]

# --- Pengaturan operasional ---
TIMEZONE = os.environ.get("TIMEZONE", "Asia/Jakarta")

# Jam kompilasi & kirim report (format 24 jam)
CUTOFF_HOUR = int(os.environ.get("CUTOFF_HOUR", "9"))
CUTOFF_MINUTE = int(os.environ.get("CUTOFF_MINUTE", "0"))

# Batas jam "hadir tepat waktu". Absen setelah ini ditandai TELAT (masih dicatat).
# Set sama dengan cutoff kalau tidak mau ada kategori telat.
ONTIME_HOUR = int(os.environ.get("ONTIME_HOUR", "8"))
ONTIME_MINUTE = int(os.environ.get("ONTIME_MINUTE", "30"))

# chat_id grup tujuan report. Bisa diisi manual, atau dideteksi via /setgrup.
# Kalau kosong, report tidak terkirim sampai /setgrup dijalankan di grup.
GROUP_CHAT_ID = os.environ.get("GROUP_CHAT_ID", "")

# Hari kerja report dikirim (0=Senin .. 6=Minggu). Default Senin-Sabtu.
WORK_DAYS = [int(d) for d in os.environ.get("WORK_DAYS", "0,1,2,3,4,5").split(",")]

# Nama tab di Google Sheet
TAB_TEKNISI = "teknisi"
TAB_ABSENSI = "absensi"
TAB_CONFIG = "config"   # untuk simpan group_chat_id yang dideteksi runtime
TAB_JADWAL = "jadwal"   # acuan siapa yang dijadwalkan hadir per tanggal
