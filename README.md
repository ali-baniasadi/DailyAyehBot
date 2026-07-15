# ربات پست روزانه آیه قرآن در کانال تلگرام

هر روز سر ساعت مشخص، یک آیه (به‌ترتیب و بدون تکرار از لیست دستچین‌شده‌ی شما)
به همراه ترجمه فارسی و یک تصویر تولیدشده با هوش مصنوعی که با معنای آیه مرتبط
است، در کانال تلگرام شما پست می‌شود.

## ساختار پروژه

```
quran-daily-bot/
├── curated_refs.json   # لیست آیات انتخابی شما (سوره:آیه) + یک موضوع کوتاه فارسی
├── fetch_verses.py      # یک‌بار اجرا می‌شود: متن عربی + ترجمه فارسی را از API می‌گیرد
├── main.py              # ربات اصلی: زمان‌بندی، تولید تصویر، ارسال به تلگرام
├── requirements.txt
├── .env.example         # نمونه تنظیمات؛ کپی کنید به .env و مقادیر را پر کنید
└── verses.json          # (بعد از اجرای fetch_verses.py ساخته می‌شود)
```

## مراحل راه‌اندازی

### ۱) ساخت ربات تلگرام
۱. در تلگرام به [@BotFather](https://t.me/BotFather) پیام دهید و با دستور `/newbot` یک ربات بسازید. توکن را نگه دارید.
۲. ربات را به‌عنوان **ادمین** به کانالتان اضافه کنید (باید دسترسی ارسال پست داشته باشد).
۳. اگر کانال خصوصی است، آیدی عددی کانال را با فوروارد یک پیام از کانال به
   [@userinfobot](https://t.me/userinfobot) پیدا کنید (چیزی شبیه `-1001234567890`).
   اگر کانال پابلیک است، کافی است از یوزرنیم آن استفاده کنید، مثلاً `@my_channel`.

### ۲) نصب پیش‌نیازها
نیاز به Python 3.10 یا بالاتر دارید.

```bash
cd quran-daily-bot
python -m venv venv
source venv/bin/activate      # ویندوز: venv\Scripts\activate
pip install -r requirements.txt
```

### ۳) تنظیم متغیرهای محیطی
فایل `.env.example` را کپی کرده و مقداردهی کنید:

```bash
cp .env.example .env
```

و مقادیر زیر را در `.env` وارد کنید:
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHANNEL_ID`
- `OPENAI_API_KEY` (برای تولید تصویر — از [platform.openai.com](https://platform.openai.com) بگیرید)
- ساعت و دقیقه‌ی پست روزانه (`POST_HOUR`, `POST_MINUTE`) و منطقه زمانی (`TIMEZONE`)

### ۴) دریافت آیات از API
آیات لیست‌شده در `curated_refs.json` را می‌توانید دلخواه ویرایش/اضافه کنید
(هر آیتم شامل شماره سوره، شماره آیه و یک «موضوع» کوتاه فارسی برای هدایت
تولید تصویر است). سپس یک‌بار این را اجرا کنید:

```bash
python fetch_verses.py
```

این اسکریپت متن دقیق عربی (رسم‌الخط عثمانی) و یک ترجمه فارسی معتبر را از
API رایگان [alquran.cloud](https://alquran.cloud/api) می‌گیرد و در
`verses.json` ذخیره می‌کند. عمداً این کار به یک API سپرده شده تا خطای
تایپی در متن مقدس رخ ندهد.

> اگر ترجمه فارسیِ خاصی (مثلاً فولادوند یا انصاریان) مدنظرتان است، شناسه
> آن ترجمه را در `PREFERRED_FA_EDITION` داخل `.env` بگذارید (لیست شناسه‌ها
> از `https://api.alquran.cloud/v1/edition?language=fa` قابل مشاهده است).

### ۵) تست فوری
```bash
python main.py --once
```
این دستور بلافاصله یک پست آزمایشی (بدون منتظر ماندن تا ساعت مشخص‌شده) ارسال می‌کند.

### ۶) اجرای دائمی با زمان‌بندی روزانه
```bash
python main.py
```
این دستور در پس‌زمینه می‌ماند و هر روز سر ساعت تنظیم‌شده یک پست جدید ارسال می‌کند.

برای اجرای همیشگی روی سرور، پیشنهاد می‌شود به‌جای اجرای دستی، یک سرویس
systemd بسازید تا در صورت ری‌استارت سرور هم خودکار بالا بیاید:

```ini
# /etc/systemd/system/quran-bot.service
[Unit]
Description=Quran Daily Telegram Bot
After=network.target

[Service]
WorkingDirectory=/path/to/quran-daily-bot
ExecStart=/path/to/quran-daily-bot/venv/bin/python main.py
Restart=always
EnvironmentFile=/path/to/quran-daily-bot/.env

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now quran-bot
```

## نکات مهم

- **ترتیب پست‌ها**: آیات به‌ترتیب لیست `verses.json` و بدون تکرار پست می‌شوند
  (وضعیت آخرین آیه‌ی ارسالی در `state.json` نگه داشته می‌شود). وقتی لیست تمام
  شود، دوباره از اول شروع می‌شود.
- **تصویر**: پرامپت تصویر بر اساس «موضوع» هر آیه ساخته می‌شود، نه ترجمه‌ی
  لفظی؛ و عمداً بدون چهره‌ی انسان یا نوشتار طراحی شده (چون هوش مصنوعی معمولاً
  نوشتار عربی/فارسی را درست تولید نمی‌کند و برای پرهیز از تصویرسازی نامناسب
  با محتوای دینی).
- **هزینه**: تولید هر تصویر با API مدل `gpt-image-1` هزینه دارد؛ قیمت فعلی
  را در [مستندات OpenAI](https://platform.openai.com/docs/pricing) ببینید.
  اگر می‌خواهید هزینه را حذف کنید، می‌توانید بخش `generate_image` را با یک
  API رایگان/متن‌باز جایگزین کنید (مثلاً Stable Diffusion لوکال).
- **گسترش لیست آیات**: هر وقت خواستید، آیه‌های بیشتری به `curated_refs.json`
  اضافه کنید و دوباره `fetch_verses.py` را اجرا کنید.
