import os
import sys
import time
import uuid
import logging
from typing import Dict, Any

from aiogram import Bot, Dispatcher, types, F
from aiogram.enums import ParseMode, ChatAction
from aiogram.filters import CommandStart, Command
from aiogram.types import FSInputFile, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession

from config import BOT_TOKEN, COOKIES_PATH
from downloader import (
    is_instagram_url,
    extract_instagram_url,
    download_instagram_video,
    cleanup_file,
    VideoInfo,
    DOWNLOAD_DIR,
)
from video_enhancer import (
    enhance_video_ai,
    AI_MODES,
)
from video_translator import (
    translate_and_dub_video,
    TARGET_LANGUAGES,
)

# Windows terminalida UTF-8 belgilar to'g'ri chiqishi uchun
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Logging sozlamalari
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

dp = Dispatcher()

# Faol videolar keshi: video_id -> { "file_path": str, "created_at": float, "uploader": str }
ACTIVE_VIDEOS: Dict[str, Dict[str, Any]] = {}

def clean_expired_videos():
    """15 daqiqadan oshgan keshdagi videolarni diskdan tozalaydi."""
    now = time.time()
    expired_ids = []
    for vid, data in ACTIVE_VIDEOS.items():
        if now - data.get("created_at", 0) > 900:  # 15 daqiqa
            cleanup_file(data.get("file_path"))
            expired_ids.append(vid)
    for vid in expired_ids:
        ACTIVE_VIDEOS.pop(vid, None)

def build_ai_keyboard(video_id: str, original_url: Optional[str] = None) -> types.InlineKeyboardMarkup:
    """AI video ishlov berish va tarjima asosiy tugmalarini yaratadi."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✨ AI Tiniqlashtirish (Ultra HD)",
        callback_data=f"ai:sharpen:{video_id}"
    )
    builder.button(
        text="🌐 Video Tarjima (AI Dublyaj)",
        callback_data=f"tr_menu:{video_id}"
    )
    builder.button(
        text="🌈 AI HDR",
        callback_data=f"ai:hdr:{video_id}"
    )
    builder.button(
        text="🎬 AI Kinematik",
        callback_data=f"ai:cinematic:{video_id}"
    )
    builder.button(
        text="🔮 AI Cyberpunk",
        callback_data=f"ai:cyberpunk:{video_id}"
    )
    builder.button(
        text="📼 AI Retro VHS",
        callback_data=f"ai:retro:{video_id}"
    )
    builder.button(
        text="🖤 AI B&W Noir",
        callback_data=f"ai:noir:{video_id}"
    )
    if original_url:
        builder.button(
            text="🔗 Instagram'da ochish",
            url=original_url
        )
        builder.adjust(1, 1, 2, 2, 1, 1)
    else:
        builder.adjust(1, 1, 2, 2, 1)
    return builder.as_markup()

def build_translation_keyboard(video_id: str) -> types.InlineKeyboardMarkup:
    """Tarjima tillarini tanlash menyusi."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="🇺🇿 O'zbekcha Dublyaj",
        callback_data=f"tr:uz:{video_id}"
    )
    builder.button(
        text="🇷🇺 Ruscha (Озвучка)",
        callback_data=f"tr:ru:{video_id}"
    )
    builder.button(
        text="🇬🇧 English Voiceover",
        callback_data=f"tr:en:{video_id}"
    )
    builder.button(
        text="⬅️ Asosiy menyuga qaytish",
        callback_data=f"tr_back:{video_id}"
    )
    builder.adjust(1, 1, 1, 1)
    return builder.as_markup()


@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    """Xush kelibsiz xabari va imkoniyatlar ro'yxati."""
    user_name = message.from_user.first_name if message.from_user else "Foydalanuvchi"
    text = (
        f"Assalomu alaykum, <b>{user_name}</b>! 👋\n\n"
        "Men <b>Instagram, AI Tiniqlashtiruvchi va Video Tarjimon</b> botman! 🚀\n\n"
        "<b>Mening imkoniyatlarim:</b>\n"
        "📥 <b>Instagram Video:</b> Reels yoki Post havolasini yuboring, original sifatda yuklab beraman.\n"
        "🌐 <b>Video Tarjima & Dublyaj:</b> Videodagi nutqni <b>O'zbek, Rus va Ingliz</b> tillariga tabiiy ovoz bilan tarjima qilib beraman.\n"
        "✨ <b>AI Tiniqlashtirish:</b> Xira videolarni Ultra HD darajasiga keltiradi.\n"
        "🎥 <b>Ixtiyoriy video:</b> Menga shunchaki biror video tashlasangiz ham uni tarjima yoki tiniqlashtirib beraman!\n\n"
        "<i>Sinash uchun Instagram havolasi yoki biror video yuboring:</i>"
    )
    await message.answer(text)


@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    """Qo'llanma."""
    text = (
        "📖 <b>Botdan foydalanish qo'llanmasi:</b>\n\n"
        "1. <b>Instagramdan yuklash:</b> Instagram video/reels havolasini botga yuboring.\n"
        "2. <b>Video Tarjima (AI Dublyaj):</b> Video tagidagi <b>🌐 Video Tarjima</b> tugmasini bosing va tilni tanlang (🇺🇿 O'zbek, 🇷🇺 Rus, 🇬🇧 Ingliz). Bot videodagi ovozni aniqlab, tanlangan tilda dublyaj qilib yuboradi!\n"
        "3. <b>AI Tiniqlashtirish:</b> <b>✨ AI Tiniqlashtirish</b> tugmasi orqali videoni xiralikdan tozalab, yuqori ravshanlikka erishing.\n"
        "4. <b>O'z videolaringiz:</b> Galereyangizdagi videolarni ham to'g'ridan-to'g'ri botga yuborishingiz mumkin."
    )
    await message.answer(text)


@dp.message(F.video)
async def handle_direct_video(message: types.Message, bot: Bot):
    """Foydalanuvchi to'g'ridan-to'g'ri video yuborganda menyuni chiqarish."""
    clean_expired_videos()

    video = message.video
    if video.file_size and video.file_size > 50 * 1024 * 1024:
        await message.answer("⚠️ Kechirasiz, Telegram bot orqali faqat 50 MB gacha bo'lgan videolarni qabul qila olaman.")
        return

    status_msg = await message.answer("⏳ <i>Video qabul qilinmoqda, iltimos kuting...</i>")

    video_id = uuid.uuid4().hex[:8]
    local_path = os.path.join(DOWNLOAD_DIR, f"user_vid_{video_id}.mp4")

    try:
        file = await bot.get_file(video.file_id)
        await bot.download_file(file.file_path, destination=local_path)

        ACTIVE_VIDEOS[video_id] = {
            "file_path": local_path,
            "created_at": time.time(),
            "uploader": message.from_user.first_name if message.from_user else "Foydalanuvchi"
        }

        await status_msg.edit_text(
            "🎬 <b>Video muvaffaqiyatli qabul qilindi!</b>\n\n"
            "Quyidagi funksiyalardan birini tanlang:",
            reply_markup=build_ai_keyboard(video_id)
        )
    except Exception as e:
        logger.error(f"Foydalanuvchi videosini yuklab olishda xatolik: {e}", exc_info=True)
        await status_msg.edit_text("❌ Videoni qabul qilishda xatolik yuz berdi. Iltimos, qayta urinib ko'ring.")
        cleanup_file(local_path)


@dp.message(F.text)
async def handle_instagram_link(message: types.Message, bot: Bot):
    """Instagram havolalarini qabul qilish va yuklab berish."""
    clean_expired_videos()
    text = message.text.strip()

    if not is_instagram_url(text):
        await message.answer(
            "⚠️ Iltimos, haqiqiy <b>Instagram video yoki Reels</b> havolasini yuboring yoki video fayl tashlang!\n\n"
            "Misol: <code>https://www.instagram.com/reel/Cxxxxxx/</code>"
        )
        return

    clean_url = extract_instagram_url(text) or text.strip()

    status_msg = await message.answer("⏳ <i>Video Instagram'dan yuklab olinmoqda...</i>")
    await bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.UPLOAD_VIDEO)

    video_info: VideoInfo | None = None
    video_id = uuid.uuid4().hex[:8]

    try:
        video_info = await download_instagram_video(clean_url, cookies_path=COOKIES_PATH)

        # Videoni keshga joylash
        ACTIVE_VIDEOS[video_id] = {
            "file_path": video_info.file_path,
            "created_at": time.time(),
            "uploader": video_info.uploader or "Instagram",
            "original_url": clean_url
        }

        caption_lines = ["🎬 <b>Instagram Video</b>\n"]
        if video_info.uploader and video_info.uploader != "Instagram":
            caption_lines.append(f"👤 <b>Muallif:</b> <a href=\"https://instagram.com/{video_info.uploader}\">@{video_info.uploader}</a>")
        caption_lines.append(f"🔗 <b>Instagram:</b> <a href=\"{clean_url}\">{clean_url}</a>")
        if video_info.filesize_mb:
            caption_lines.append(f"📦 <b>Hajmi:</b> {video_info.filesize_mb} MB")
        caption_lines.append(f"🤖 <b>Yuklab olindi:</b> @Iinstavideo_bot")
        caption_lines.append("\n<i>🌐 Videoni tarjima qilish yoki AI orqali tiniqlashtirish uchun quyidagi tugmalardan birini bosing:</i>")

        caption = "\n".join(caption_lines)

        video_file = FSInputFile(video_info.file_path)
        for attempt in range(3):
            try:
                await message.answer_video(
                    video=video_file,
                    caption=caption,
                    duration=video_info.duration,
                    width=video_info.width,
                    height=video_info.height,
                    supports_streaming=True,
                    reply_markup=build_ai_keyboard(video_id, original_url=clean_url),
                    request_timeout=300
                )
                break
            except Exception as up_err:
                logger.warning(f"Video yuborish urinishi {attempt+1}/3: {up_err}")
                if attempt == 2:
                    raise up_err
                import asyncio
                await asyncio.sleep(2)

        try:
            await status_msg.delete()
        except Exception:
            pass

    except Exception as e:
        logger.error(f"Videoni yuklashda xatolik: {e}", exc_info=True)
        error_text = str(e).lower()

        if "file is larger than" in error_text or "max_filesize" in error_text:
            msg = "❌ Kechirasiz, ushbu video 50 MB dan katta bo'lgani sababli Telegram Bot orqali yuborib bo'lmaydi."
        elif "login" in error_text or "private" in error_text:
            msg = "🔒 Ushbu video yopiq (private) profilda joylashgan yoki Instagram tizimga kirishni talab qilmoqda."
        else:
            msg = "❌ Videoni yuklab olishda xatolik yuz berdi. Havola to'g'riligini tekshiring yoki birozdan so'ng qayta urinib ko'ring."

        await status_msg.edit_text(msg)
        if video_info and video_info.file_path:
            cleanup_file(video_info.file_path)


@dp.callback_query(F.data.startswith("tr_menu:"))
async def handle_translation_menu(callback: CallbackQuery):
    """Tarjima tillari menyusiga o'tish."""
    video_id = callback.data.split(":")[1]
    if video_id not in ACTIVE_VIDEOS or not os.path.exists(ACTIVE_VIDEOS[video_id]["file_path"]):
        await callback.answer("⚠️ Ushbu video muddati tugagan. Iltimos, videoni qayta yuboring.", show_alert=True)
        return

    await callback.message.edit_reply_markup(
        reply_markup=build_translation_keyboard(video_id)
    )
    await callback.answer("Tarjima tilini tanlang")


@dp.callback_query(F.data.startswith("tr_back:"))
async def handle_translation_back(callback: CallbackQuery):
    """Asosiy AI menyusiga qaytish."""
    video_id = callback.data.split(":")[1]
    if video_id not in ACTIVE_VIDEOS or not os.path.exists(ACTIVE_VIDEOS[video_id]["file_path"]):
        await callback.answer("⚠️ Ushbu video muddati tugagan. Iltimos, videoni qayta yuboring.", show_alert=True)
        return

    await callback.message.edit_reply_markup(
        reply_markup=build_ai_keyboard(video_id)
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("tr:"))
async def handle_translation_action(callback: CallbackQuery, bot: Bot):
    """Videoni tanlangan tilga tarjima va dublyaj qilish."""
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("⚠️ Noma'lum buyruq.", show_alert=True)
        return

    _, target_lang, video_id = parts

    if video_id not in ACTIVE_VIDEOS or not os.path.exists(ACTIVE_VIDEOS[video_id]["file_path"]):
        await callback.answer(
            "⚠️ Ushbu video muddati tugagan yoki o'chirilgan. Iltimos, videoni qayta yuboring.",
            show_alert=True
        )
        return

    lang_info = TARGET_LANGUAGES.get(target_lang, TARGET_LANGUAGES["uz"])
    await callback.answer(f"{lang_info['flag']} {lang_info['name']} dublyaji tanlandi!")

    status_msg = await callback.message.reply(
        f"⏳ <b>Video {lang_info['flag']} {lang_info['name']}ga tarjima qilinmoqda...</b>\n\n"
        f"<i>1. Nutq aniqlanmoqda...</i>\n"
        f"<i>2. Matn tarjima qilinmoqda...</i>\n"
        f"<i>3. AI neyron ovoz bilan dublyaj qilinmoqda...</i>\n\n"
        f"Iltimos, biroz kuting (15-40 soniya)..."
    )

    await bot.send_chat_action(chat_id=callback.message.chat.id, action=ChatAction.UPLOAD_VIDEO)

    source_path = ACTIVE_VIDEOS[video_id]["file_path"]
    dubbed_result = None

    try:
        dubbed_result = await translate_and_dub_video(source_path, target_lang=target_lang)
        output_path = dubbed_result["output_video_path"]

        orig_preview = dubbed_result["original_text"]
        if len(orig_preview) > 200:
            orig_preview = orig_preview[:200] + "..."

        trans_preview = dubbed_result["translated_text"]
        if len(trans_preview) > 200:
            trans_preview = trans_preview[:200] + "..."

        src_code = dubbed_result.get("detected_lang", "auto").split("-")[0].upper()

        uploader = ACTIVE_VIDEOS[video_id].get("uploader", "Instagram")
        orig_url = ACTIVE_VIDEOS[video_id].get("original_url", "")

        meta_lines = []
        if uploader and uploader != "Instagram":
            meta_lines.append(f"👤 <b>Muallif:</b> <a href=\"https://instagram.com/{uploader}\">@{uploader}</a>")
        if orig_url:
            meta_lines.append(f"🔗 <b>Instagram:</b> <a href=\"{orig_url}\">{orig_url}</a>")
        meta_block = "\n".join(meta_lines) + "\n\n" if meta_lines else ""

        caption = (
            f"🌐 <b>Video AI Dublyaj ({lang_info['flag']} {lang_info['name']})</b>\n\n"
            f"{meta_block}"
            f"🗣 <b>Asl nutq ({src_code}):</b>\n<i>\"{orig_preview}\"</i>\n\n"
            f"📝 <b>Tarjima:</b>\n<i>\"{trans_preview}\"</i>\n\n"
            f"📦 <b>Hajmi:</b> {dubbed_result['file_size_mb']} MB\n"
            f"{engine_text}"
            f"🤖 <b>Yuklab olindi:</b> @Iinstavideo_bot"
        )

        video_file = FSInputFile(output_path)
        for attempt in range(3):
            try:
                await callback.message.answer_video(
                    video=video_file,
                    caption=caption,
                    supports_streaming=True,
                    request_timeout=300
                )
                break
            except Exception as up_err:
                logger.warning(f"Dublyaj video yuborish urinishi {attempt+1}/3: {up_err}")
                if attempt == 2:
                    raise up_err
                import asyncio
                await asyncio.sleep(2)

        try:
            await status_msg.delete()
        except Exception:
            pass

    except ValueError as ve:
        logger.info(f"Videoda nutq topilmadi: {ve}")
        await status_msg.edit_text("ℹ️ Ushbu videoda tushunarli inson nutqi aniqlanmadi yoki video faqat musiqadan iborat.")
    except Exception as e:
        logger.error(f"Video tarjimada xatolik: {e}", exc_info=True)
        await status_msg.edit_text("❌ Videoni tarjima qilishda xatolik yuz berdi. Iltimos, qayta urinib ko'ring.")
    finally:
        import gc
        gc.collect()
        import asyncio
        await asyncio.sleep(0.5)
        if dubbed_result and "output_video_path" in dubbed_result:
            cleanup_file(dubbed_result["output_video_path"])


@dp.callback_query(F.data.startswith("ai:"))
async def handle_ai_callback(callback: CallbackQuery, bot: Bot):
    """AI rejim tugmalari bosilganda videoni qayta ishlab yuborish."""
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("⚠️ Noma'lum buyruq.", show_alert=True)
        return

    _, mode, video_id = parts

    if video_id not in ACTIVE_VIDEOS or not os.path.exists(ACTIVE_VIDEOS[video_id]["file_path"]):
        await callback.answer(
            "⚠️ Ushbu video muddati tugagan yoki o'chirilgan. Iltimos, videoni qayta yuboring.",
            show_alert=True
        )
        return

    mode_info = AI_MODES.get(mode, AI_MODES["sharpen"])
    await callback.answer(f"{mode_info['short_title']} tanlandi!")

    status_msg = await callback.message.reply(
        f"⏳ <b>{mode_info['title']}</b> jarayoni boshlandi...\n"
        f"<i>AI video ustida ishlamoqda, iltimos 10-30 soniya kuting...</i>"
    )

    await bot.send_chat_action(chat_id=callback.message.chat.id, action=ChatAction.UPLOAD_VIDEO)

    source_path = ACTIVE_VIDEOS[video_id]["file_path"]
    enhanced_path = None

    try:
        enhanced_path, size_mb = await enhance_video_ai(source_path, mode=mode)

        uploader = ACTIVE_VIDEOS[video_id].get("uploader", "Instagram")
        orig_url = ACTIVE_VIDEOS[video_id].get("original_url", "")

        meta_lines = []
        if uploader and uploader != "Instagram":
            meta_lines.append(f"👤 <b>Muallif:</b> <a href=\"https://instagram.com/{uploader}\">@{uploader}</a>")
        if orig_url:
            meta_lines.append(f"🔗 <b>Instagram:</b> <a href=\"{orig_url}\">{orig_url}</a>")
        meta_block = "\n".join(meta_lines) + "\n\n" if meta_lines else ""

        caption = (
            f"<b>{mode_info['title']}</b>\n\n"
            f"{meta_block}"
            f"ℹ️ {mode_info['description']}\n"
            f"📦 <b>Hajmi:</b> {size_mb} MB\n"
            f"🔊 <i>Asl ovoz to'liq saqlandi.</i>\n\n"
            f"🤖 <b>Yuklab olindi:</b> @Iinstavideo_bot"
        )

        video_file = FSInputFile(enhanced_path)
        for attempt in range(3):
            try:
                await callback.message.answer_video(
                    video=video_file,
                    caption=caption,
                    supports_streaming=True,
                    request_timeout=300
                )
                break
            except Exception as up_err:
                logger.warning(f"AI video yuborish urinishi {attempt+1}/3: {up_err}")
                if attempt == 2:
                    raise up_err
                import asyncio
                await asyncio.sleep(2)

        try:
            await status_msg.delete()
        except Exception:
            pass

    except Exception as e:
        logger.error(f"AI videoni qayta ishlashda xatolik: {e}", exc_info=True)
        await status_msg.edit_text("❌ Videoni yuklash yoki qayta ishlashda tarmoq xatoligi yuz berdi. Iltimos, qayta urinib ko'ring.")
    finally:
        import gc
        gc.collect()
        import asyncio
        await asyncio.sleep(0.5)
        if enhanced_path:
            cleanup_file(enhanced_path)


async def main():
    if not BOT_TOKEN or ":" not in BOT_TOKEN:
        print("\n" + "=" * 65)
        print("XATOLIK: .env faylida yaroqli BOT_TOKEN ko'rsatilmagan!")
        print("=" * 65 + "\n")
        return

    # Katta video fayllar uzatilishi uchun 300 soniyalik timeout
    session = AiohttpSession(timeout=300.0)
    bot = Bot(
        token=BOT_TOKEN,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )

    print("\n" + "=" * 60, flush=True)
    print("[+] AI & Tarjimon Bot muvaffaqiyatli ishga tushirildi!", flush=True)
    print("[+] Telegram'da botingizga kirib /start yuboring.", flush=True)
    print("=" * 60 + "\n", flush=True)

    await bot.delete_webhook(drop_pending_updates=True)
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        import asyncio
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot to'xtatildi.")
