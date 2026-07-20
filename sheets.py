"""
Lapisan akses data: Google Sheets (daftar teknisi, catatan absensi) + upload
foto ke Google Drive. Memakai satu service account.

Struktur Sheet yang diharapkan:
  Tab 'teknisi'  : kolom -> nama | nik | user_id | sektor
                   (user_id boleh kosong; diisi otomatis saat teknisi daftar)
  Tab 'absensi'  : kolom -> tanggal | nama | nik | sektor | jam | status | link_foto | user_id
  Tab 'config'   : kolom -> key | value   (menyimpan group_chat_id runtime)
"""
import io
import json
import time
import datetime as dt

import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

import config

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

_creds = Credentials.from_service_account_info(
    json.loads(config.GOOGLE_CREDS_JSON), scopes=_SCOPES
)
_gc = gspread.authorize(_creds)
_drive = build("drive", "v3", credentials=_creds)
_ss = _gc.open_by_key(config.SHEET_ID)


def _ws(tab_name):
    """Ambil worksheet; buat kalau belum ada dengan header default."""
    try:
        return _ss.worksheet(tab_name)
    except gspread.WorksheetNotFound:
        ws = _ss.add_worksheet(title=tab_name, rows=1000, cols=12)
        if tab_name == config.TAB_ABSENSI:
            ws.append_row(
                ["tanggal", "nama", "nik", "sektor", "jam",
                 "status", "link_foto", "user_id"]
            )
        elif tab_name == config.TAB_TEKNISI:
            ws.append_row(["nama", "nik", "user_id", "sektor"])
        elif tab_name == config.TAB_CONFIG:
            ws.append_row(["key", "value"])
        return ws


# ---------- Teknisi ----------
def get_all_teknisi():
    """Return list of dict: {nama, nik, user_id, sektor}."""
    return _ws(config.TAB_TEKNISI).get_all_records()


def find_teknisi_by_user_id(user_id):
    for row in get_all_teknisi():
        if str(row.get("user_id", "")).strip() == str(user_id):
            return row
    return None


def get_unregistered_names():
    """Nama teknisi yang belum punya user_id (belum daftar)."""
    return [r["nama"] for r in get_all_teknisi()
            if not str(r.get("user_id", "")).strip()]


def register_user_id(nama, user_id):
    """Isi user_id untuk baris teknisi dengan nama tertentu.
    Return dict teknisi kalau sukses, None kalau nama tak ditemukan."""
    ws = _ws(config.TAB_TEKNISI)
    records = ws.get_all_records()
    for idx, row in enumerate(records, start=2):  # baris 1 = header
        if row["nama"].strip().lower() == nama.strip().lower():
            # kolom user_id = kolom ke-3
            ws.update_cell(idx, 3, str(user_id))
            row["user_id"] = str(user_id)
            return row
    return None


# ---------- Absensi ----------
def already_absent_today(user_id, today_str):
    ws = _ws(config.TAB_ABSENSI)
    for row in ws.get_all_records():
        if (str(row.get("user_id", "")) == str(user_id)
                and row.get("tanggal") == today_str):
            return True
    return False


def record_absensi(tanggal, nama, nik, sektor, jam, status, link_foto, user_id):
    _ws(config.TAB_ABSENSI).append_row(
        [tanggal, nama, str(nik), sektor, jam, status, link_foto, str(user_id)]
    )


def get_absensi_for_date(today_str):
    return [r for r in _ws(config.TAB_ABSENSI).get_all_records()
            if r.get("tanggal") == today_str]


# ---------- Config runtime (group chat id) ----------
def set_config(key, value):
    ws = _ws(config.TAB_CONFIG)
    records = ws.get_all_records()
    for idx, row in enumerate(records, start=2):
        if row.get("key") == key:
            ws.update_cell(idx, 2, str(value))
            return
    ws.append_row([key, str(value)])


def get_config(key, default=None):
    for row in _ws(config.TAB_CONFIG).get_all_records():
        if row.get("key") == key:
            return row.get("value")
    return default


# ---------- Drive ----------
def upload_foto(image_bytes, filename, max_retry=3):
    """Upload foto ke folder Drive (resumable + retry), return link view.

    Resumable upload mengirim file dalam potongan dan bisa melanjutkan kalau
    koneksi putus di tengah -- ini mengatasi BrokenPipeError yang terjadi pada
    upload single-shot untuk file besar dari HP.
    """
    meta = {"name": filename, "parents": [config.DRIVE_FOLDER_ID]}

    last_err = None
    for attempt in range(1, max_retry + 1):
        try:
            media = MediaIoBaseUpload(
                io.BytesIO(image_bytes),
                mimetype="image/jpeg",
                chunksize=1024 * 1024,   # 1 MB per chunk
                resumable=True,
            )
            request = _drive.files().create(
                body=meta, media_body=media, fields="id"
            )
            response = None
            while response is None:
                _status, response = request.next_chunk()
            file_id = response["id"]

            _drive.permissions().create(
                fileId=file_id, body={"role": "reader", "type": "anyone"}
            ).execute()
            return f"https://drive.google.com/file/d/{file_id}/view"

        except (BrokenPipeError, ConnectionError, OSError) as e:
            last_err = e
            if attempt < max_retry:
                time.sleep(2 * attempt)   # backoff: 2s, 4s
                continue
            raise

    raise last_err
