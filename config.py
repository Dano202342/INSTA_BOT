import os
from dotenv import load_dotenv

# .env faylini yuklaymiz
load_dotenv()

raw_token = (
    os.getenv("BOT_TOKEN")
    or os.getenv("TELEGRAM_BOT_TOKEN")
    or os.getenv("TELEGRAM_TOKEN")
    or os.getenv("TOKEN")
    or ""
)
BOT_TOKEN = raw_token.strip().strip("\"'").strip()

COOKIES_PATH = os.getenv("INSTAGRAM_COOKIES_PATH", "cookies.txt")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

if not os.path.exists(COOKIES_PATH):
    COOKIES_PATH = None
