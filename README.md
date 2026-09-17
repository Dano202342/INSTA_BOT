# 📱 Instagram Downloader, AI Enhancer & Video Translator Bot

Ushbu Telegram bot Instagram'dagi **Reels**, **Post videolar** va **IGTV** videolarini original sifatda yuklab beradi, videolarni **tiniqlashtiradi (Ultra HD)** hamda videolardagi nutqni avtomatik aniqlab **O'zbekcha**, **Ruscha** va **Inglizcha** tillariga **AI dublyaj (ovozli tarjima)** qilib beradi!

---

## 🌟 Asosiy Imkoniyatlari

### 1. 🌐 Video Tarjima va AI Dublyaj (YANGI!)
- **Avtomatik nutqni aniqlash (Speech-to-Text):** Videodagi gaplarni avtomatik aniqlaydi.
- **3 ta asosiy tilga tarjima:**
  - 🇺🇿 **O'zbekcha Dublyaj:** Tabiiy neyron ovoz (`uz-UZ-MadinaNeural`).
  - 🇷🇺 **Ruscha Dublyaj:** Tabiiy neyron ovoz (`ru-RU-SvetlanaNeural`).
  - 🇬🇧 **English Voiceover:** Tabiiy neyron ovoz (`en-US-JennyNeural`).
- **Audio Ducking:** Asl fon musiqasi to'liq o'chirilmaydi (15% hajmda orqada eshitilib turadi), tarjima qilingan yangi ovoz esa 130% balandlikda tiniq eshitiladi.
- **Matnli transkripsiya:** Video bilan birga asl matn va tarjima qilingan matn ham Telegram xabarida beriladi.

### 2. ✨ AI Video Tiniqlashtirish va Stil O'zgartirish
- **✨ AI Tiniqlashtirish (Ultra HD):** Xiralikni yo'qotib, har bir detalni aniq va tiniq qiladi.
- **🌈 AI HDR:** Ranglar to'yinganligi va dinamik diapazonni oshiradi.
- **🎬 AI Kinematik:** Teal & Orange kino effekti.
- **🔮 AI Cyberpunk:** Neon futuristik effekt.
- **📼 AI Retro VHS:** 90-yillar analog videokamera nostaljisi.
- **🖤 AI B&W Noir:** Dramatik qora-oq kino uslubi.

### 3. 📥 Instagram Video Yuklash
- **Asl sifat:** Hech qanday siqishlarsiz eng yuqori sifatli MP4 oqimi.
- **Avtomatik Streaming:** Video kelishi bilanoq Telegram'da ijro etiladi.

---

## 🛠 O'rnatish va Ishga tushirish

```bash
# 1. Kutubxonalarni o'rnatish
python -m pip install -r requirements.txt

# 2. Botni ishga tushirish
python -u main.py
```

---

## 📁 Loyiha tarkibi

- [`main.py`](main.py) — Botning asosiy boshqaruv kodi va Telegram menyulari.
- [`video_translator.py`](video_translator.py) — Nutqni aniqlash, tarjima qilish, TTS va video dublyaj moduli.
- [`video_enhancer.py`](video_enhancer.py) — AI video filtrlari va tiniqlashtirish moduli.
- [`downloader.py`](downloader.py) — Instagram havolalarini yuklovchi modul (yt-dlp).
- [`config.py`](config.py) — Sozlamalar va token.
- [`.env`](.env) — Bot tokeni.
- [`requirements.txt`](requirements.txt) — Bog'liqliklar ro'yxati.
