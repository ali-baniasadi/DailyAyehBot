"""
ربات پست روزانه آیه قرآن + ترجمه فارسی + تصویر تولیدشده با هوش مصنوعی
با استفاده از Cloudflare Workers AI (مدل FLUX.1 [schnell])

اجرای عادی:
    python main.py
اجرای تست:
    python main.py --once
"""
import argparse
import base64
import hashlib
import json
import os
from datetime import date, datetime

import requests
from apscheduler.schedulers.blocking import BlockingScheduler
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")

# --- Cloudflare Workers AI ---
CF_ACCOUNT_ID = os.getenv("CF_ACCOUNT_ID")
CF_API_TOKEN = os.getenv("CF_API_TOKEN")
# SDXL-Lightning پشتیبانی واقعی از negative_prompt دارد (بر خلاف flux-1-schnell)
CF_IMAGE_MODEL = os.getenv("CF_IMAGE_MODEL", "@cf/bytedance/stable-diffusion-xl-lightning")

NEGATIVE_PROMPT = (
    "text, writing, letters, words, calligraphy, script, arabic script, persian script, "
    "caption, subtitle, watermark, logo, signature, low quality, blurry, distorted, "
    "extra limbs, deformed, people, faces, humans, animals"
)

# --- عناصر تصویری برای ساخت تنوع بین آیات مختلف ---
_TIME_OF_DAY = [
    "a fiery golden sunrise", "a soft amber sunset", "a quiet moonlit night",
    "bright midday sky", "a deep blue hour just after dusk",
    "a misty early morning", "a clear starlit night sky",
]
_SETTINGS = [
    "towering mountain peaks", "vast desert dunes", "a calm ocean shoreline",
    "a lush green valley", "rolling hills beneath an open sky",
    "a still lake reflecting the sky", "an ancient stone canyon",
    "a quiet forest clearing", "terraced fields on a hillside",
]
_WEATHER = [
    "soft clouds drifting slowly", "light rain falling in the distance",
    "a clear open sky", "gentle mist rolling over the land",
    "a light breeze moving through tall grass", "still, calm air",
]
_PALETTE = [
    "warm gold and amber tones", "deep blue and violet tones",
    "soft pastel pink and lavender tones", "rich emerald and teal tones",
    "warm terracotta and burnt orange tones", "cool silver and white tones",
    "deep indigo and rose tones",
]
_STYLE = [
    "cinematic digital painting", "soft watercolor illustration",
    "minimalist flat illustration", "dreamlike surreal art",
    "detailed matte painting", "impressionistic brushwork painting",
]

POST_HOUR = int(os.getenv("POST_HOUR", "8"))
POST_MINUTE = int(os.getenv("POST_MINUTE", "0"))
TIMEZONE = os.getenv("TIMEZONE", "Asia/Tehran")

VERSES_FILE = "verses.json"
STATE_FILE = "state.json"
IMAGE_PATH = "generated_image.png"
TELEGRAM_CAPTION_LIMIT = 1024


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


def pick_next_verse(verses: list) -> dict:
    start_date = date(2026, 1, 1)  # تاریخ شروع چرخه
    today = date.today()
    days = (today - start_date).days
    return verses[days % len(verses)]


def _pick(options: list, verse_key: str, salt: str):
    """انتخاب قطعی (deterministic) یک آیتم از لیست بر اساس هش سوره+آیه،
    تا هر آیه همیشه همان ترکیب فضا/نور/رنگ را بگیرد ولی بین آیات مختلف باشد."""
    digest = hashlib.sha256(f"{verse_key}-{salt}".encode("utf-8")).hexdigest()
    return options[int(digest, 16) % len(options)]


def build_image_prompt(verse: dict) -> str:
    theme = verse.get("theme") or verse["translation_fa"][:100]
    verse_key = f"{verse.get('surah_name_ar', '')}:{verse.get('ayah', '')}"

    time_of_day = _pick(_TIME_OF_DAY, verse_key, "time")
    setting = _pick(_SETTINGS, verse_key, "setting")
    weather = _pick(_WEATHER, verse_key, "weather")
    palette = _pick(_PALETTE, verse_key, "palette")
    style = _pick(_STYLE, verse_key, "style")

    return (
        f"{style}, a symbolic and evocative artwork inspired by the concept of: {theme}. "
        f"The scene shows {setting} during {time_of_day}, with {weather}. "
        f"Color palette dominated by {palette}. "
        "Peaceful, spiritual, contemplative atmosphere, subtle abstract geometric patterns "
        "woven into the composition, elegant balanced composition, ultra detailed, high quality."
    )


def generate_image(prompt: str) -> str:
    if not CF_ACCOUNT_ID or not CF_API_TOKEN:
        raise RuntimeError("CF_ACCOUNT_ID یا CF_API_TOKEN تنظیم نشده است.")

    url = (
        f"https://api.cloudflare.com/client/v4/accounts/"
        f"{CF_ACCOUNT_ID}/ai/run/{CF_IMAGE_MODEL}"
    )
    response = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {CF_API_TOKEN}",
            "Content-Type": "application/json",
        },
        json={
            "prompt": prompt,
            "negative_prompt": NEGATIVE_PROMPT,
            "width": 1024,
            "height": 1024,
        },
        timeout=120,
    )

    if response.status_code != 200:
        # پاسخ خام سرور را لاگ می‌کنیم تا علت واقعی خطا مشخص شود
        raise RuntimeError(
            f"Cloudflare HTTP {response.status_code}: {response.text[:500]}"
        )

    try:
        data = response.json()
    except ValueError:
        raise RuntimeError(
            f"پاسخ Cloudflare قابل‌خواندن به‌صورت JSON نبود "
            f"(status={response.status_code}): {response.text[:500]!r}"
        )

    if not data.get("success", False):
        raise RuntimeError(f"خطای Cloudflare Workers AI: {data.get('errors')}")

    image_b64 = data["result"]["image"]
    with open(IMAGE_PATH, "wb") as f:
        f.write(base64.b64decode(image_b64))
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
        files = {"photo": photo}
        response = requests.post(url, data=data, files=files, timeout=120)
    response.raise_for_status()
    return response.json()


def send_text(text: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    response = requests.post(
        url,
        data={"chat_id": CHANNEL_ID, "text": text},
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

    log(f"ارسال شد: {verse['surah_name_ar']} - آیه {verse['ayah']}")


def run_scheduler():
    scheduler = BlockingScheduler(timezone=TIMEZONE)
    scheduler.add_job(post_daily_verse, "cron", hour=POST_HOUR, minute=POST_MINUTE)
    log(f"ربات فعال شد. ارسال روزانه ساعت {POST_HOUR:02d}:{POST_MINUTE:02d}")
    scheduler.start()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="اجرای یک‌باره برای تست")
    args = parser.parse_args()

    if not BOT_TOKEN:
        raise SystemExit("متغیر TELEGRAM_BOT_TOKEN تنظیم نشده است.")
    if not CHANNEL_ID:
        raise SystemExit("متغیر TELEGRAM_CHANNEL_ID تنظیم نشده است.")
    if not CF_ACCOUNT_ID:
        raise SystemExit("متغیر CF_ACCOUNT_ID تنظیم نشده است.")
    if not CF_API_TOKEN:
        raise SystemExit("متغیر CF_API_TOKEN تنظیم نشده است.")

    if args.once:
        post_daily_verse()
    else:
        run_scheduler()