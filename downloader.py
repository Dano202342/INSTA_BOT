import os
import re
import asyncio
import logging
from dataclasses import dataclass
from typing import Optional
import yt_dlp

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

def _download_sync(url: str, cookies_path: Optional[str] = None) -> VideoInfo:
    """
    Sinxron ravishda yt-dlp orqali videoni eng yuqori sifatda yuklab oladi.
    Sifatni o'zgartirmasdan, original stream (mp4) saqlanadi.
    """
    outtmpl = os.path.join(DOWNLOAD_DIR, "%(id)s_%(epoch)s.%(ext)s")
    
    ydl_opts = {
        # Eng yuqori sifatli tayyor MP4 video va audio (ffmpeg talab qilmaydi, sifat buzilmaydi)
        'format': 'best[ext=mp4]/best',
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

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        
        # Agar karusel (playlist) bo'lsa birinchi elementni olamiz
        if 'entries' in info and info['entries']:
            info = info['entries'][0]
            
        file_path = ydl.prepare_filename(info)
        
        # Agar kengaytmasi boshqa bo'lib qolsa yoki fayl tekshiruvi
        if not os.path.exists(file_path):
            # Qidirib ko'ramiz
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
            uploader=info.get('uploader') or info.get('channel'),
            duration=info.get('duration'),
            width=info.get('width'),
            height=info.get('height'),
            thumbnail=info.get('thumbnail'),
            filesize_mb=round(size_mb, 2)
        )

async def download_instagram_video(url: str, cookies_path: Optional[str] = None) -> VideoInfo:
    """
    Asinxron wrapper: yt-dlp yuklash jarayonini botning event loop'ini
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
