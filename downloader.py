import os
import re
import time
import asyncio
import logging
from dataclasses import dataclass
from typing import Optional
import yt_dlp
import requests

from video_enhancer import get_ffmpeg_exe

logger = logging.getLogger(__name__)

# Vaqtinchalik fayllar uchun papka
DOWNLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Instagram havolasini aniqlash uchun regex
INSTAGRAM_URL_REGEX = re.compile(
    r"https?://(?:www\.)?instagram\.com/(p|reel|reels|tv)/([a-zA-Z0-9_-]+)",
    re.IGNORECASE
)

@dataclass
class VideoInfo:
    file_path: str
    title: Optional[str] = None
    uploader: Optional[str] = None
    duration: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None
    thumbnail: Optional[str] = None
    filesize_mb: float = 0.0

def is_instagram_url(text: str) -> bool:
    """Matn ichida Instagram video havolasi borligini tekshiradi."""
    if not text:
        return False
    return bool(INSTAGRAM_URL_REGEX.search(text))

def extract_instagram_url(text: str) -> Optional[str]:
    """Matndan toza Instagram havolasini ajratib oladi."""
    match = INSTAGRAM_URL_REGEX.search(text)
    if match:
        post_type = match.group(1).lower()
        if post_type == "reels":
            post_type = "reel"
        post_id = match.group(2)
        return f"https://www.instagram.com/{post_type}/{post_id}/"
    return None

def extract_shortcode(url: str) -> Optional[str]:
    """Instagram havolasidan post kodini (shortcode) ajratib oladi."""
    match = INSTAGRAM_URL_REGEX.search(url)
    if match:
        return match.group(2)
    return None

def _download_with_instaloader_fallback(url: str) -> VideoInfo:
    """
    yt-dlp ishlamay qolganda (masalan, bo'sh media javobi berilganda)
    Instaloader orqali videoni yuklab oluvchi mustahkam zaxira tizimi.
    """
    import instaloader
    shortcode = extract_shortcode(url)
    if not shortcode:
        raise ValueError("Instagram post kodi aniqlanmadi.")

    logger.info(f"Instaloader zaxira tizimi ishga tushirildi: {shortcode}")
    L = instaloader.Instaloader(
        download_pictures=False,
        download_videos=False,
        download_video_thumbnails=False,
        download_geotags=False,
        download_comments=False,
        save_metadata=False,
        compress_json=False
    )
    post = instaloader.Post.from_shortcode(L.context, shortcode)

    vid_url = None
    if post.is_video:
        vid_url = post.video_url
    elif post.typename == "GraphSidecar":
        for node in post.get_sidecar_nodes():
            if node.is_video:
                vid_url = node.video_url
                break

    if not vid_url:
        raise ValueError("Ushbu Instagram postida video topilmadi (faqat rasm bo'lishi mumkin).")

    file_path = os.path.join(DOWNLOAD_DIR, f"{shortcode}_{int(time.time())}.mp4")
    with requests.get(vid_url, stream=True, timeout=60) as resp:
        resp.raise_for_status()
        with open(file_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=128 * 1024):
                if chunk:
                    f.write(chunk)

    if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
        raise FileNotFoundError("Video fayli to'liq yuklab olinmadi.")

    size_mb = round(os.path.getsize(file_path) / (1024 * 1024), 2)
    return VideoInfo(
        file_path=file_path,
        title=post.caption[:120] if post.caption else "Instagram Video",
        uploader=post.owner_username or "Instagram",
        duration=post.video_duration,
        filesize_mb=size_mb
    )

def _download_sync(url: str, cookies_path: Optional[str] = None) -> VideoInfo:
    """
    Sinxron ravishda videoni eng yuqori sifatda yuklab oladi.
    Avval yt-dlp, agar xatolik yuz bersa avtomatik ravishda Instaloader zaxira tizimi ishlatiladi.
    """
    outtmpl = os.path.join(DOWNLOAD_DIR, "%(id)s_%(epoch)s.%(ext)s")
    ffmpeg_bin = get_ffmpeg_exe()

    ydl_opts = {
        # Eng yuqori sifatli video va audio (ffmpeg orqali MP4 ga birlashtiriladi)
        'format': 'bestvideo+bestaudio/best',
        'merge_output_format': 'mp4',
        'ffmpeg_location': ffmpeg_bin,
        'outtmpl': outtmpl,
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
        # Telegram Bot API cheklovi (maksimum 50MB)
        'max_filesize': 50 * 1024 * 1024,
        'http_headers': {
            'User-Agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/124.0.0.0 Safari/537.36'
            ),
            'Accept-Language': 'en-US,en;q=0.9',
        },
    }

    # Agar cookies fayli mavjud bo'lsa, foydalanamiz
    if cookies_path and os.path.exists(cookies_path):
        ydl_opts['cookiefile'] = cookies_path
        logger.info(f"Cookies fayli ishlatilmoqda: {cookies_path}")

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)

            if 'entries' in info and info['entries']:
                info = info['entries'][0]

            file_path = ydl.prepare_filename(info)

            # Format birlashtirilganda kengaytma .mp4 bo'ladi
            if not os.path.exists(file_path):
                base, _ = os.path.splitext(file_path)
                for ext in ['.mp4', '.mkv', '.webm']:
                    if os.path.exists(base + ext):
                        file_path = base + ext
                        break

            if not os.path.exists(file_path):
                raise FileNotFoundError("Video fayli saqlanmadi yoki topilmadi.")

            size_mb = os.path.getsize(file_path) / (1024 * 1024)

            return VideoInfo(
                file_path=file_path,
                title=info.get('title') or info.get('description') or "Instagram Video",
                uploader=info.get('uploader') or info.get('channel') or "Instagram",
                duration=info.get('duration'),
                width=info.get('width'),
                height=info.get('height'),
                thumbnail=info.get('thumbnail'),
                filesize_mb=round(size_mb, 2)
            )

    except Exception as ydl_err:
        logger.warning(f"yt-dlp yuklashda xatolik yuz berdi: {ydl_err}. Instaloader zaxira tizimi tekshirilmoqda...")

        # Chala qolgan .part fayllarini tozalaymiz
        shortcode = extract_shortcode(url)
        if shortcode:
            for fname in os.listdir(DOWNLOAD_DIR):
                if shortcode in fname and fname.endswith(".part"):
                    try:
                        os.remove(os.path.join(DOWNLOAD_DIR, fname))
                    except Exception:
                        pass

        # Instaloader zaxira tizimi orqali yuklash
        return _download_with_instaloader_fallback(url)

async def download_instagram_video(url: str, cookies_path: Optional[str] = None) -> VideoInfo:
    """
    Asinxron wrapper: yuklash jarayonini botning event loop'ini
    bloklamasdan alohida thread'da bajaradi.
    """
    clean_url = extract_instagram_url(url) or url
    return await asyncio.to_thread(_download_sync, clean_url, cookies_path)

def cleanup_file(file_path: Optional[str]):
    """Yuborilgandan so'ng diskda joy egallamasligi uchun faylni o'chiradi (Windows fayl bandligi hisobga olingan)."""
    if not file_path or not os.path.exists(file_path):
        return
    import time
    for attempt in range(5):
        try:
            os.remove(file_path)
            logger.info(f"Vaqtinchalik fayl o'chirildi: {file_path}")
            return
        except PermissionError:
            time.sleep(0.5)
        except Exception as e:
            logger.warning(f"Faylni o'chirishda xatolik ({file_path}): {e}")
            return
