import os
import time
import uuid
import logging
import asyncio
import subprocess
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# Vaqtinchalik yuklamalar katalogi
DOWNLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

def get_ffmpeg_exe() -> str:
    """imageio_ffmpeg orqali o'rnatilgan ffmpeg binar faylini topadi."""
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as e:
        logger.warning(f"imageio_ffmpeg dan foydalanishda xatolik: {e}. Tizim ffmpeg qidirilmoqda.")
        return "ffmpeg"

# AI ishlov berish rejimlarining ta'riflari va optimallashtirilgan FFmpeg filtrlari
AI_MODES: Dict[str, Dict[str, str]] = {
    "sharpen": {
        "title": "✨ AI Tiniqlashtirish (Ultra HD)",
        "short_title": "✨ Tiniqlashtirish",
        "description": "Detallarni aniq, kontrastli va o'ta tiniq qiladi.",
        "filter": "unsharp=5:5:1.3:5:5:0.0,eq=contrast=1.08:saturation=1.12:brightness=0.01"
    },
    "hdr": {
        "title": "🌈 AI HDR Jonlantirish",
        "short_title": "🌈 AI HDR",
        "description": "Ranglar to'yinganligi, dinamik diapazon va kontrastni kuchaytiradi.",
        "filter": "eq=contrast=1.18:saturation=1.35:brightness=0.02,unsharp=3:3:0.8:3:3:0.0"
    },
    "cinematic": {
        "title": "🎬 AI Kinematik (Teal & Orange)",
        "short_title": "🎬 Kinematik",
        "description": "Kinofilmlardagi kabi chuqur va estetik rang gammasi.",
        "filter": "eq=contrast=1.12:saturation=1.15,colorbalance=rs=0.05:gs=-0.02:bs=-0.05:rm=0.04:gm=0.0:bm=-0.04:rh=-0.03:gh=0.02:bh=0.06"
    },
    "cyberpunk": {
        "title": "🔮 AI Cyberpunk Neon",
        "short_title": "🔮 Cyberpunk",
        "description": "Futuristik yorqin binafsha va havorang neon effekti.",
        "filter": "eq=contrast=1.22:saturation=1.40,colorbalance=rs=0.15:bs=0.20:gs=-0.1:rh=-0.1:gh=0.15:bh=0.25,unsharp=5:5:0.9:5:5:0.0"
    },
    "retro": {
        "title": "📼 AI Retro VHS (90-yillar)",
        "short_title": "📼 Retro VHS",
        "description": "Nostaljik analog lenta va iliq retro ranglar.",
        "filter": "eq=contrast=1.08:saturation=0.88:brightness=0.02,noise=alls=8:allf=t+u"
    },
    "noir": {
        "title": "🖤 AI Klassik Noir (Qora-Oq)",
        "short_title": "🖤 B&W Noir",
        "description": "Yuqori kontrastli, dramatik klassik oq-qora kino uslubi.",
        "filter": "hue=s=0,eq=contrast=1.30:brightness=-0.02,unsharp=5:5:1.1:5:5:0.0"
    }
}

def _process_video_sync(input_path: str, mode: str) -> Tuple[str, float]:
    """
    Sinxron ravishda videoni qayta ishlaydi.
    - Tezkor va barqaror: preset=veryfast, crf=21.
    - Asl ovoz 100% sinxron saqlanadi.
    - Telegramda tez ochilishi uchun faststart qo'shiladi.
    """
    if mode not in AI_MODES:
        mode = "sharpen"

    ffmpeg_bin = get_ffmpeg_exe()
    vf_chain = AI_MODES[mode]["filter"]
    
    unique_id = uuid.uuid4().hex[:8]
    output_filename = f"ai_{mode}_{int(time.time())}_{unique_id}.mp4"
    output_path = os.path.join(DOWNLOAD_DIR, output_filename)

    cmd = [
        ffmpeg_bin,
        "-y",
        "-i", input_path,
        "-vf", vf_chain,
        "-c:v", "libx264",
        "-preset", "veryfast",   # Encoding tezligini bir necha barobar oshiradi
        "-crf", "21",            # Optimal visual sifat va yengil hajm
        "-map", "0:v:0",
        "-map", "0:a?",          # Agar audio bo'lsa uni oladi, bo'lmasa xato bermaydi
        "-c:a", "copy",          # Ovozni qayta siqmasdan asl holda ko'chiradi
        "-movflags", "+faststart",
        output_path
    ]

    logger.info(f"AI ishlov berish boshlandi ({mode}): {output_filename}")
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    if result.returncode != 0:
        err_msg = result.stderr.decode("utf-8", errors="ignore")
        logger.error(f"FFmpeg xatoligi: {err_msg}")
        raise RuntimeError(f"Videoni qayta ishlashda xatolik yuz berdi.")

    if not os.path.exists(output_path):
        raise FileNotFoundError("Chiqish fayli yaratilmadi.")

    size_mb = round(os.path.getsize(output_path) / (1024 * 1024), 2)
    return output_path, size_mb

async def enhance_video_ai(input_path: str, mode: str = "sharpen") -> Tuple[str, float]:
    """Asinxron wrapper: FFmpeg jarayonini boshqa thread'da yurgizadi."""
    return await asyncio.to_thread(_process_video_sync, input_path, mode)
