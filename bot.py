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

    # ambil foto resolusi tertinggi
    photo = update.message.photo[-1]
    tg_file = await context.bot.get_file(photo.file_id)
    image_bytes = bytes(await tg_file.download_as_bytearray())

    fname = f"{today}_{tek['nama'].replace(' ', '_')}.jpg"
    try:
        link = sheets.upload_foto(image_bytes, fname)
    except Exception as e:
        log.exception("Upload Drive gagal")
        link = "(upload gagal)"

    sheets.record_absensi(
        tanggal=today, nama=tek["nama"], nik=tek.get("nik", ""),
        sektor=tek.get("sektor", ""), jam=jam, status=status,
        link_foto=link, user_id=user.id,
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

    absen_uid = {str(r.get("user_id")) for r in records}
    hadir = [r for r in records if r.get("status") == "HADIR"]
    telat = [r for r in records if r.get("status") == "TELAT"]

    # teknisi terdaftar yang belum absen
    belum = [t for t in all_tek
             if str(t.get("user_id", "")).strip()
             and str(t["user_id"]) not in absen_uid]

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
    lines.append(f"❌ *BELUM ABSEN ({len(belum)})*")
    for t in sorted(belum, key=lambda x: x.get("sektor", "")):
        lines.append(f"  • {t['nama']} — {t.get('sektor','-')}")
    if not belum:
        lines.append("  -")

    total_terdaftar = len([t for t in all_tek if str(t.get('user_id','')).strip()])
    lines.append("")
    lines.append(f"Total absen: {len(records)}/{total_terdaftar} terdaftar")
    return "\n".join(lines)


async def kirim_rekap(context: ContextTypes.DEFAULT_TYPE):
    group_id = _resolve_group_id()
    if not group_id:
        log.warning("group_chat_id belum diset; rekap tidak dikirim.")
        return
    text = _build_rekap_text(_today_str())
    await context.bot.send_message(
        chat_id=int(group_id), text=text, parse_mode="Markdown"
    )
    log.info("Rekap terkirim ke grup %s", group_id)


async def rekap_manual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/rekap — kirim rekap sekarang (untuk test / kebutuhan mendadak)."""
    group_id = _resolve_group_id()
    if not group_id:
        await update.message.reply_text(
            "Grup tujuan belum diset. Ketik /setgrup di grup dulu."
        )
        return
    text = _build_rekap_text(_today_str())
    await context.bot.send_message(int(group_id), text, parse_mode="Markdown")
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

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("setgrup", set_grup))
    app.add_handler(CommandHandler("rekap", rekap_manual))
    app.add_handler(CallbackQueryHandler(on_register_choice, pattern=r"^reg::"))
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))

    # jadwal harian jam cutoff
    cutoff = dt.time(hour=config.CUTOFF_HOUR, minute=config.CUTOFF_MINUTE,
                     tzinfo=TZ)
    app.job_queue.run_daily(_daily_job, time=cutoff)
    log.info("Bot start. Rekap harian jam %02d:%02d %s",
             config.CUTOFF_HOUR, config.CUTOFF_MINUTE, config.TIMEZONE)

    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
