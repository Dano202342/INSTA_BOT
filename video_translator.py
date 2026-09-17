import os
import re
import time
import json
import uuid
import logging
import asyncio
import subprocess
import urllib.request
import urllib.parse
from typing import Optional, Dict, Any, Tuple
import speech_recognition as sr
import edge_tts

from video_enhancer import get_ffmpeg_exe

logger = logging.getLogger(__name__)

DOWNLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Qo'llab-quvvatlanadigan tillar va ularning neyron ovozlari
TARGET_LANGUAGES: Dict[str, Dict[str, str]] = {
    "uz": {
        "name": "O'zbekcha",
        "flag": "🇺🇿",
        "voice": "uz-UZ-MadinaNeural"
    },
    "ru": {
        "name": "Ruscha",
        "flag": "🇷🇺",
        "voice": "ru-RU-SvetlanaNeural"
    },
    "en": {
        "name": "English",
        "flag": "🇬🇧",
        "voice": "en-US-JennyNeural"
    }
}


def has_audio_stream(video_path: str) -> bool:
    """Videoda audio trek mavjudligini tekshiradi."""
    ffmpeg_bin = get_ffmpeg_exe()
    cmd = [ffmpeg_bin, "-i", video_path]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    output = res.stderr.decode("utf-8", errors="ignore")
    return "Audio:" in output


def extract_audio_wav(video_path: str, output_wav_path: str):
    """
    Videodan inson nutqini yaxshiroq aniqlash uchun audio trekni
    nutq chastotasiga moslangan filtr (80Hz - 8000Hz) va WAV ga ajratadi.
    """
    ffmpeg_bin = get_ffmpeg_exe()
    cmd = [
        ffmpeg_bin, "-y",
        "-i", video_path,
        "-vn",
        "-af", "highpass=f=80,lowpass=f=8000,volume=1.3",
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        output_wav_path
    ]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if res.returncode != 0 or not os.path.exists(output_wav_path):
        raise RuntimeError("Videodan audio ajratib olishda xatolik.")


def _score_candidate(text: str, lang: str, conf: float) -> float:
    """Nutq qaysi tilga ko'proq tegishli ekanini so'zlar va lug'at asosida xolisona baholaydi."""
    if not text or not text.strip():
        return 0.0

    words = [w.lower().strip(".,?!'\"") for w in text.split() if w.strip()]
    if not words:
        return 0.0

    # Asosiy ball: so'zlar soni va umumiy matn uzunligi
    score = len(words) * 2.0 + len(text) * 0.1

    # Har bir tilga xos bo'lgan eng ko'p ishlatiladigan so'zlar
    uz_markers = {
        "va", "bilan", "uchun", "emas", "kerak", "lekin", "bu", "bir", "ham",
        "faqat", "shuning", "sababi", "qilish", "qilib", "boladi", "bitta",
        "endi", "man", "men", "biz", "siz", "ular", "yoq", "bor", "nega",
        "qanday", "nima", "agar", "hozir", "shunday", "balki", "juda"
    }
    ru_markers = {
        "и", "в", "не", "на", "что", "с", "по", "как", "это", "но", "к",
        "для", "от", "он", "она", "они", "мы", "вы", "если", "или", "все",
        "так", "же", "бы", "когда", "то", "уже", "где", "только", "очень"
    }
    en_markers = {
        "the", "and", "to", "of", "a", "in", "that", "have", "i", "it",
        "for", "not", "on", "with", "he", "as", "you", "do", "at", "this",
        "but", "his", "by", "from", "they", "we", "say", "her", "she", "or",
        "an", "will", "my", "one", "all", "would", "there", "their", "what"
    }

    if lang == "uz-UZ":
        found = sum(1 for w in words if w in uz_markers)
        score += found * 6.0
    elif lang == "ru-RU":
        found = sum(1 for w in words if w in ru_markers)
        score += found * 6.0
    elif lang == "en-US":
        found = sum(1 for w in words if w in en_markers)
        score += found * 6.0

    return score * max(0.5, conf)


def _transcribe_sync(wav_path: str) -> Tuple[str, str]:
    """
    WAV audiodan nutqni yuqori aniqlikda aniqlaydi.
    Boshlang'ich qismda tilni xolisona aniqlab, qolgan barcha bo'laklarni
    shu tilda transkripsiya qiladi.
    """
    r = sr.Recognizer()
    r.energy_threshold = 200
    r.dynamic_energy_threshold = True

    with sr.AudioFile(wav_path) as source:
        duration = source.DURATION
        if duration is None or duration <= 0:
            raise ValueError("Audio bo'sh yoki topilmadi.")

        head_len = min(20.0, duration)
        audio_head = r.record(source, duration=head_len)

        detected_lang = "uz-UZ"
        best_score = -1.0
        head_transcript = ""

        # Tilni aniqlash uchun test (o'zbek, rus va ingliz tillari)
        candidate_langs = ["uz-UZ", "ru-RU", "en-US"]
        candidate_results = {}

        for lang in candidate_langs:
            try:
                data = r.recognize_google(audio_head, language=lang, show_all=True)
                if data and isinstance(data, dict) and "alternative" in data:
                    item = data["alternative"][0]
                    conf = item.get("confidence", 0.8)
                    text = item.get("transcript", "").strip()
                    if text:
                        candidate_results[lang] = (text, conf)
            except Exception:
                pass

        for lang, (text, conf) in candidate_results.items():
            score = _score_candidate(text, lang, conf)
            logger.info(f"Til tekshiruvi: {lang} -> Score: {score:.2f} | Matn: {text[:60]}")
            if score > best_score:
                best_score = score
                detected_lang = lang
                head_transcript = text

        logger.info(f"Aniqlangan asosiy til: {detected_lang} (Score: {best_score:.2f})")
        transcripts = [head_transcript] if head_transcript else []

        # Qolgan audio bo'laklarini aniqlangan tilda o'qish
        chunk_size = 20.0
        offset = head_len

        while offset < duration:
            chunk_len = min(chunk_size, duration - offset)
            audio_chunk = r.record(source, duration=chunk_len)
            offset += chunk_len

            try:
                chunk_text = r.recognize_google(audio_chunk, language=detected_lang)
                if chunk_text and chunk_text.strip():
                    transcripts.append(chunk_text.strip())
            except Exception:
                pass

        full_text = " ".join(transcripts).strip()
        if not full_text:
            raise ValueError("Videoda tushunarli inson nutqi aniqlanmadi.")

        return full_text, detected_lang


def _translate_single_chunk(text: str, target_lang: str, source_lang: str = "auto") -> str:
    """Bir nechta tarjima provayderlari (gtx -> chrome-ex -> MyMemory) orqali ishonchli tarjima qilish."""
    if not text or not text.strip():
        return ""

    encoded = urllib.parse.quote(text)

    # 1-urinish: Google gtx
    try:
        url_gtx = (
            f"https://translate.googleapis.com/translate_a/single?"
            f"client=gtx&sl={source_lang}&tl={target_lang}&dt=t&q={encoded}"
        )
        req = urllib.request.Request(
            url_gtx,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            }
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data and data[0]:
                res = "".join([part[0] for part in data[0] if part and part[0]])
                if res and res.strip():
                    return res.strip()
    except Exception as e:
        logger.debug(f"Google gtx xatosi: {e}")

    # 2-urinish: Google dict-chrome-ex
    try:
        url_chrome = (
            f"https://translate.googleapis.com/translate_a/single?"
            f"client=dict-chrome-ex&sl={source_lang}&tl={target_lang}&dt=t&q={encoded}"
        )
        req = urllib.request.Request(
            url_chrome,
            headers={"User-Agent": "Mozilla/5.0"}
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data and data[0]:
                res = "".join([part[0] for part in data[0] if part and part[0]])
                if res and res.strip():
                    return res.strip()
    except Exception as e:
        logger.debug(f"Google chrome-ex xatosi: {e}")

    # 3-urinish: MyMemory Translator (zaxira)
    try:
        from deep_translator import MyMemoryTranslator
        src_tag = f"{source_lang}-{source_lang.upper()}" if len(source_lang) == 2 else source_lang
        tgt_tag = f"{target_lang}-{target_lang.upper()}" if len(target_lang) == 2 else target_lang
        res = MyMemoryTranslator(source=src_tag, target=tgt_tag).translate(text)
        if res and res.strip():
            return res.strip()
    except Exception as e:
        logger.warning(f"MyMemory tarjima xatosi: {e}")

    return text


def translate_text(text: str, target_lang: str = "uz", source_lang: str = "auto") -> str:
    """
    Matnni xavfsiz gaplarga bo'lib, ko'p bosqichli tarjima orqali xatosiz o'giradi.
    Agar manba va maqsad tillari bir xil bo'lsa, ortiqcha tarjima qilinmaydi.
    """
    if not text or not text.strip():
        return ""

    # Agar manba va maqsad tili bir xil bo'lsa
    clean_src = source_lang.split("-")[0].lower() if source_lang else "auto"
    clean_tgt = target_lang.split("-")[0].lower()
    if clean_src != "auto" and clean_src == clean_tgt:
        return text

    # Matnni tinish belgilari bo'yicha gaplarga ajratamiz
    raw_sentences = re.split(r'(?<=[.?!,;\n])\s+', text)
    chunks = []
    current_chunk = ""

    for s in raw_sentences:
        s = s.strip()
        if not s:
            continue
        if len(current_chunk) + len(s) < 350:
            current_chunk += " " + s if current_chunk else s
        else:
            if current_chunk:
                chunks.append(current_chunk.strip())
            current_chunk = s

    if current_chunk:
        chunks.append(current_chunk.strip())

    translated_parts = []
    for c in chunks:
        res = _translate_single_chunk(c, target_lang, source_lang)
        translated_parts.append(res if res else c)

    return " ".join(translated_parts).strip()


def extract_audio_mp3(video_path: str, output_mp3_path: str):
    """Videodan Gemini AI uchun ixcham va sifatli MP3 audio ajratib oladi."""
    ffmpeg_bin = get_ffmpeg_exe()
    cmd = [
        ffmpeg_bin, "-y",
        "-i", video_path,
        "-vn",
        "-acodec", "libmp3lame",
        "-ar", "24000",
        "-ac", "1",
        "-b:a", "64k",
        output_mp3_path
    ]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if res.returncode != 0 or not os.path.exists(output_mp3_path):
        raise RuntimeError("Videodan MP3 ajratishda xatolik yuz berdi.")


def _gemini_transcribe_and_translate(audio_path: str, target_lang: str = "uz") -> Optional[Dict[str, Any]]:
    """
    Google Gemini 2.5 / 2.0 Flash orqali nutqni bexato eshitish,
    fon musiqasidan ajratish va tabiiy tarjima qilish.
    """
    from config import GEMINI_API_KEY
    if not GEMINI_API_KEY:
        return None

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=GEMINI_API_KEY)
        lang_info = TARGET_LANGUAGES.get(target_lang, TARGET_LANGUAGES["uz"])
        target_name = lang_info["name"]

        prompt = (
            "You are an expert audio speech recognition and translation AI. "
            "Listen carefully to the human speech in this audio clip, even if there is loud background music or sound effects.\n"
            "1. Extract and transcribe the human speech in its original language accurately. If there is NO human speech (only music, silence, or noise), set 'has_speech' to false.\n"
            "2. Identify the detected spoken language (e.g. uz for Uzbek, ru for Russian, en for English, etc.).\n"
            f"3. Translate the spoken text accurately into {target_name} ({target_lang}). "
            "Make the translation sound completely natural, fluent, and conversational, preserving original meaning.\n"
            "Return ONLY a valid JSON object matching this schema:\n"
            "{\n"
            '  "has_speech": true,\n'
            '  "original_text": "original transcription here",\n'
            '  "detected_lang": "uz",\n'
            '  "translated_text": "translated text here"\n'
            "}"
        )

        with open(audio_path, "rb") as f:
            audio_data = f.read()

        # Ketma-ket eng yangi Gemini modellarini sinab ko'ramiz
        models_to_try = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]
        for model_name in models_to_try:
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=[
                        types.Part.from_bytes(data=audio_data, mime_type="audio/mp3"),
                        prompt
                    ],
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json"
                    )
                )

                if response and response.text:
                    clean_json = response.text.strip()
                    if clean_json.startswith("```json"):
                        clean_json = clean_json[7:]
                    if clean_json.endswith("```"):
                        clean_json = clean_json[:-3]
                    clean_json = clean_json.strip()

                    result = json.loads(clean_json)
                    if not result.get("has_speech", True):
                        raise ValueError("Videoda tushunarli inson nutqi aniqlanmadi (faqat musiqa yoki shovqin).")

                    orig = result.get("original_text", "").strip()
                    trans = result.get("translated_text", "").strip()
                    det = result.get("detected_lang", target_lang).strip()

                    if not orig:
                        raise ValueError("Videoda inson nutqi aniqlanmadi.")

                    logger.info(f"Gemini AI ({model_name}) muvaffaqiyatli bajardi! Til: {det}")
                    return {
                        "original_text": orig,
                        "translated_text": trans if trans else orig,
                        "detected_lang": det,
                        "ai_engine": f"Gemini Flash ({model_name})"
                    }
            except ValueError:
                raise
            except Exception as me:
                logger.warning(f"Gemini {model_name} modelida xatolik: {me}. Keyingi model tekshirilmoqda...")
                continue

        return None
    except ValueError:
        raise
    except Exception as e:
        logger.error(f"Gemini API umumiy xatoligi: {e}", exc_info=True)
        return None


async def generate_tts(text: str, target_lang: str, output_mp3_path: str):
    """Matnni Edge-TTS tabiiy neyron ovozlari yordamida audio qiladi."""
    lang_config = TARGET_LANGUAGES.get(target_lang, TARGET_LANGUAGES["uz"])
    voice = lang_config["voice"]

    # Agar matn juda uzun bo'lsa biroz tezroq gapirish
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(output_mp3_path)

    if not os.path.exists(output_mp3_path) or os.path.getsize(output_mp3_path) == 0:
        raise FileNotFoundError("TTS audio yaratilmadi.")


def _mix_video_sync(video_path: str, tts_audio_path: str, output_path: str):
    """
    Video ustiga yangi tarjima qilingan ovozni mikser qiladi.
    - Fon audiosi 15% ga pasaytiriladi (audio ducking).
    - Yangi ovoz 135% hajmda aniq va tiniq eshitiladi.
    - Video o'zining asl sifatini saqlaydi (-c:v copy).
    """
    ffmpeg_bin = get_ffmpeg_exe()

    if has_audio_stream(video_path):
        filter_str = "[0:a]volume=0.15[bg];[1:a]volume=1.35[fg];[bg][fg]amix=inputs=2:duration=first:dropout_transition=2[aout]"
        cmd = [
            ffmpeg_bin, "-y",
            "-i", video_path,
            "-i", tts_audio_path,
            "-filter_complex", filter_str,
            "-map", "0:v:0",
            "-map", "[aout]",
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            "-movflags", "+faststart",
            output_path
        ]
    else:
        cmd = [
            ffmpeg_bin, "-y",
            "-i", video_path,
            "-i", tts_audio_path,
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            "-movflags", "+faststart",
            output_path
        ]

    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if res.returncode != 0 or not os.path.exists(output_path):
        err = res.stderr.decode("utf-8", errors="ignore")
        logger.error(f"FFmpeg dublyaj xatoligi: {err}")
        raise RuntimeError("Videoni dublyaj qilishda xatolik yuz berdi.")


async def translate_and_dub_video(
    video_path: str,
    target_lang: str = "uz"
) -> Dict[str, Any]:
    """
    Videoni tarjima qilish va dublyaj qilish to'liq asinxron pipeline:
    1. Gemini AI (agar kalit kiritilgan bo'lsa) orqali to'g'ridan-to'g'ri audiodan transkripsiya va tarjima.
    2. Zaxira tizim: Audio ajratish -> SpeechRecognition -> Multi-tier Translator.
    3. Edge-TTS tabiiy neyron ovozlashtirish.
    4. Video va ovozni avtomatik mikser qilish (Audio Ducking).
    """
    from config import GEMINI_API_KEY

    tag = uuid.uuid4().hex[:8]
    wav_path = os.path.join(DOWNLOAD_DIR, f"temp_{tag}.wav")
    gemini_mp3_path = os.path.join(DOWNLOAD_DIR, f"gemini_{tag}.mp3")
    tts_path = os.path.join(DOWNLOAD_DIR, f"tts_{tag}.mp3")
    output_video_path = os.path.join(DOWNLOAD_DIR, f"dubbed_{target_lang}_{int(time.time())}_{tag}.mp4")

    original_text = ""
    translated_text = ""
    detected_lang = target_lang
    ai_engine = "Standart AI"

    try:
        # 1. Agar GEMINI_API_KEY mavjud bo'lsa, avval Gemini AI orqali harakat qilamiz!
        if GEMINI_API_KEY:
            try:
                await asyncio.to_thread(extract_audio_mp3, video_path, gemini_mp3_path)
                gemini_res = await asyncio.to_thread(_gemini_transcribe_and_translate, gemini_mp3_path, target_lang)
                if gemini_res:
                    original_text = gemini_res["original_text"]
                    translated_text = gemini_res["translated_text"]
                    detected_lang = gemini_res["detected_lang"]
                    ai_engine = gemini_res.get("ai_engine", "Google Gemini AI")
            except ValueError:
                raise
            except Exception as ge:
                logger.warning(f"Gemini AI orqali ishlashda xatolik: {ge}. Standart tizimga o'tilmoqda...")

        # 2. Agar Gemini ishlatilmagan bo'lsa yoki kalit yo'q bo'lsa -> Zaxira SpeechRecognition tizimi
        if not original_text:
            await asyncio.to_thread(extract_audio_wav, video_path, wav_path)
            original_text, detected_lang = await asyncio.to_thread(_transcribe_sync, wav_path)
            src_code = detected_lang.split("-")[0] if "-" in detected_lang else detected_lang
            translated_text = await asyncio.to_thread(translate_text, original_text, target_lang, src_code)
            ai_engine = "SpeechRecognition (Offline/Web)"

        # 3. Yangi tildagi audio hosil qilish (Edge-TTS)
        await generate_tts(translated_text, target_lang, tts_path)

        # 4. Videoni yangi audio bilan dublyaj qilish
        await asyncio.to_thread(_mix_video_sync, video_path, tts_path, output_video_path)

        size_mb = round(os.path.getsize(output_video_path) / (1024 * 1024), 2)

        return {
            "output_video_path": output_video_path,
            "original_text": original_text,
            "translated_text": translated_text,
            "detected_lang": detected_lang,
            "target_lang": target_lang,
            "file_size_mb": size_mb,
            "ai_engine": ai_engine
        }

    finally:
        # Vaqtinchalik audio fayllarni tozalash
        for temp_f in [wav_path, gemini_mp3_path, tts_path]:
            if os.path.exists(temp_f):
                try:
                    os.remove(temp_f)
                except Exception:
                    pass

