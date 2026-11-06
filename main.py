import os
import sys
import time
import uuid
import html
import logging
from typing import Dict, Any, Optional

from aiogram import Bot, Dispatcher, types, F
from aiogram.enums import ParseMode, ChatAction
from aiogram.filters import CommandStart, Command
from aiogram.types import FSInputFile, CallbackQuery, InputMediaPhoto, InputMediaVideo
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramForbiddenError, TelegramAPIError

from config import BOT_TOKEN, COOKIES_PATH
from downloader import (
    is_supported_url,
    extract_media_url,
    detect_platform,
    download_media,
    extract_audio_mp3,
    cleanup_file,
    MediaItem,
    DownloadResult,
    DOWNLOAD_DIR,
    PLATFORMS,
)
from video_enhancer import (
    change_video_resolution,
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


@dp.error()
async def global_error_handler(event: types.ErrorEvent):
    """Foydalanuvchi botni bloklaganida yoki ruxsat yo'qligida tinchgina log yozish."""
    if isinstance(event.exception, TelegramForbiddenError):
        logger.warning(f"Foydalanuvchi botni bloklagan: {event.exception}")
        return True
    logger.error(f"Kutilmagan xatolik: {event.exception}", exc_info=event.exception)
    return True


# Faol videolar keshi: video_id -> { "file_path": str, "created_at": float, "uploader": str, "original_url": str, "platform": str }
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


def build_media_keyboard(
    video_id: str,
    original_url: Optional[str] = None,
    platform_name: str = "Havolani"
) -> types.InlineKeyboardMarkup:
    """Video sifati (720p / 1080p), MP3 audio ajratish va havola tugmalarini yaratadi."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="📥 720p (HD)",
        callback_data=f"dl:720:{video_id}"
    )
    builder.button(
        text="📥 1080p (Full HD)",
        callback_data=f"dl:1080:{video_id}"
    )
    builder.button(
        text="🎵 Audio (MP3)",
        callback_data=f"dl:mp3:{video_id}"
    )
    if original_url:
        builder.button(
            text=f"🔗 {platform_name}'da ochish",
            url=original_url
        )
        builder.adjust(2, 1, 1)
    else:
        builder.adjust(2, 1)
    return builder.as_markup()


# Eski kodlar bilan moslik uchun
build_ai_keyboard = build_media_keyboard


@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    """Xush kelibsiz xabari va qo'llab-quvvatlanadigan platformalar ro'yxati."""
    raw_user_name = message.from_user.first_name if message.from_user and message.from_user.first_name else "Foydalanuvchi"
    user_name = html.escape(raw_user_name)
    text = (
        f"Assalomu alaykum, <b>{user_name}</b>! 👋\n\n"
        "Men barcha asosiy ijtimoiy tarmoqlardan video va rasm yuklab beruvchi <b>Universal Media Botiman</b>! 🚀\n\n"
        "<b>Quyidagi platformalardan istalgan havolani yuboring:</b>\n"
        "• 📸 <b>Instagram</b> - post, stories, reels, rasm;\n"
        "• 🔴 <b>YouTube</b> - video, shorts, audio (MP3);\n"
        "• 🎵 <b>Tik Tok</b> - suv belgisiz video;\n"
        "• 🔵 <b>Facebook</b> - reels, rasm, video;\n"
        "• 📌 <b>Pinterest</b> - rasm, video;\n"
        "• 👻 <b>Snapchat</b> - rasm, video;\n"
        "• ✈️ <b>Telegram</b> - hikoya va postlar;\n\n"
        "🎥 <i>Shuningdek, o'z videolaringizni tashlasangiz, uni 720p/1080p sifatga o'tkazib yoki MP3 audio ajratib beraman!</i>"
    )
    await message.answer(text)


@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    """Qo'llanma."""
    text = (
        "📖 <b>Botdan foydalanish qo'llanmasi:</b>\n\n"
        "1. <b>Havola orqali yuklash:</b> Instagram, YouTube, TikTok, Facebook, Pinterest, Snapchat yoki Telegram havolasini botga yuboring.\n"
        "2. <b>TikTok:</b> Barcha videolar avtomatik ravishda <b>suv belgisiz (no watermark)</b> asl sifatda yuklanadi.\n"
        "3. <b>🎵 Audio (MP3):</b> Har qanday video ostidagi <b>🎵 Audio (MP3)</b> tugmasi orqali uning ovozini MP3 formatda yuklab olishingiz mumkin.\n"
        "4. <b>📥 720p / 1080p:</b> Video o'lchamini kerakli sifatga o'zgartirish uchun mos tugmani bosing.\n"
        "5. <b>O'z videolaringiz:</b> Shaxsiy videolaringizni yuborib ham audio yoki formatini o'zgartirishingiz mumkin."
    )
    await message.answer(text)


@dp.message(F.video)
async def handle_direct_video(message: types.Message, bot: Bot):
    """Foydalanuvchi to'g'ridan-to'g'ri video yuborganda sifat va MP3 menyusini chiqarish."""
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

        uploader_name = message.from_user.first_name if message.from_user and message.from_user.first_name else "Foydalanuvchi"
        ACTIVE_VIDEOS[video_id] = {
            "file_path": local_path,
            "created_at": time.time(),
            "uploader": uploader_name,
            "original_url": None,
            "platform": "Video"
        }

        await status_msg.edit_text(
            "🎬 <b>Video muvaffaqiyatli qabul qilindi!</b>\n\n"
            "Quyidagi variantlardan birini tanlang:",
            reply_markup=build_media_keyboard(video_id, platform_name="Video")
        )
    except Exception as e:
        logger.error(f"Foydalanuvchi videosini yuklab olishda xatolik: {e}", exc_info=True)
        await status_msg.edit_text("❌ Videoni qabul qilishda xatolik yuz berdi. Iltimos, qayta urinib ko'ring.")
        cleanup_file(local_path)


@dp.message(F.text)
async def handle_media_link(message: types.Message, bot: Bot):
    """Instagram, YouTube, TikTok, Facebook, Pinterest, Snapchat, Telegram havolalarini yuklab berish."""
    clean_expired_videos()
    text = message.text.strip()

    clean_url = extract_media_url(text)
    if not clean_url:
        await message.answer(
            "⚠️ Iltimos, qo'llab-quvvatlanadigan platforma havolasini yuboring:\n\n"
            "• 📸 <b>Instagram</b> - post, stories, reels, rasm\n"
            "• 🔴 <b>YouTube</b> - video, shorts, audio\n"
            "• 🎵 <b>Tik Tok</b> - suv belgisiz video\n"
            "• 🔵 <b>Facebook</b> - reels, rasm, video\n"
            "• 📌 <b>Pinterest</b> - rasm, video\n"
            "• 👻 <b>Snapchat</b> - rasm, video\n"
            "• ✈️ <b>Telegram</b> - hikoya va postlar"
        )
        return

    pkey, pmeta = detect_platform(clean_url)
    status_msg = await message.answer(f"⏳ <i>{pmeta['icon']} {pmeta['name']} dan media yuklab olinmoqda...</i>")
    await bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.UPLOAD_VIDEO)

    result: Optional[DownloadResult] = None
    try:
        result = await download_media(clean_url, cookies_path=COOKIES_PATH)
        if not result or not result.items:
            raise ValueError("Media fayllar topilmadi.")

        # Muallif va havola matnlari
        safe_url = html.escape(clean_url)
        safe_title = html.escape(result.title[:80] + "...") if result.title and len(result.title) > 80 else html.escape(result.title or "")
        safe_uploader = html.escape(result.uploader or pmeta["name"])

        base_caption_lines = [f"{pmeta['icon']} <b>{pmeta['name']} Media</b>\n"]
        if safe_title:
            base_caption_lines.append(f"📝 <b>Sarlavha:</b> {safe_title}")
        if safe_uploader and safe_uploader != pmeta["name"]:
            base_caption_lines.append(f"👤 <b>Muallif:</b> @{safe_uploader}")
        base_caption_lines.append(f"🔗 <b>Havola:</b> <a href=\"{safe_url}\">{safe_url}</a>")
        base_caption_lines.append("🤖 <b>Yuklab olindi:</b> @Iinstavideo_bot")

        # 1. BIR NECHTA MEDIA (ALBOM / KARUSEL) BO'LSA
        if len(result.items) > 1:
            media_group = []
            caption_text = "\n".join(base_caption_lines)
            for idx, item in enumerate(result.items[:10]):  # Telegram maksimal 10 ta media
                c = caption_text if idx == 0 else None
                f_input = FSInputFile(item.file_path)
                if item.media_type == "photo":
                    media_group.append(InputMediaPhoto(media=f_input, caption=c))
                else:
                    media_group.append(InputMediaVideo(media=f_input, caption=c, supports_streaming=True))

            await message.answer_media_group(media=media_group)

            # Vaqtinchalik fayllarni tozalaymiz
            for item in result.items:
                cleanup_file(item.file_path)

            try:
                await status_msg.delete()
            except Exception:
                pass
            return

        # 2. YAGONA MEDIA BO'LSA
        item = result.items[0]

        # 2A. RASM (PHOTO)
        if item.media_type == "photo":
            caption_lines = list(base_caption_lines)
            if item.filesize_mb:
                caption_lines.insert(-1, f"📦 <b>Hajmi:</b> {item.filesize_mb} MB")
            caption = "\n".join(caption_lines)

            photo_file = FSInputFile(item.file_path)
            await message.answer_photo(
                photo=photo_file,
                caption=caption
            )
            cleanup_file(item.file_path)
            try:
                await status_msg.delete()
            except Exception:
                pass
            return

        # 2B. AUDIO
        if item.media_type == "audio":
            caption_lines = list(base_caption_lines)
            if item.filesize_mb:
                caption_lines.insert(-1, f"📦 <b>Hajmi:</b> {item.filesize_mb} MB")
            caption = "\n".join(caption_lines)

            audio_file = FSInputFile(item.file_path)
            await message.answer_audio(
                audio=audio_file,
                caption=caption,
                title=result.title or f"{pmeta['name']} Audio",
                performer=result.uploader or pmeta["name"]
            )
            cleanup_file(item.file_path)
            try:
                await status_msg.delete()
            except Exception:
                pass
            return

        # 2C. VIDEO
        video_id = uuid.uuid4().hex[:8]
        ACTIVE_VIDEOS[video_id] = {
            "file_path": item.file_path,
            "created_at": time.time(),
            "uploader": result.uploader or pmeta["name"],
            "original_url": clean_url,
            "platform": pmeta["name"]
        }

        caption_lines = list(base_caption_lines)
        if item.filesize_mb:
            caption_lines.insert(-1, f"📦 <b>Hajmi:</b> {item.filesize_mb} MB")
        caption_lines.append("\n<i>📥 Sifatni tanlash yoki MP3 audio ajratib olish uchun quyidagi tugmalardan birini bosing:</i>")
        caption = "\n".join(caption_lines)

        video_file = FSInputFile(item.file_path)
        for attempt in range(3):
            try:
                await message.answer_video(
                    video=video_file,
                    caption=caption,
                    duration=item.duration,
                    width=item.width,
                    height=item.height,
                    supports_streaming=True,
                    reply_markup=build_media_keyboard(video_id, original_url=clean_url, platform_name=pmeta["name"]),
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
        logger.error(f"Mediani yuklashda xatolik: {e}", exc_info=True)
        err_str = str(e).lower()

        if "file is larger than" in err_str or "max_filesize" in err_str or "50 mb" in err_str:
            msg = "❌ Kechirasiz, ushbu media fayl 50 MB dan katta bo'lgani sababli Telegram Bot orqali yuborib bo'lmaydi."
        elif "login" in err_str or "private" in err_str:
            msg = f"🔒 Ushbu post yopiq (private) profilda joylashgan yoki {pmeta['name']} tizimga kirishni talab qilmoqda."
        else:
            msg = f"❌ {pmeta['name']} dan yuklab olishda xatolik yuz berdi. Havola to'g'riligini tekshiring yoki birozdan so'ng qayta urinib ko'ring."

        await status_msg.edit_text(msg)
        if result and result.items:
            for item in result.items:
                cleanup_file(item.file_path)


@dp.callback_query(F.data.startswith("dl:"))
async def handle_download_callback(callback: CallbackQuery, bot: Bot):
    """720p, 1080p yoki MP3 audio ajratib yuborish callback boshqaruvi."""
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("⚠️ Noma'lum buyruq.", show_alert=True)
        return

    _, action_type, video_id = parts

    if video_id not in ACTIVE_VIDEOS or not os.path.exists(ACTIVE_VIDEOS[video_id]["file_path"]):
        await callback.answer(
            "⚠️ Ushbu video muddati tugagan yoki o'chirilgan. Iltimos, videoni qayta yuboring.",
            show_alert=True
        )
        return

    source_path = ACTIVE_VIDEOS[video_id]["file_path"]
    uploader = ACTIVE_VIDEOS[video_id].get("uploader", "Media")
    orig_url = ACTIVE_VIDEOS[video_id].get("original_url", "")
    pname = ACTIVE_VIDEOS[video_id].get("platform", "Media")

    # 1. MP3 AUDIO AJRATISH
    if action_type == "mp3":
        await callback.answer("🎵 MP3 audio tayyorlanmoqda...")
        status_msg = await callback.message.reply("⏳ <b>Videodan MP3 audio ajratib olinmoqda...</b>")
        await bot.send_chat_action(chat_id=callback.message.chat.id, action=ChatAction.UPLOAD_VOICE)

        mp3_path = None
        try:
            mp3_path, size_mb = await extract_audio_mp3(source_path)

            caption = (
                f"🎵 <b>{pname} Audio (MP3)</b>\n\n"
                f"👤 <b>Muallif:</b> @{html.escape(uploader)}\n"
                f"📦 <b>Hajmi:</b> {size_mb} MB\n"
                f"🤖 <b>Yuklab olindi:</b> @Iinstavideo_bot"
            )

            await callback.message.answer_audio(
                audio=FSInputFile(mp3_path),
                caption=caption,
                title=f"{pname} Audio",
                performer=uploader
            )
            try:
                await status_msg.delete()
            except Exception:
                pass
        except Exception as e:
            logger.error(f"MP3 ajratishda xatolik: {e}", exc_info=True)
            await status_msg.edit_text("❌ MP3 audio ajratib olishda xatolik yuz berdi.")
        finally:
            if mp3_path:
                cleanup_file(mp3_path)
        return

    # 2. 720p / 1080p SIFAT O'ZGARTIRISH
    try:
        target_res = int(action_type)
    except ValueError:
        target_res = 720

    quality_label = f"{target_res}p {'HD' if target_res == 720 else 'Full HD'}"
    await callback.answer(f"📥 {quality_label} tayyorlanmoqda...")

    status_msg = await callback.message.reply(
        f"⏳ <b>Video {quality_label} formatda tayyorlanmoqda...</b>\n"
        f"<i>Iltimos, biroz kuting (5-15 soniya)...</i>"
    )

    await bot.send_chat_action(chat_id=callback.message.chat.id, action=ChatAction.UPLOAD_VIDEO)
    processed_path = None

    try:
        processed_path, size_mb = await change_video_resolution(source_path, target_res=target_res)

        meta_lines = []
        if uploader and uploader not in ["Instagram", "YouTube", "TikTok", "Facebook", "Pinterest", "Snapchat", "Telegram"]:
            safe_uploader = html.escape(str(uploader))
            meta_lines.append(f"👤 <b>Muallif:</b> @{safe_uploader}")
        if orig_url:
            safe_url = html.escape(str(orig_url))
            meta_lines.append(f"🔗 <b>Havola:</b> <a href=\"{safe_url}\">{safe_url}</a>")
        meta_block = "\n".join(meta_lines) + "\n\n" if meta_lines else ""

        caption = (
            f"📥 <b>{pname} Video ({quality_label})</b>\n\n"
            f"{meta_block}"
            f"📦 <b>Hajmi:</b> {size_mb} MB\n"
            f"📐 <b>Sifat:</b> {quality_label}\n"
            f"🤖 <b>Yuklab olindi:</b> @Iinstavideo_bot"
        )

        video_file = FSInputFile(processed_path)
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
                logger.warning(f"{quality_label} video yuborish urinishi {attempt+1}/3: {up_err}")
                if attempt == 2:
                    raise up_err
                import asyncio
                await asyncio.sleep(2)

        try:
            await status_msg.delete()
        except Exception:
            pass

    except Exception as e:
        logger.error(f"{quality_label} videoni tayyorlashda xatolik: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ Videoni {quality_label} formatga o'tkazishda xatolik yuz berdi. Iltimos, qayta urinib ko'ring.")
    finally:
        import gc
        gc.collect()
        import asyncio
        await asyncio.sleep(0.5)
        if processed_path:
            cleanup_file(processed_path)


@dp.callback_query(F.data.startswith("ai:"))
async def handle_ai_callback(callback: CallbackQuery):
    """Oldingi AI tugmalari bosilganda bildirishnoma ko'rsatish."""
    await callback.answer("ℹ️ AI filtrlari o'chirilgan. Sifat (720p/1080p) yoki MP3 tugmalaridan foydalaning.", show_alert=True)


async def start_dummy_health_server():
    """Railway va boshqa cloud platformalar healthcheck tekshiruvi uchun yengil HTTP server."""
    port_str = os.getenv("PORT")
    if not port_str:
        return
    try:
        port = int(port_str)
        from aiohttp import web
        app = web.Application()

        async def health(request):
            return web.Response(text="OK - Universal Media Downloader Bot is running!")

        app.router.add_get("/", health)
        app.router.add_get("/health", health)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", port)
        await site.start()
        logger.info(f"Railway Healthcheck HTTP server ishga tushirildi: 0.0.0.0:{port}")
    except Exception as e:
        logger.warning(f"Healthcheck serverni ishga tushirishda xatolik: {e}")


async def main():
    if not BOT_TOKEN or ":" not in BOT_TOKEN:
        print("\n" + "=" * 65)
        print("XATOLIK: .env yoki Railway Variables'da yaroqli BOT_TOKEN ko'rsatilmagan!")
        print("Railway Dashboard -> Service -> Variables bo'limiga BOT_TOKEN qo'shing!")
        print("=" * 65 + "\n")
        import asyncio
        await asyncio.sleep(60)
        return

    # Railway healthcheck serverini ishga tushiramiz (agar PORT berilgan bo'lsa)
    await start_dummy_health_server()

    # Katta fayllar uzatilishi uchun 300 soniyalik timeout
    session = AiohttpSession(timeout=300.0)
    bot = Bot(
        token=BOT_TOKEN,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )

    print("\n" + "=" * 65, flush=True)
    print("[+] Universal Multi-Media Downloader Bot muvaffaqiyatli ishga tushirildi!", flush=True)
    print("[+] Platformalar: Instagram, YouTube, TikTok, Facebook, Pinterest, Snapchat, Telegram", flush=True)
    print("[+] Telegram'da botingizga kirib /start yuboring.", flush=True)
    print("=" * 65 + "\n", flush=True)

    await bot.delete_webhook(drop_pending_updates=False)
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
