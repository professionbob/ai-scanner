import requests
from config import BOT_TOKEN, CHAT_ID


def send_telegram(msg):
    if not BOT_TOKEN or not CHAT_ID:
        raise RuntimeError("Telegram environment variables are not configured")

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    response = requests.post(
        url,
        data={"chat_id": CHAT_ID, "text": msg},
        timeout=10,
    )
    response.raise_for_status()
