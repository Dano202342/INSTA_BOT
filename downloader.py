import os
import re
import time
import uuid
import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional, List, Tuple, Dict, Any
import requests
import yt_dlp
import subprocess

from video_enhancer import get_ffmpeg_exe

logger = logging.getLogger(__name__)

# Vaqtinchalik yuklamalar katalogi
DOWNLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# 7 ta asosiy platforma konfiguratsiyasi
PLATFORMS: Dict[str, Dict[str, Any]] = {
    "instagram": {
        "name": "Instagram",
        "icon": "📸",
        "desc": "post, stories, reels, rasm",
        "regex": re.compile(
            r"https?://(?:www\.)?instagram\.com/(?:p|reel|reels|tv|stories|share)/[a-zA-Z0-9_\-\./]+|https?://instagr\.am/[a-zA-Z0-9_\-\./]+",
            re.IGNORECASE
        )
    },
    "youtube": {
        "name": "YouTube",
        "icon": "🔴",
        "desc": "video, shorts, audio",
        "regex": re.compile(
            r"https?://(?:www\.|m\.)?(?:youtube\.com/(?:watch\?[^ \n\r\t]+|shorts/[a-zA-Z0-9_\-]+|embed/[a-zA-Z0-9_\-]+|live/[a-zA-Z0-9_\-]+)|youtu\.be/[a-zA-Z0-9_\-]+)",
            re.IGNORECASE
        )
    },
    "tiktok": {
        "name": "TikTok",
        "icon": "🎵",
        "desc": "suv belgisiz video",
        "regex": re.compile(
            r"https?://(?:www\.|vt\.|vm\.)?tiktok\.com/[a-zA-Z0-9_\-\./@?=&]+",
            re.IGNORECASE
        )
    },
    "facebook": {
        "name": "Facebook",
        "icon": "🔵",
        "desc": "reels, rasm, video",
        "regex": re.compile(
            r"https?://(?:www\.|web\.|m\.)?(?:facebook\.com/(?:reel|watch|stories|[a-zA-Z0-9\._\-]+/videos|[a-zA-Z0-9\._\-]+/posts|share)/[a-zA-Z0-9_\-\./?=&]+|fb\.watch/[a-zA-Z0-9_\-]+|fb\.com/[a-zA-Z0-9_\-\./?=&]+)",
            re.IGNORECASE
        )
    },
    "pinterest": {
        "name": "Pinterest",
        "icon": "📌",
        "desc": "rasm, video",
        "regex": re.compile(
            r"https?://(?:[a-zA-Z0-9]+\.)?pinterest\.[a-z\.]+/(?:pin/[0-9]+|pin/[a-zA-Z0-9_\-]+)/?|https?://pin\.it/[a-zA-Z0-9_\-]+",
            re.IGNORECASE
        )
    },
    "snapchat": {
        "name": "Snapchat",
        "icon": "👻",
        "desc": "rasm, video",
        "regex": re.compile(
            r"https?://(?:www\.|story\.|t\.)?snapchat\.com/(?:spotlight|add|story|t)/[a-zA-Z0-9_\-\./?=&]+",
            re.IGNORECASE
        )
    },
    "telegram": {
        "name": "Telegram",
        "icon": "✈️",
        "desc": "hikoya, post",
        "regex": re.compile(
            r"https?://t\.me/(?:[a-zA-Z0-9_]+/s/[0-9]+|[a-zA-Z0-9_]+/[0-9]+|[a-zA-Z0-9_]+\?story=[0-9]+|b/story/[a-zA-Z0-9_]+)",
            re.IGNORECASE
        )
    }
}

GENERIC_URL_REGEX = re.compile(r"https?://[^\s<>\"'{}|\\^`]+", re.IGNORECASE)


@dataclass
class MediaItem:
    media_type: str  # "video", "photo", "audio"
    file_path: str
    title: Optional[str] = None
    uploader: Optional[str] = None
    duration: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None
    thumbnail: Optional[str] = None
    filesize_mb: float = 0.0


@dataclass
class DownloadResult:
    platform_key: str
    platform_name: str
    platform_icon: str
    items: List[MediaItem] = field(default_factory=list)
    title: Optional[str] = None
    uploader: Optional[str] = None
    original_url: str = ""


# Oldingi kodlar bilan to'liq mos kelishi uchun:
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


def detect_platform(url: str) -> Tuple[str, Dict[str, Any]]:
    """Berilgan havola qaysi platformaga tegishli ekanligini aniqlaydi."""
    for key, p in PLATFORMS.items():
        if p["regex"].search(url):
            return key, p
    return "generic", {"name": "Internet", "icon": "🌐", "desc": "media"}


def extract_media_url(text: str) -> Optional[str]:
    """Matn ichidan birinchi mos keluvchi havolani ajratib oladi."""
    if not text:
        return None
    # Avval 7 ta asosiy platforma bo'yicha tekshiramiz
    for key, p in PLATFORMS.items():
        match = p["regex"].search(text)
        if match:
            return match.group(0).strip()
    # Umumiy http(s) havola
    match = GENERIC_URL_REGEX.search(text)
    if match:
        return match.group(0).strip()
    return None


def is_supported_url(text: str) -> bool:
    """Matnda yuklab olinadigan havola mavjudligini tekshiradi."""
    return extract_media_url(text) is not None


# Eski funksiyalar (main.py bilan mos kelishi uchun)
def is_instagram_url(text: str) -> bool:
    return is_supported_url(text)


def extract_instagram_url(text: str) -> Optional[str]:
    return extract_media_url(text)


def extract_shortcode(url: str) -> Optional[str]:
    match = re.search(r"instagram\.com/(?:p|reel|reels|tv)/([a-zA-Z0-9_-]+)", url, re.I)
    if match:
        return match.group(1)
    return None


def resolve_shortlink(url: str) -> str:
    """Qisqartirilgan havolalarning (pin.it, fb.watch, vt.tiktok.com va h.k.) asl manzilini topadi."""
    if any(domain in url.lower() for domain in ["pin.it", "fb.watch", "vt.tiktok.com", "vm.tiktok.com", "t.snapchat.com", "youtu.be"]):
        try:
            resp = requests.head(
                url,
                allow_redirects=True,
                timeout=10,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
            )
            if resp.url:
                return resp.url
        except Exception as e:
            logger.debug(f"Havola redirect tekshirishda xatolik: {e}")
    return url


# -------------------------------------------------------------
# 1. TIKTOK SUVSIS (TIKWM) ZAXIRA TIZIMI
# -------------------------------------------------------------
def _download_tiktok_tikwm(url: str) -> Optional[List[MediaItem]]:
    """TikTok'dan suv belgisiz (watermark-free) video yoki rasmlarni yuklab oluvchi mustahkam tizim."""
    try:
        api_url = "https://www.tikwm.com/api/"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        }
        resp = requests.post(api_url, data={"url": url}, headers=headers, timeout=20)
        data = resp.json()
        if data.get("code") != 0 or "data" not in data:
            return None

        tdata = data["data"]
        title = tdata.get("title") or "TikTok Video"
        uploader = tdata.get("author", {}).get("unique_id") or "TikTok"

        # Agar rasm to'plami (photo mode) bo'lsa
        if "images" in tdata and isinstance(tdata["images"], list) and tdata["images"]:
            items = []
            for idx, img_url in enumerate(tdata["images"]):
                img_path = os.path.join(DOWNLOAD_DIR, f"tiktok_{uuid.uuid4().hex[:8]}_{idx}.jpg")
                r_img = requests.get(img_url, headers=headers, timeout=25)
                r_img.raise_for_status()
                with open(img_path, "wb") as f:
                    f.write(r_img.content)
                size_mb = round(os.path.getsize(img_path) / (1024 * 1024), 2)
                items.append(MediaItem(
                    media_type="photo",
                    file_path=img_path,
                    title=title,
                    uploader=uploader,
                    filesize_mb=size_mb
                ))
            return items

        # Agar video bo'lsa (suv belgisisiz)
        video_url = tdata.get("play") or tdata.get("wmplay")
        if video_url:
            vid_path = os.path.join(DOWNLOAD_DIR, f"tiktok_{uuid.uuid4().hex[:8]}.mp4")
            with requests.get(video_url, headers=headers, stream=True, timeout=60) as r_vid:
                r_vid.raise_for_status()
                with open(vid_path, "wb") as f:
                    for chunk in r_vid.iter_content(chunk_size=128 * 1024):
                        if chunk:
                            f.write(chunk)
            if os.path.exists(vid_path) and os.path.getsize(vid_path) > 0:
                size_mb = round(os.path.getsize(vid_path) / (1024 * 1024), 2)
                return [MediaItem(
                    media_type="video",
                    file_path=vid_path,
                    title=title,
                    uploader=uploader,
                    duration=tdata.get("duration"),
                    filesize_mb=size_mb
                )]
    except Exception as e:
        logger.warning(f"TikWM orqali yuklashda xatolik: {e}")
    return None


# -------------------------------------------------------------
# 2. PINTEREST RASM VA VIDEO ZAXIRA TIZIMI
# -------------------------------------------------------------
def _download_pinterest_direct(url: str) -> Optional[List[MediaItem]]:
    """Pinterest sahifasidan original sifatdagi rasm yoki videoni yuklab oladi."""
    try:
        resolved = resolve_shortlink(url)
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        }
        resp = requests.get(resolved, headers=headers, timeout=15)
        html = resp.text

        # 1. Video tekshirish
        video_m = re.search(r'"contentUrl":\s*"([^"]+)"', html) or re.search(r'<video[^>]+src="([^"]+)"', html)
        if video_m:
            vid_url = video_m.group(1).replace("\\u0026", "&")
            vid_path = os.path.join(DOWNLOAD_DIR, f"pin_vid_{uuid.uuid4().hex[:8]}.mp4")
            with requests.get(vid_url, headers=headers, stream=True, timeout=60) as r_vid:
                r_vid.raise_for_status()
                with open(vid_path, "wb") as f:
                    for chunk in r_vid.iter_content(chunk_size=128 * 1024):
                        if chunk:
                            f.write(chunk)
            if os.path.exists(vid_path) and os.path.getsize(vid_path) > 0:
                size_mb = round(os.path.getsize(vid_path) / (1024 * 1024), 2)
                return [MediaItem(
                    media_type="video",
                    file_path=vid_path,
                    title="Pinterest Video",
                    uploader="Pinterest",
                    filesize_mb=size_mb
                )]

        # 2. Asl sifatdagi rasm (originals)
        img_url = None
        orig_match = re.search(r'https://i\.pinimg\.com/originals/[a-zA-Z0-9/_\-\.]+\.(?:jpg|jpeg|png|webp)', html)
        if orig_match:
            img_url = orig_match.group(0)
        else:
            og_match = re.search(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"', html)
            if og_match:
                img_url = re.sub(r'/(?:236x|474x|736x)/', '/originals/', og_match.group(1))

        if img_url:
            ext = os.path.splitext(img_url.split("?")[0])[1] or ".jpg"
            img_path = os.path.join(DOWNLOAD_DIR, f"pin_img_{uuid.uuid4().hex[:8]}{ext}")
            r_img = requests.get(img_url, headers=headers, timeout=25)
            r_img.raise_for_status()
            with open(img_path, "wb") as f:
                f.write(r_img.content)
            size_mb = round(os.path.getsize(img_path) / (1024 * 1024), 2)
            return [MediaItem(
                media_type="photo",
                file_path=img_path,
                title="Pinterest Photo",
                uploader="Pinterest",
                filesize_mb=size_mb
            )]
    except Exception as e:
        logger.warning(f"Pinterest to'g'ridan-to'g'ri yuklashda xatolik: {e}")
    return None


# -------------------------------------------------------------
# 3. TELEGRAM HIKOYA VA EMBED ZAXIRA TIZIMI
# -------------------------------------------------------------
def _download_telegram_embed(url: str) -> Optional[List[MediaItem]]:
    """Telegram ommaviy post va hikoyalari (embed) orqali media yuklash."""
    try:
        clean_url = url.split("?")[0].rstrip("/") + "?embed=1"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        }
        resp = requests.get(clean_url, headers=headers, timeout=15)
        html = resp.text

        # Video bormi?
        video_m = re.search(r'<video[^>]+src=[\'"]([^\'"]+)[\'"]', html)
        if video_m:
            vid_url = video_m.group(1)
            vid_path = os.path.join(DOWNLOAD_DIR, f"tg_{uuid.uuid4().hex[:8]}.mp4")
            with requests.get(vid_url, headers=headers, stream=True, timeout=60) as r_vid:
                r_vid.raise_for_status()
                with open(vid_path, "wb") as f:
                    for chunk in r_vid.iter_content(chunk_size=128 * 1024):
                        if chunk:
                            f.write(chunk)
            if os.path.exists(vid_path) and os.path.getsize(vid_path) > 0:
                size_mb = round(os.path.getsize(vid_path) / (1024 * 1024), 2)
                return [MediaItem(
                    media_type="video",
                    file_path=vid_path,
                    title="Telegram Video / Story",
                    uploader="Telegram",
                    filesize_mb=size_mb
                )]

        # Rasm bormi?
        img_m = re.search(r'background-image:url\([\'"]?([^\'"\)]+)[\'"]?\)', html)
        if img_m and not img_m.group(1).endswith(".png") and "telegram.org" not in img_m.group(1):
            img_url = img_m.group(1)
            img_path = os.path.join(DOWNLOAD_DIR, f"tg_{uuid.uuid4().hex[:8]}.jpg")
            r_img = requests.get(img_url, headers=headers, timeout=25)
            r_img.raise_for_status()
            with open(img_path, "wb") as f:
                f.write(r_img.content)
            size_mb = round(os.path.getsize(img_path) / (1024 * 1024), 2)
            return [MediaItem(
                media_type="photo",
                file_path=img_path,
                title="Telegram Photo / Story",
                uploader="Telegram",
                filesize_mb=size_mb
            )]
    except Exception as e:
        logger.warning(f"Telegram embed yuklashda xatolik: {e}")
    return None


# -------------------------------------------------------------
# 4. INSTAGRAM INSTALOADER ZAXIRA TIZIMI
# -------------------------------------------------------------
def _download_with_instaloader_fallback(url: str) -> List[MediaItem]:
    """Instaloader orqali post, reel yoki albomni (karusel) yuklash."""
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
    uploader = post.owner_username or "Instagram"
    caption = post.caption[:120] if post.caption else "Instagram Media"

    items: List[MediaItem] = []

    # 1. Yagona video bo'lsa
    if post.is_video:
        file_path = os.path.join(DOWNLOAD_DIR, f"insta_{shortcode}_{int(time.time())}.mp4")
        with requests.get(post.video_url, stream=True, timeout=60) as resp:
            resp.raise_for_status()
            with open(file_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=128 * 1024):
                    if chunk:
                        f.write(chunk)
        size_mb = round(os.path.getsize(file_path) / (1024 * 1024), 2)
        items.append(MediaItem(
            media_type="video",
            file_path=file_path,
            title=caption,
            uploader=uploader,
            duration=post.video_duration,
            filesize_mb=size_mb
        ))
        return items

    # 2. Albom (karusel - bir nechta rasm/video) bo'lsa
    if post.typename == "GraphSidecar":
        for idx, node in enumerate(post.get_sidecar_nodes()):
            if node.is_video:
                f_path = os.path.join(DOWNLOAD_DIR, f"insta_{shortcode}_{idx}.mp4")
                with requests.get(node.video_url, stream=True, timeout=60) as resp:
                    resp.raise_for_status()
                    with open(f_path, "wb") as f:
                        for chunk in resp.iter_content(chunk_size=128 * 1024):
                            if chunk:
                                f.write(chunk)
                s_mb = round(os.path.getsize(f_path) / (1024 * 1024), 2)
                items.append(MediaItem(
                    media_type="video",
                    file_path=f_path,
                    title=caption,
                    uploader=uploader,
                    filesize_mb=s_mb
                ))
            else:
                f_path = os.path.join(DOWNLOAD_DIR, f"insta_{shortcode}_{idx}.jpg")
                r_img = requests.get(node.display_url, timeout=25)
                r_img.raise_for_status()
                with open(f_path, "wb") as f:
                    f.write(r_img.content)
                s_mb = round(os.path.getsize(f_path) / (1024 * 1024), 2)
                items.append(MediaItem(
                    media_type="photo",
                    file_path=f_path,
                    title=caption,
                    uploader=uploader,
                    filesize_mb=s_mb
                ))
        if items:
            return items

    # 3. Yagona rasm bo'lsa
    if post.url:
        f_path = os.path.join(DOWNLOAD_DIR, f"insta_{shortcode}.jpg")
        r_img = requests.get(post.url, timeout=25)
        r_img.raise_for_status()
        with open(f_path, "wb") as f:
            f.write(r_img.content)
        s_mb = round(os.path.getsize(f_path) / (1024 * 1024), 2)
        items.append(MediaItem(
            media_type="photo",
            file_path=f_path,
            title=caption,
            uploader=uploader,
            filesize_mb=s_mb
        ))
        return items

    raise ValueError("Instagram postidan media fayllar ajratib olinmadi.")


# -------------------------------------------------------------
# 5. ASOSIY MULTI-PLATFORMA YUKLOVCHI (YT-DLP)
# -------------------------------------------------------------
def _download_sync(url: str, cookies_path: Optional[str] = None) -> DownloadResult:
    """Barcha platformalarni sinxron tartibda tahlil qilib, yuklab oladi."""
    resolved_url = resolve_shortlink(url)
    pkey, pmeta = detect_platform(resolved_url)
    outtmpl = os.path.join(DOWNLOAD_DIR, f"{pkey}_%(id)s_%(epoch)s.%(ext)s")
    ffmpeg_bin = get_ffmpeg_exe()

    # Maxsus platformalarga moslashtirilgan formatlar
    if pkey == "youtube":
        # Telegram Bot API cheklovi: 50MB
        fmt = "bestvideo[filesize<45M][ext=mp4]+bestaudio[filesize<45M][ext=m4a]/bestvideo[filesize<45M]+bestaudio[filesize<45M]/best[filesize<48M]/best"
    elif pkey == "tiktok":
        # TikTok suv belgisiz stream
        fmt = "bestvideo+bestaudio/best"
    else:
        fmt = "bestvideo+bestaudio/best"

    ydl_opts = {
        "format": fmt,
        "merge_output_format": "mp4",
        "ffmpeg_location": ffmpeg_bin,
        "outtmpl": outtmpl,
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "max_filesize": 50 * 1024 * 1024,
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        },
    }

    if cookies_path and os.path.exists(cookies_path):
        ydl_opts["cookiefile"] = cookies_path

    items: List[MediaItem] = []
    main_title = None
    main_uploader = None

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(resolved_url, download=True)
            if not info:
                raise ValueError("Media haqida ma'lumot olinmadi.")

            entries = info.get("entries") if "entries" in info and info["entries"] else [info]

            for entry in entries:
                if not entry:
                    continue
                file_path = ydl.prepare_filename(entry)
                if not os.path.exists(file_path):
                    base, _ = os.path.splitext(file_path)
                    for ext in [".mp4", ".mkv", ".webm", ".jpg", ".png", ".webp", ".m4a", ".mp3"]:
                        if os.path.exists(base + ext):
                            file_path = base + ext
                            break

                if os.path.exists(file_path):
                    ext = os.path.splitext(file_path)[1].lower()
                    if ext in [".jpg", ".jpeg", ".png", ".webp"]:
                        mtype = "photo"
                    elif ext in [".mp3", ".m4a", ".wav", ".aac"]:
                        mtype = "audio"
                    else:
                        mtype = "video"

                    sz = round(os.path.getsize(file_path) / (1024 * 1024), 2)
                    title = entry.get("title") or entry.get("description") or f"{pmeta['name']} Media"
                    uploader = entry.get("uploader") or entry.get("channel") or pmeta["name"]
                    if not main_title:
                        main_title = title
                    if not main_uploader:
                        main_uploader = uploader

                    items.append(MediaItem(
                        media_type=mtype,
                        file_path=file_path,
                        title=title,
                        uploader=uploader,
                        duration=entry.get("duration"),
                        width=entry.get("width"),
                        height=entry.get("height"),
                        thumbnail=entry.get("thumbnail"),
                        filesize_mb=sz
                    ))

        if items:
            return DownloadResult(
                platform_key=pkey,
                platform_name=pmeta["name"],
                platform_icon=pmeta["icon"],
                items=items,
                title=main_title,
                uploader=main_uploader,
                original_url=resolved_url
            )

    except Exception as ydl_err:
        logger.warning(f"yt-dlp xatoligi ({pkey}): {ydl_err}. Zaxira usullar tekshirilmoqda...")

    # Maxsus platforma zaxira tizimlari (Fallbacks)
    fallback_items = None
    if pkey == "tiktok":
        fallback_items = _download_tiktok_tikwm(resolved_url)
    elif pkey == "pinterest":
        fallback_items = _download_pinterest_direct(resolved_url)
    elif pkey == "telegram":
        fallback_items = _download_telegram_embed(resolved_url)
    elif pkey == "instagram":
        try:
            fallback_items = _download_with_instaloader_fallback(resolved_url)
        except Exception as inst_err:
            logger.warning(f"Instaloader xatoligi: {inst_err}")

    if fallback_items:
        first = fallback_items[0]
        return DownloadResult(
            platform_key=pkey,
            platform_name=pmeta["name"],
            platform_icon=pmeta["icon"],
            items=fallback_items,
            title=first.title,
            uploader=first.uploader,
            original_url=resolved_url
        )

    raise ValueError(f"Ushbu havoladan {pmeta['name']} mediasini yuklab bo'lmadi. Havola to'g'riligini yoki ochiqligini tekshiring.")


async def download_media(url: str, cookies_path: Optional[str] = None) -> DownloadResult:
    """Asinxron holda barcha platformalardan media yuklab oluvchi asosiy funksiya."""
    return await asyncio.to_thread(_download_sync, url, cookies_path)


# Eski funksiya bilan to'liq mos kelishi uchun:
async def download_instagram_video(url: str, cookies_path: Optional[str] = None) -> VideoInfo:
    res = await download_media(url, cookies_path)
    if not res.items:
        raise FileNotFoundError("Video topilmadi.")
    first = res.items[0]
    return VideoInfo(
        file_path=first.file_path,
        title=first.title,
        uploader=first.uploader,
        duration=first.duration,
        width=first.width,
        height=first.height,
        thumbnail=first.thumbnail,
        filesize_mb=first.filesize_mb
    )


async def extract_audio_mp3(video_path: str) -> Tuple[str, float]:
    """Videodan yuqori sifatli (192kbps) MP3 audio ajratib oladi."""
    ffmpeg_bin = get_ffmpeg_exe()
    out_path = os.path.splitext(video_path)[0] + f"_audio_{uuid.uuid4().hex[:6]}.mp3"

    cmd = [
        ffmpeg_bin,
        "-y",
        "-i", video_path,
        "-vn",
        "-c:a", "libmp3lame",
        "-b:a", "192k",
        out_path
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0 or not os.path.exists(out_path):
        err_msg = stderr.decode(errors="replace") if stderr else "Noma'lum xatolik"
        raise RuntimeError(f"MP3 audio ajratishda xatolik: {err_msg[:200]}")

    size_mb = round(os.path.getsize(out_path) / (1024 * 1024), 2)
    return out_path, size_mb


def cleanup_file(file_path: Optional[str]):
    """Vaqtinchalik fayllarni diskdan xavfsiz o'chiradi."""
    if not file_path or not os.path.exists(file_path):
        return
    for _ in range(5):
        try:
            os.remove(file_path)
            logger.info(f"Vaqtinchalik fayl o'chirildi: {file_path}")
            return
        except PermissionError:
            time.sleep(0.4)
        except Exception as e:
            logger.warning(f"Faylni o'chirishda xatolik ({file_path}): {e}")
            return
