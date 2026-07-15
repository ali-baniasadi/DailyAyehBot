"""
ربات پست روزانه آیه قرآن + ترجمه فارسی + تصویر تولیدشده با هوش مصنوعی
در یک کانال تلگرام.

اجرای عادی (با زمان‌بندی روزانه):
    python main.py

اجرای فوری برای تست (بدون منتظر ماندن تا ساعت مشخص‌شده):
    python main.py --once
"""

import argparse
import base64
import json
import os
from datetime import datetime

import requests
from dotenv import load_dotenv
from openai import OpenAI
from apscheduler.schedulers.blocking import BlockingScheduler

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
POST_HOUR = int(os.getenv("POST_HOUR", "8"))
POST_MINUTE = int(os.getenv("POST_MINUTE", "0"))
TIMEZONE = os.getenv("TIMEZONE", "Asia/Tehran")

VERSES_FILE = "verses.json"
STATE_FILE = "state.json"
IMAGE_PATH = "generated_image.png"

TELEGRAM_CAPTION_LIMIT = 1024

client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None


def log(msg: str):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}")


def load_verses() -> list:
    if not os.path.exists(VERSES_FILE):
        raise FileNotFoundError(
            f"{VERSES_FILE} پیدا نشد. ابتدا `python fetch_verses.py` را اجرا کنید."
        )
    with open(VERSES_FILE, "r", encoding="utf-8") as f:
        verses = json.load(f)
    if not verses:
        raise ValueError(f"{VERSES_FILE} خالی است.")
    return verses


def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"last_index": -1}


def save_state(state: dict):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def pick_next_verse(verses: list, state: dict) -> dict:
    """به‌صورت چرخشی و بدون تکرار، آیه بعدی را انتخاب می‌کند."""
    total = len(verses)
    idx = (state["last_index"] + 1) % total
    state["last_index"] = idx
    save_state(state)
    return verses[idx]


def build_image_prompt(verse: dict) -> str:
    """
    پرامپت تصویر را بر اساس «موضوع» آیه می‌سازد، نه ترجمه لفظی.
    عمداً از تصویرسازی چهره انسان، موجودات مقدس یا نوشتار عربی/فارسی
    خودداری می‌کنیم چون:
      1) هوش مصنوعی معمولاً نوشتار را درست تولید نمی‌کند.
      2) در بسیاری از سنت‌های هنر اسلامی از تصویرسازی چهره‌ها
         و شخصیت‌های مقدس پرهیز می‌شود؛ اینجا هم تصویر انتزاعی/طبیعی
         و بدون شخصیت‌محور نگه داشته شده است.
    """
    theme = verse.get("theme") or verse["translation_fa"][:100]
    return (
        f"A serene, symbolic, abstract illustration representing the concept of: {theme}. "
        "Style: soft natural light, calm and warm color palette, elements of nature "
        "(sky, mountains, water, light rays, gentle geometric islamic patterns), "
        "no human figures, no faces, no text or writing of any kind, "
        "peaceful and contemplative atmosphere, high quality digital painting."
    )


def generate_image(prompt: str) -> str:
    if client is None:
        raise RuntimeError("OPENAI_API_KEY تنظیم نشده است.")
    result = client.images.generate(
        model="gpt-image-1",
        prompt=prompt,
        size="1024x1024",
    )
    b64_data = result.data[0].b64_json
    image_bytes = base64.b64decode(b64_data)
    with open(IMAGE_PATH, "wb") as f:
        f.write(image_bytes)
    return IMAGE_PATH


def build_caption(verse: dict) -> str:
    header = f"📖 {verse['surah_name_ar']} — آیه {verse['ayah']}"
    body = f"{verse['arabic']}\n\n🔸 ترجمه:\n{verse['translation_fa']}"
    return f"{header}\n\n{body}"


def send_photo(image_path: str, caption: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    with open(image_path, "rb") as photo:
        data = {"chat_id": CHANNEL_ID, "caption": caption[:TELEGRAM_CAPTION_LIMIT]}
        files = {"photo": photo}
        resp = requests.post(url, data=data, files=files, timeout=60)
    resp.raise_for_status()
    return resp.json()


def send_text(text: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    resp = requests.post(
        url, data={"chat_id": CHANNEL_ID, "text": text}, timeout=30
    )
    resp.raise_for_status()
    return resp.json()


def post_daily_verse():
    try:
        verses = load_verses()
        state = load_state()
        verse = pick_next_verse(verses, state)

        prompt = build_image_prompt(verse)
        image_path = generate_image(prompt)

        caption = build_caption(verse)
        send_photo(image_path, caption)

        # اگر متن از سقف کپشن تلگرام (1024 کاراکتر) بلندتر بود،
        # بخش اضافه را به‌صورت پیام متنی جداگانه ارسال می‌کنیم
        # تا هیچ بخشی از ترجمه/متن آیه ناقص نماند.
        if len(caption) > TELEGRAM_CAPTION_LIMIT:
            send_text(caption)

        log(f"پست ارسال شد: {verse['surah_name_ar']} آیه {verse['ayah']}")
    except Exception as e:
        log(f"خطا در ارسال پست روزانه: {e}")


def run_scheduler():
    scheduler = BlockingScheduler(timezone=TIMEZONE)
    scheduler.add_job(post_daily_verse, "cron", hour=POST_HOUR, minute=POST_MINUTE)
    log(f"ربات فعال شد. پست روزانه ساعت {POST_HOUR:02d}:{POST_MINUTE:02d} ({TIMEZONE}) ارسال می‌شود.")
    scheduler.start()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()

    if not BOT_TOKEN or not CHANNEL_ID:
        raise SystemExit(
            "TELEGRAM_BOT_TOKEN و TELEGRAM_CHANNEL_ID باید تنظیم شوند."
        )

    if args.once:
        post_daily_verse()
    else:
        run_scheduler()
