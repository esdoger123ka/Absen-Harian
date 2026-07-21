"""
Bot Absensi Morning Briefing — RJW.

Flow:
  1. Teknisi /start bot (wajib sekali).
  2. Kalau user_id belum dikenal -> bot minta pilih nama dari daftar (registrasi).
     user_id tersimpan ke Sheet tab 'teknisi'.
  3. Teknisi kirim FOTO -> bot cek identitas, simpan foto ke Drive, catat
     absensi di Sheet dengan status HADIR / TELAT berdasarkan jam.
  4. Setiap hari kerja jam CUTOFF (default 09:00) -> bot kompilasi absensi hari
     itu dan kirim rekap ke grup: yang hadir, yang telat, dan yang belum absen.

Command:
  /start    - mulai / registrasi
  /status   - cek status absen sendiri hari ini
  /setgrup  - (ketik DI GRUP) daftarkan grup sebagai tujuan report
  /rekap    - (admin) paksa kirim rekap sekarang
"""
import logging
import datetime as dt

import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters,
)

import config
import sheets

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("absensi")

TZ = pytz.timezone(config.TIMEZONE)


def _now():
    return dt.datetime.now(TZ)


def _today_str():
    return _now().strftime("%Y-%m-%d")


# ---------------- Registrasi ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    tek = sheets.find_teknisi_by_user_id(user.id)
    if tek:
        await update.message.reply_text(
            f"Halo {tek['nama']} (Sektor {tek.get('sektor','-')}).\n"
            f"Kirim *foto* untuk absen morning briefing.\n"
            f"Cek status: /status",
            parse_mode="Markdown",
        )
        return
    await _kirim_menu_daftar(update, context)


async def _kirim_menu_daftar(update, context):
    names = sheets.get_unregistered_names()
    if not names:
        await update.effective_message.reply_text(
            "Semua nama sudah terdaftar / nama Anda tidak ada di daftar teknisi.\n"
            "Hubungi koordinator (Bagaskara) untuk didaftarkan."
        )
        return
    # Telegram inline keyboard: max ~100 tombol; kelompokkan 1 kolom biar rapi.
    buttons = [
        [InlineKeyboardButton(n, callback_data=f"reg::{n}")]
        for n in names[:90]
    ]
    await update.effective_message.reply_text(
        "Pilih nama Anda untuk mendaftar:",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def on_register_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    nama = query.data.split("::", 1)[1]
    user = update.effective_user

    # cegah 1 user_id klaim >1 nama
    if sheets.find_teknisi_by_user_id(user.id):
        await query.edit_message_text("Anda sudah terdaftar sebelumnya.")
        return

    tek = sheets.register_user_id(nama, user.id)
    if tek:
        await query.edit_message_text(
            f"Terdaftar sebagai *{nama}* (Sektor {tek.get('sektor','-')}).\n"
            f"Sekarang kirim *foto* untuk absen.",
            parse_mode="Markdown",
        )
    else:
        await query.edit_message_text(
            "Gagal mendaftar (nama tidak ditemukan). Coba /start lagi."
        )


# ---------------- Absensi via foto ----------------
async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    tek = sheets.find_teknisi_by_user_id(user.id)
    if not tek:
        await update.message.reply_text(
            "Anda belum terdaftar. Ketik /start dulu untuk pilih nama."
        )
        await _kirim_menu_daftar(update, context)
        return

    today = _today_str()
    if sheets.already_absent_today(user.id, today):
        await update.message.reply_text("Anda sudah absen hari ini. ✅")
        return

    now = _now()
    jam = now.strftime("%H:%M:%S")

    # status berdasarkan ambang tepat waktu
    ontime = now.replace(hour=config.ONTIME_HOUR, minute=config.ONTIME_MINUTE,
                         second=0, microsecond=0)
    status = "HADIR" if now <= ontime else "TELAT"

    # Foto TIDAK disimpan permanen. Kita simpan file_id-nya saja (ringan, tahan
    # restart). Jam 9 bot mengambil ulang foto via file_id dan menyusun kolase.
    photo = update.message.photo[-1]
    file_id = photo.file_id

    sheets.record_absensi(
        tanggal=today, nama=tek["nama"], nik=tek.get("nik", ""),
        sektor=tek.get("sektor", ""), jam=jam, status=status,
        link_foto="", user_id=user.id, file_id=file_id,
    )

    emoji = "✅" if status == "HADIR" else "⚠️"
    await update.message.reply_text(
        f"{emoji} Absen tercatat.\n"
        f"Nama: {tek['nama']}\nJam: {jam}\nStatus: {status}"
    )


# ---------------- Grup & rekap ----------------
async def set_grup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type not in ("group", "supergroup"):
        await update.message.reply_text("Perintah ini harus diketik DI DALAM grup.")
        return
    sheets.set_config("group_chat_id", chat.id)
    await update.message.reply_text(
        f"Grup ini didaftarkan sebagai tujuan report absensi.\n(chat_id: {chat.id})"
    )


def _resolve_group_id():
    return config.GROUP_CHAT_ID or sheets.get_config("group_chat_id")


def _build_rekap_text(today):
    records = sheets.get_absensi_for_date(today)
    all_tek = sheets.get_all_teknisi()
    jadwal_names = sheets.get_jadwal_for_date(today)   # nama dijadwalkan hari ini

    hadir = [r for r in records if r.get("status") == "HADIR"]
    telat = [r for r in records if r.get("status") == "TELAT"]

    # peta nama -> sektor (untuk menampilkan sektor pada 'belum absen')
    sektor_by_name = {t["nama"].strip().lower(): t.get("sektor", "-")
                      for t in all_tek}

    # nama yang sudah absen hari ini (case-insensitive)
    absen_names = {str(r.get("nama", "")).strip().lower() for r in records}

    # BELUM ABSEN = dijadwalkan hari ini TAPI belum absen
    belum = [n for n in jadwal_names
             if n.strip().lower() not in absen_names]

    tgl_id = _now().strftime("%d %B %Y")
    lines = [f"📋 *REKAP MORNING BRIEFING RJW*", f"Tanggal: {tgl_id}", ""]

    lines.append(f"✅ *HADIR ({len(hadir)})*")
    for r in sorted(hadir, key=lambda x: x.get("sektor", "")):
        lines.append(f"  • {r['nama']} — {r.get('sektor','-')} ({r['jam'][:5]})")
    if not hadir:
        lines.append("  -")

    lines.append("")
    lines.append(f"⚠️ *TELAT ({len(telat)})*")
    for r in sorted(telat, key=lambda x: x.get("sektor", "")):
        lines.append(f"  • {r['nama']} — {r.get('sektor','-')} ({r['jam'][:5]})")
    if not telat:
        lines.append("  -")

    lines.append("")
    if not jadwal_names:
        # jadwal hari ini belum diisi -> beri tahu, jangan tampilkan angka menyesatkan
        lines.append("❌ *BELUM ABSEN (?)*")
        lines.append("  ⚠️ Jadwal hari ini belum diisi di tab 'jadwal'.")
    else:
        lines.append(f"❌ *BELUM ABSEN ({len(belum)})*")
        for nama in sorted(belum, key=lambda n: sektor_by_name.get(n.strip().lower(), "")):
            sektor = sektor_by_name.get(nama.strip().lower(), "-")
            lines.append(f"  • {nama} — {sektor}")
        if not belum:
            lines.append("  -")

    lines.append("")
    if jadwal_names:
        lines.append(f"Total hadir: {len(records)}/{len(jadwal_names)} dijadwalkan")
    else:
        lines.append(f"Total absen: {len(records)}")
    return "\n".join(lines)


async def _buat_kolase(context, records):
    """Ambil foto dari file_id tiap absensi, susun jadi satu kolase grid.
    Return BytesIO (JPEG) atau None kalau tidak ada foto.

    Foto diambil ulang dari Telegram via file_id -- tidak ada penyimpanan
    permanen. Tiap sel diberi label nama di bawahnya.
    """
    from io import BytesIO
    from PIL import Image, ImageDraw, ImageFont

    # kumpulkan (nama, bytes foto)
    fotos = []
    for r in records:
        fid = str(r.get("file_id", "")).strip()
        if not fid:
            continue
        try:
            tg_file = await context.bot.get_file(fid)
            data = bytes(await tg_file.download_as_bytearray())
            img = Image.open(BytesIO(data)).convert("RGB")
            fotos.append((r.get("nama", "-"), img))
        except Exception:
            log.exception("Gagal ambil foto file_id=%s", fid[:20])

    if not fotos:
        return None

    # ukuran sel & grid
    cell_w, cell_h = 300, 300           # area foto per sel
    label_h = 26                        # ruang nama di bawah tiap foto
    pad = 6
    n = len(fotos)
    cols = min(6, max(1, int(n ** 0.5) + 1))   # grid mendekati persegi, maks 6 kolom
    rows = (n + cols - 1) // cols

    total_w = cols * cell_w + (cols + 1) * pad
    total_h = rows * (cell_h + label_h) + (rows + 1) * pad
    canvas = Image.new("RGB", (total_w, total_h), (245, 245, 245))
    draw = ImageDraw.Draw(canvas)
    font = _load_font(16)

    for idx, (nama, img) in enumerate(fotos):
        rr, cc = divmod(idx, cols)
        x = pad + cc * (cell_w + pad)
        y = pad + rr * (cell_h + label_h + pad)

        # fit foto ke dalam sel (crop tengah agar rasio pas)
        img_fit = _crop_center(img, cell_w, cell_h)
        canvas.paste(img_fit, (x, y))

        # label nama (dipotong kalau kepanjangan)
        label = nama if len(nama) <= 22 else nama[:20] + "…"
        draw.text((x + 4, y + cell_h + 4), label, fill=(20, 20, 20), font=font)

    out = BytesIO()
    canvas.save(out, format="JPEG", quality=80)
    out.seek(0)
    out.name = "kolase.jpg"
    return out


def _load_font(size):
    """Cari font TrueType di beberapa lokasi umum; fallback ke default Pillow."""
    from PIL import ImageFont
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
        "/nix/store/dejavu-fonts/share/fonts/truetype/DejaVuSans.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _crop_center(img, w, h):
    """Resize+crop tengah agar mengisi w×h tanpa distorsi."""
    from PIL import Image
    src_ratio = img.width / img.height
    dst_ratio = w / h
    if src_ratio > dst_ratio:
        new_h = h
        new_w = int(h * src_ratio)
    else:
        new_w = w
        new_h = int(w / src_ratio)
    img = img.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - w) // 2
    top = (new_h - h) // 2
    return img.crop((left, top, left + w, top + h))


async def kirim_rekap(context: ContextTypes.DEFAULT_TYPE):
    group_id = _resolve_group_id()
    if not group_id:
        log.warning("group_chat_id belum diset; rekap tidak dikirim.")
        return
    await _kirim_rekap_ke(context, int(group_id))
    log.info("Rekap terkirim ke grup %s", group_id)


async def _kirim_rekap_ke(context, chat_id):
    """Kirim teks rekap + kolase foto ke chat_id."""
    today = _today_str()
    records = sheets.get_absensi_for_date(today)
    text = _build_rekap_text(today)

    # kirim teks rekap dulu
    await context.bot.send_message(chat_id, text, parse_mode="Markdown")

    # lalu kolase foto (kalau ada)
    try:
        kolase = await _buat_kolase(context, records)
        if kolase:
            await context.bot.send_photo(
                chat_id, photo=kolase,
                caption=f"📸 Kolase foto absen — {len(records)} peserta",
            )
    except Exception:
        log.exception("Gagal membuat/mengirim kolase")


async def rekap_manual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/rekap — kirim rekap sekarang (untuk test / kebutuhan mendadak)."""
    group_id = _resolve_group_id()
    if not group_id:
        await update.message.reply_text(
            "Grup tujuan belum diset. Ketik /setgrup di grup dulu."
        )
        return
    await update.message.reply_text("Menyusun rekap + kolase, mohon tunggu…")
    await _kirim_rekap_ke(context, int(group_id))
    await update.message.reply_text("Rekap dikirim ke grup.")


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    tek = sheets.find_teknisi_by_user_id(user.id)
    if not tek:
        await update.message.reply_text("Anda belum terdaftar. Ketik /start.")
        return
    if sheets.already_absent_today(user.id, _today_str()):
        await update.message.reply_text("Anda SUDAH absen hari ini. ✅")
    else:
        await update.message.reply_text("Anda BELUM absen hari ini. Kirim foto.")


# ---------------- Scheduler ----------------
async def _daily_job(context: ContextTypes.DEFAULT_TYPE):
    if _now().weekday() in config.WORK_DAYS:
        await kirim_rekap(context)


def main():
    app = Application.builder().token(config.BOT_TOKEN).build()

    # start, status, dan foto HANYA diproses di chat pribadi (bukan grup)
    priv = filters.ChatType.PRIVATE
    app.add_handler(CommandHandler("start", start, filters=priv))
    app.add_handler(CommandHandler("status", status, filters=priv))
    # setgrup & rekap memang dijalankan di grup, jadi tidak dibatasi
    app.add_handler(CommandHandler("setgrup", set_grup))
    app.add_handler(CommandHandler("rekap", rekap_manual))
    app.add_handler(CallbackQueryHandler(on_register_choice, pattern=r"^reg::"))
    # foto absen hanya diterima dari chat pribadi
    app.add_handler(MessageHandler(filters.PHOTO & priv, on_photo))

    # jadwal harian jam cutoff
    cutoff = dt.time(hour=config.CUTOFF_HOUR, minute=config.CUTOFF_MINUTE,
                     tzinfo=TZ)
    app.job_queue.run_daily(_daily_job, time=cutoff)
    log.info("Bot start. Rekap harian jam %02d:%02d %s",
             config.CUTOFF_HOUR, config.CUTOFF_MINUTE, config.TIMEZONE)

    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
