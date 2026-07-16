import inspect

print(inspect.getsource(post_daily_verse))

"""
ربات پست روزانه آیه قرآن + ترجمه فارسی + تصویر تولیدشده با هوش مصنوعی
با استفاده از Hugging Face FLUX.1-schnell

اجرای عادی:
    python main.py

اجرای تست:
    python main.py --once
"""

import argparse
import json
import os
from datetime import datetime

import requests
from apscheduler.schedulers.blocking import BlockingScheduler
from dotenv import load_dotenv
from huggingface_hub import InferenceClient

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")
HF_TOKEN = os.getenv("HF_TOKEN")

POST_HOUR = int(os.getenv("POST_HOUR", "8"))
POST_MINUTE = int(os.getenv("POST_MINUTE", "0"))
TIMEZONE = os.getenv("TIMEZONE", "Asia/Tehran")

VERSES_FILE = "verses.json"
STATE_FILE = "state.json"
IMAGE_PATH = "generated_image.png"

TELEGRAM_CAPTION_LIMIT = 1024

client = (
    InferenceClient(api_key=HF_TOKEN)
    if HF_TOKEN
    else None
)


def log(msg: str):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}")


def load_verses() -> list:
    if not os.path.exists(VERSES_FILE):
        raise FileNotFoundError(
            f"{VERSES_FILE} پیدا نشد. ابتدا fetch_verses.py را اجرا کنید."
        )

    with open(VERSES_FILE, "r", encoding="utf-8") as f:
        verses = json.load(f)

    if not verses:
        raise ValueError(f"{VERSES_FILE} خالی است.")

    return verses


from datetime import date

def pick_next_verse(verses: list) -> dict:
    start_date = date(2026, 1, 1)   # تاریخ شروع چرخه
    today = date.today()

    days = (today - start_date).days

    return verses[days % len(verses)]
def build_image_prompt(verse: dict) -> str:
    theme = verse.get("theme") or verse["translation_fa"][:100]

    return (
        f"A peaceful symbolic illustration inspired by the Quranic concept of: {theme}. "
        "Beautiful sunrise, mountains, rivers, soft clouds, divine light, "
        "subtle Islamic geometric patterns, elegant composition, "
        "warm cinematic colors, ultra detailed digital painting, "
        "no people, no faces, no animals, "
        "no Arabic text, no Persian text, no calligraphy, no writing."
    )


def generate_image(prompt: str) -> str:
    if client is None:
        raise RuntimeError("HF_TOKEN تنظیم نشده است.")

    image = client.text_to_image(
        prompt=prompt,
        model="black-forest-labs/FLUX.1-dev",
    )

    image.save(IMAGE_PATH)

    return IMAGE_PATH


def build_caption(verse: dict) -> str:
    header = f"📖 {verse['surah_name_ar']} — آیه {verse['ayah']}"

    body = (
        f"{verse['arabic']}\n\n"
        f"🔸 ترجمه:\n"
        f"{verse['translation_fa']}"
    )

    return f"{header}\n\n{body}"

def send_photo(image_path: str, caption: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"

    with open(image_path, "rb") as photo:
        data = {
            "chat_id": CHANNEL_ID,
            "caption": caption[:TELEGRAM_CAPTION_LIMIT],
        }

        files = {
            "photo": photo
        }

        response = requests.post(
            url,
            data=data,
            files=files,
            timeout=120,
        )

    response.raise_for_status()

    return response.json()


def send_text(text: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    response = requests.post(
        url,
        data={
            "chat_id": CHANNEL_ID,
            "text": text,
        },
        timeout=60,
    )

    response.raise_for_status()

    return response.json()


def post_daily_verse():
    verses = load_verses()
    verse = pick_next_verse(verses)

    caption = build_caption(verse)

    try:
        prompt = build_image_prompt(verse)

        log("در حال تولید تصویر...")

        image_path = generate_image(prompt)

        log("در حال ارسال به تلگرام...")

        send_photo(image_path, caption)

        if os.path.exists(image_path):
            os.remove(image_path)

    except Exception as e:

        log(f"خطا در تولید تصویر: {e}")

        log("ارسال فقط متن آیه...")

        send_text(caption)


    log(
        f"ارسال شد: {verse['surah_name_ar']} - آیه {verse['ayah']}"
    )


def run_scheduler():
    scheduler = BlockingScheduler(
        timezone=TIMEZONE
    )

    scheduler.add_job(
        post_daily_verse,
        "cron",
        hour=POST_HOUR,
        minute=POST_MINUTE,
    )

    log(
        f"ربات فعال شد. ارسال روزانه ساعت "
        f"{POST_HOUR:02d}:{POST_MINUTE:02d}"
    )

    scheduler.start()

if __name__ == "__main__":

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--once",
        action="store_true",
        help="اجرای یک‌باره برای تست"
    )

    args = parser.parse_args()

    if not BOT_TOKEN:
        raise SystemExit(
            "متغیر TELEGRAM_BOT_TOKEN تنظیم نشده است."
        )

    if not CHANNEL_ID:
        raise SystemExit(
            "متغیر TELEGRAM_CHANNEL_ID تنظیم نشده است."
        )

    if not HF_TOKEN:
        raise SystemExit(
            "متغیر HF_TOKEN تنظیم نشده است."
        )

    if args.once:
        post_daily_verse()
    else:
        run_scheduler()    