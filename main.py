"""
ربات پست روزانه آیه قرآن + ترجمه فارسی + تصویر تولیدشده با هوش مصنوعی
با استفاده از Cloudflare Workers AI

اجرای عادی (اجرای پیوسته با زمان‌بند داخلی - برای سرور/VPS):
    python main.py
اجرای یک‌باره (برای GitHub Actions یا تست):
    python main.py --once
"""
import argparse
import base64
import hashlib
import json
import os
import random
import tempfile
from datetime import datetime
from zoneinfo import ZoneInfo

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

# قوانین ایمنی تصویری: هیچ‌گونه تصویر انسان/چهره (که ریسک ترسیم پیامبران و
# فرشتگان را هم از بین می‌برد)، هیچ نوشته/خوشنویسی، و هیچ صفحه‌ی جعلی قرآن.
NEGATIVE_PROMPT = (
    "text, writing, letters, words, typography, calligraphy, arabic calligraphy, "
    "script, arabic script, persian script, quran page, book page, fake scripture, "
    "caption, subtitle, watermark, logo, signature, "
    "god, allah, deity, prophet, messenger, angel, wings, halo, religious icon, "
    "religious symbol, shrine, "
    "people, person, human, human face, human figure, portrait, crowd, animals, "
    "low quality, blurry, distorted, extra limbs, deformed anatomy"
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

POST_HOUR = int(os.getenv("POST_HOUR", "10"))
POST_MINUTE = int(os.getenv("POST_MINUTE", "0"))
TIMEZONE = os.getenv("TIMEZONE", "Asia/Tehran")

VERSES_FILE = "verses.json"
STATE_FILE = "state.json"
IMAGE_PATH = "generated_image.jpg"
TELEGRAM_CAPTION_LIMIT = 1024

SIGNATURE = "🆔 @Daiily_Ayeh | کانال آیه روزانه"


def log(msg: str):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}")


def tehran_tz() -> ZoneInfo:
    return ZoneInfo(TIMEZONE)


def today_in_tehran() -> str:
    """تاریخ امروز به وقت تهران، به‌صورت YYYY-MM-DD (نه UTC و نه ساعت سیستم)."""
    return datetime.now(tehran_tz()).date().isoformat()


# ---------------------------------------------------------------------------
# آیات
# ---------------------------------------------------------------------------

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


def verse_key(verse: dict) -> str:
    """شناسه‌ی یکتای هر آیه: شماره سوره + شماره آیه (نه ترتیب/ایندکس در فایل)."""
    return f"{verse['surah']}:{verse['ayah']}"


class NoUnusedVersesError(Exception):
    """همه‌ی آیات موجود در curated_refs.json/verses.json قبلاً منتشر شده‌اند."""


def select_next_verse(verses: list, state: dict) -> dict:
    used = set(state.get("used_verses", []))
    unused = [v for v in verses if verse_key(v) not in used]
    # آیه‌ای که کپشنش از حد تلگرام بلندتر باشد باید ترجمه‌اش کوتاه شود؛ برای دقت
    # ترجمه، تا وقتی آیه‌ی کامل‌ِ قابل‌ارسال هست، از آن‌ها انتخاب می‌کنیم.
    fits = [v for v in unused if len(build_caption(v)) <= TELEGRAM_CAPTION_LIMIT]
    unused = fits or unused
    if not unused:
        raise NoUnusedVersesError(
            f"همه‌ی {len(verses)} آیه‌ی موجود قبلاً منتشر شده‌اند. "
            "برای ادامه، آیات بیشتری به curated_refs.json اضافه کرده و "
            "fetch_verses.py را دوباره اجرا کنید."
        )
    # از میان آیات استفاده‌نشده، یکی به‌صورت تصادفی انتخاب می‌شود (نه لزوماً
    # اولین مورد در فایل)، تا ترتیب پست‌ها هم غیرقابل‌پیش‌بینی و متنوع باشد.
    # با این حال، تضمین می‌شود که هیچ آیه‌ای تا وقتی همه‌ی آیات دیگر پست
    # نشده‌اند، دوباره تکرار نشود.
    return random.choice(unused)


# ---------------------------------------------------------------------------
# وضعیت پایدار (state.json) — ضد تکرار
# ---------------------------------------------------------------------------

def _default_state() -> dict:
    return {
        "used_verses": [],       # لیست "سوره:آیه" ی آیاتی که با موفقیت پست شده‌اند
        "last_post_date": None,  # آخرین تاریخ پست موفق، به وقت تهران (YYYY-MM-DD)
        "last_post_status": None,
    }


def load_state() -> dict:
    if not os.path.exists(STATE_FILE):
        log(f"{STATE_FILE} پیدا نشد؛ وضعیت اولیه (خالی) ساخته می‌شود.")
        return _default_state()

    with open(STATE_FILE, "r", encoding="utf-8") as f:
        try:
            raw = json.load(f)
        except json.JSONDecodeError as e:
            # به‌جای بازنویسی بی‌سروصدای فایل خراب، خطا را با صدای بلند اعلام می‌کنیم
            # تا داده‌ی قبلی به‌اشتباه از بین نرود.
            raise RuntimeError(
                f"{STATE_FILE} خراب/غیرقابل‌خواندن است ({e}). "
                "لطفاً دستی بررسی کنید تا سابقه‌ی آیات منتشرشده از دست نرود."
            )

    # مهاجرت از فرمت قدیمی: نسخه‌ی قبلی main.py فقط یک شمارنده‌ی
    # استفاده‌نشده به نام last_index داشت و اصلاً آیات منتشرشده را ثبت
    # نمی‌کرد (همین، ریشه‌ی اصلی باگ تکرار آیات بود). آن شمارنده را برای
    # مرجع نگه می‌داریم ولی به سیستم جدید ردیابی صریح آیات متکی می‌شویم.
    if "used_verses" not in raw:
        log(
            "⚠️ فرمت قدیمی state.json شناسایی شد (بدون ردیابی آیات منتشرشده). "
            "چون نسخه‌ی قبلی کد اصلاً آیات پست‌شده را ثبت نمی‌کرد، امکان "
            "بازسازی خودکار تاریخچه‌ی واقعی کانال وجود ندارد. اگر می‌خواهید "
            "آیاتی که قبلاً به‌صورت دستی می‌دانید پست شده‌اند دوباره تکرار "
            "نشوند، شناسه‌ی آن‌ها را (به شکل \"سوره:آیه\") به لیست "
            "used_verses در state.json اضافه کنید."
        )
        raw["_legacy_last_index"] = raw.get("last_index")
        raw["used_verses"] = []

    raw.setdefault("last_post_date", None)
    raw.setdefault("last_post_status", None)
    return raw


def save_state(state: dict) -> None:
    """نوشتن اتمیک: ابتدا در یک فایل موقت نوشته و سپس با os.replace جایگزین
    می‌شود، تا در صورت کرش/قطعی برق وسط نوشتن، state.json هرگز نیمه‌نوشته/
    خراب نشود."""
    directory = os.path.dirname(os.path.abspath(STATE_FILE)) or "."
    fd, tmp_path = tempfile.mkstemp(prefix=".state-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, STATE_FILE)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


# ---------------------------------------------------------------------------
# تولید تصویر
# ---------------------------------------------------------------------------

def _pick(options: list, key: str, salt: str):
    """انتخاب قطعی (deterministic) یک آیتم از لیست بر اساس هش سوره+آیه،
    تا هر آیه همیشه همان ترکیب فضا/نور/رنگ را بگیرد ولی بین آیات مختلف باشد."""
    digest = hashlib.sha256(f"{key}-{salt}".encode("utf-8")).hexdigest()
    return options[int(digest, 16) % len(options)]


def build_image_prompt(verse: dict) -> str:
    """پرامپت تصویر را از روی معنای واقعی آیه (image_theme/keywords/theme)
    می‌سازد، نه یک جمله‌ی عمومی و بی‌ربط."""
    image_theme = (
        verse.get("image_theme")
        or verse.get("theme")
        or verse.get("translation_fa", "")[:100]
    )
    keywords = verse.get("keywords") or []
    keyword_clause = f" Visual motifs to evoke: {', '.join(keywords)}." if keywords else ""

    key = verse_key(verse)
    time_of_day = _pick(_TIME_OF_DAY, key, "time")
    setting = _pick(_SETTINGS, key, "setting")
    weather = _pick(_WEATHER, key, "weather")
    palette = _pick(_PALETTE, key, "palette")
    style = _pick(_STYLE, key, "style")

    return (
        f"{style}, an editorial cinematic conceptual artwork that visually interprets "
        f"the concept of: {image_theme}.{keyword_clause} "
        f"The scene shows {setting} during {time_of_day}, with {weather}. "
        f"Color palette dominated by {palette}. "
        "Peaceful, premium, contemplative, symbolic composition — a visual metaphor, "
        "not a literal illustration of any religious story or figure. "
        "No depiction of God, prophets, angels, or any sacred figures. "
        "No text, no typography, no Arabic or Persian writing, no watermark, no logo, "
        "no random religious symbols. Elegant balanced composition, natural realistic "
        "lighting, shot like a high-end editorial photograph, ultra detailed, high quality."
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

    content_type = response.headers.get("content-type", "")

    if content_type.startswith("image/"):
        # برخی مدل‌ها (مثل stable-diffusion-xl-lightning) خود بایت‌های
        # تصویر را مستقیم برمی‌گردانند، نه JSON.
        with open(IMAGE_PATH, "wb") as f:
            f.write(response.content)
        return IMAGE_PATH

    try:
        data = response.json()
    except ValueError:
        raise RuntimeError(
            f"پاسخ Cloudflare قابل‌خواندن به‌صورت JSON نبود "
            f"(status={response.status_code}, content-type={content_type}): "
            f"{response.text[:200]!r}"
        )

    if not data.get("success", False):
        raise RuntimeError(f"خطای Cloudflare Workers AI: {data.get('errors')}")

    # برخی مدل‌ها (مثل flux-1-schnell) تصویر را به‌صورت base64 داخل JSON می‌دهند
    image_b64 = data["result"]["image"]
    with open(IMAGE_PATH, "wb") as f:
        f.write(base64.b64decode(image_b64))
    return IMAGE_PATH


# ---------------------------------------------------------------------------
# ارسال به تلگرام
# ---------------------------------------------------------------------------

def build_caption(verse: dict) -> str:
    header = f"📖 {verse['surah_name_ar']} — آیه {verse['ayah']}"
    body = (
        f"{verse['arabic']}\n\n"
        f"🔸 ترجمه:\n"
        f"{verse['translation_fa']}"
    )
    return f"{header}\n\n{body}\n\n{SIGNATURE}"


def truncate_caption(caption: str, limit: int = TELEGRAM_CAPTION_LIMIT) -> str:
    """اگر کپشن از محدودیت تلگرام بلندتر بود، بخش ترجمه را کوتاه می‌کنیم اما
    امضای کانال (SIGNATURE) را همیشه کامل و دست‌نخورده در انتها نگه می‌داریم."""
    if len(caption) <= limit:
        return caption
    if SIGNATURE not in caption:
        return caption[:limit]

    head, _, _ = caption.partition(SIGNATURE)
    ellipsis = "…\n\n"
    reserved = len(SIGNATURE) + len(ellipsis)
    available = max(limit - reserved, 0)
    return head[:available].rstrip() + ellipsis + SIGNATURE


def send_photo(image_path: str, caption: str) -> dict:
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    with open(image_path, "rb") as photo:
        data = {
            "chat_id": CHANNEL_ID,
            "caption": truncate_caption(caption),
        }
        files = {"photo": photo}
        response = requests.post(url, data=data, files=files, timeout=120)
    response.raise_for_status()
    return response.json()


def send_text(text: str) -> dict:
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    response = requests.post(
        url,
        data={"chat_id": CHANNEL_ID, "text": text},
        timeout=60,
    )
    response.raise_for_status()
    return response.json()


# ---------------------------------------------------------------------------
# جریان اصلی پست روزانه
# ---------------------------------------------------------------------------

def post_daily_verse():
    """
    START
     -> بارگذاری state
     -> تعیین تاریخ امروز (Asia/Tehran)
     -> اگر امروز قبلاً پست شده -> خروج
     -> انتخاب یک آیه‌ی استفاده‌نشده
     -> تولید تصویر (اختیاری؛ شکست آن مانع پست متن نمی‌شود)
     -> ارسال به تلگرام
     -> فقط در صورت تایید موفقیت از سمت تلگرام -> ثبت آیه به‌عنوان استفاده‌شده
        + ثبت تاریخ امروز به‌عنوان last_post_date
     END
    """
    state = load_state()
    today = today_in_tehran()

    if state.get("last_post_date") == today:
        log(f"امروز ({today}) قبلاً با موفقیت پست شده. برای جلوگیری از تکرار، خروج بدون ارسال.")
        return

    verses = load_verses()

    try:
        verse = select_next_verse(verses, state)
    except NoUnusedVersesError as e:
        log(f"❌ {e}")
        raise SystemExit(1)

    caption = build_caption(verse)

    image_path = None
    telegram_ok = False
    try:
        prompt = build_image_prompt(verse)
        log("در حال تولید تصویر...")
        image_path = generate_image(prompt)
        log("در حال ارسال پست (متن + تصویر) به تلگرام...")
        result = send_photo(image_path, caption)
        telegram_ok = bool(result.get("ok"))
    except Exception as e:
        log(f"خطا در مسیر تصویر/ارسال عکس: {e}")
        log("ارسال نسخه‌ی متنی (بدون تصویر) به‌جای آن...")
        try:
            result = send_text(caption)
            telegram_ok = bool(result.get("ok"))
        except Exception as e2:
            log(f"❌ ارسال نسخه‌ی متنی هم ناموفق بود: {e2}")
            telegram_ok = False
    finally:
        if image_path and os.path.exists(image_path):
            os.remove(image_path)

    if not telegram_ok:
        log(
            "❌ ارسال به تلگرام تایید نشد؛ این آیه به‌عنوان «منتشرشده» ثبت "
            "نمی‌شود تا در اجرای بعدی دوباره تلاش شود (و پست تکراری هم رخ ندهد)."
        )
        raise SystemExit(1)

    # فقط بعد از تایید قطعیِ ارسال موفق، وضعیت را ثبت می‌کنیم
    state.setdefault("used_verses", []).append(verse_key(verse))
    state["last_post_date"] = today
    state["last_post_status"] = "success"
    save_state(state)

    log(f"✅ منتشر شد: {verse['surah_name_ar']} - آیه {verse['ayah']}")


def run_scheduler():
    """حالت اجرای پیوسته (برای سرور/VPS، نه GitHub Actions).
    از cron واقعیِ APScheduler روی منطقه‌ی زمانی Asia/Tehran استفاده می‌شود
    (نه sleep(24h))، بنابراین هیچ drift زمانی رخ نمی‌دهد. علاوه بر آن، همان
    محافظ «یک پست در روز» داخل post_daily_verse هم برقرار است."""
    scheduler = BlockingScheduler(timezone=TIMEZONE)
    scheduler.add_job(post_daily_verse, "cron", hour=POST_HOUR, minute=POST_MINUTE)
    log(f"ربات فعال شد. ارسال روزانه ساعت {POST_HOUR:02d}:{POST_MINUTE:02d} به وقت {TIMEZONE}")
    scheduler.start()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="اجرای یک‌باره برای تست/GitHub Actions")
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
