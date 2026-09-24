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
    change_video_resolution,
    AI_MODES,
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

# Faol videolar keshi: video_id -> { "file_path": str, "created_at": float, "uploader": str, "original_url": str }
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
    """AI video ishlov berish va sifat tanlash (720p / 1080p) asosiy tugmalarini yaratadi."""
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
        text="✨ AI Tiniqlashtirish (Ultra HD)",
        callback_data=f"ai:sharpen:{video_id}"
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
        builder.adjust(2, 1, 2, 2, 1, 1)
    else:
        builder.adjust(2, 1, 2, 2, 1)
    return builder.as_markup()


@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    """Xush kelibsiz xabari va imkoniyatlar ro'yxati."""
    raw_user_name = message.from_user.first_name if message.from_user and message.from_user.first_name else "Foydalanuvchi"
    user_name = html.escape(raw_user_name)
    text = (
        f"Assalomu alaykum, <b>{user_name}</b>! 👋\n\n"
        "Men <b>Instagram Video Yuklovchi va AI Sifat Botiman</b>! 🚀\n\n"
        "<b>Mening imkoniyatlarim:</b>\n"
        "📥 <b>Instagram Video:</b> Reels yoki Post havolasini yuboring, original sifatda yuklab beraman.\n"
        "📐 <b>720p / 1080p Sifat:</b> Videoni istalgan hajmda (720p HD yoki 1080p Full HD) tezkor yuklab oling.\n"
        "✨ <b>AI Tiniqlashtirish:</b> Xira videolarni Ultra HD darajasiga keltiradi.\n"
        "🎨 <b>AI Rang filtrlari:</b> HDR, Kinematik, Cyberpunk, Retro VHS va Noir rejimlari.\n"
        "🎥 <b>Ixtiyoriy video:</b> O'zingiz video tashlasangiz ham uni sifatini oshirib yoki o'lchamini o'zgartirib beraman!\n\n"
        "<i>Sinash uchun Instagram havolasi yoki video yuboring:</i>"
    )
    await message.answer(text)


@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    """Qo'llanma."""
    text = (
        "📖 <b>Botdan foydalanish qo'llanmasi:</b>\n\n"
        "1. <b>Instagramdan yuklash:</b> Instagram video/reels havolasini botga yuboring.\n"
        "2. <b>Sifatni tanlash:</b> Video ostidagi <b>📥 720p (HD)</b> yoki <b>📥 1080p (Full HD)</b> tugmalari orqali kerakli formatda yuklab oling.\n"
        "3. <b>AI Tiniqlashtirish:</b> <b>✨ AI Tiniqlashtirish</b> tugmasi orqali videoni xiralikdan tozalab, yuqori ravshanlikka erishing.\n"
        "4. <b>AI Rang effektlari:</b> HDR, Kinematik, Neon Cyberpunk kabi maxsus rang uslublarini qo'llang.\n"
        "5. <b>O'z videolaringiz:</b> Galereyangizdagi videolarni ham to'g'ridan-to'g'ri botga yuborishingiz mumkin."
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

        uploader_name = message.from_user.first_name if message.from_user and message.from_user.first_name else "Foydalanuvchi"
        ACTIVE_VIDEOS[video_id] = {
            "file_path": local_path,
            "created_at": time.time(),
            "uploader": uploader_name,
            "original_url": None
        }

        await status_msg.edit_text(
            "🎬 <b>Video muvaffaqiyatli qabul qilindi!</b>\n\n"
            "Quyidagi sifat yoki AI funksiyalaridan birini tanlang:",
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

    video_info: Optional[VideoInfo] = None
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
            safe_uploader = html.escape(str(video_info.uploader))
            caption_lines.append(f"👤 <b>Muallif:</b> <a href=\"https://instagram.com/{safe_uploader}\">@{safe_uploader}</a>")
        safe_url = html.escape(str(clean_url))
        caption_lines.append(f"🔗 <b>Instagram:</b> <a href=\"{safe_url}\">{safe_url}</a>")
        if video_info.filesize_mb:
            caption_lines.append(f"📦 <b>Hajmi:</b> {video_info.filesize_mb} MB")
        caption_lines.append(f"🤖 <b>Yuklab olindi:</b> @Iinstavideo_bot")
        caption_lines.append("\n<i>📥 Sifatni tanlash yoki AI orqali tiniqlashtirish uchun quyidagi tugmalardan birini bosing:</i>")

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


@dp.callback_query(F.data.startswith("dl:"))
async def handle_download_quality_callback(callback: CallbackQuery, bot: Bot):
    """720p yoki 1080p sifatdagi videoni tayyorlab yuborish."""
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("⚠️ Noma'lum buyruq.", show_alert=True)
        return

    _, quality_str, video_id = parts
    try:
        target_res = int(quality_str)
    except ValueError:
        target_res = 720

    quality_label = f"{target_res}p {'HD' if target_res == 720 else 'Full HD'}"

    if video_id not in ACTIVE_VIDEOS or not os.path.exists(ACTIVE_VIDEOS[video_id]["file_path"]):
        await callback.answer(
            "⚠️ Ushbu video muddati tugagan yoki o'chirilgan. Iltimos, videoni qayta yuboring.",
            show_alert=True
        )
        return

    await callback.answer(f"📥 {quality_label} tayyorlanmoqda...")

    status_msg = await callback.message.reply(
        f"⏳ <b>Video {quality_label} formatda tayyorlanmoqda...</b>\n"
        f"<i>Iltimos, biroz kuting (5-15 soniya)...</i>"
    )

    await bot.send_chat_action(chat_id=callback.message.chat.id, action=ChatAction.UPLOAD_VIDEO)

    source_path = ACTIVE_VIDEOS[video_id]["file_path"]
    processed_path = None

    try:
        processed_path, size_mb = await change_video_resolution(source_path, target_res=target_res)

        uploader = ACTIVE_VIDEOS[video_id].get("uploader", "Instagram")
        orig_url = ACTIVE_VIDEOS[video_id].get("original_url", "")

        meta_lines = []
        if uploader and uploader != "Instagram":
            safe_uploader = html.escape(str(uploader))
            meta_lines.append(f"👤 <b>Muallif:</b> <a href=\"https://instagram.com/{safe_uploader}\">@{safe_uploader}</a>")
        if orig_url:
            safe_url = html.escape(str(orig_url))
            meta_lines.append(f"🔗 <b>Instagram:</b> <a href=\"{safe_url}\">{safe_url}</a>")
        meta_block = "\n".join(meta_lines) + "\n\n" if meta_lines else ""

        caption = (
            f"📥 <b>Instagram Video ({quality_label})</b>\n\n"
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
            safe_uploader = html.escape(str(uploader))
            meta_lines.append(f"👤 <b>Muallif:</b> <a href=\"https://instagram.com/{safe_uploader}\">@{safe_uploader}</a>")
        if orig_url:
            safe_url = html.escape(str(orig_url))
            meta_lines.append(f"🔗 <b>Instagram:</b> <a href=\"{safe_url}\">{safe_url}</a>")
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
            return web.Response(text="OK - Instagram Bot is running!")

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

    # Katta video fayllar uzatilishi uchun 300 soniyalik timeout
    session = AiohttpSession(timeout=300.0)
    bot = Bot(
        token=BOT_TOKEN,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )

    print("\n" + "=" * 60, flush=True)
    print("[+] Instagram Downloader & AI Bot muvaffaqiyatli ishga tushirildi!", flush=True)
    print("[+] Telegram'da botingizga kirib /start yuboring.", flush=True)
    print("=" * 60 + "\n", flush=True)

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
