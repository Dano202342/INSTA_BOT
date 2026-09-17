import os
from dotenv import load_dotenv

# .env faylini yuklaymiz
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
COOKIES_PATH = os.getenv("INSTAGRAM_COOKIES_PATH", "cookies.txt")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

if not os.path.exists(COOKIES_PATH):
    COOKIES_PATH = None

