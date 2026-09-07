import os

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL", "300"))
MAX_SCAN_PER_ROUND = int(os.getenv("MAX_SCAN_PER_ROUND", "250"))

MIN_PRICE = 5
MIN_AVG_VOLUME = 500000
