"""
این اسکریپت را یک‌بار (و هر وقت خواستید لیست آیات را عوض/اضافه کنید) اجرا کنید.
کار آن: خواندن curated_refs.json (لیست سوره:آیه + موضوع) و گرفتن متن عربیِ
دقیق (رسم‌الخط عثمانی با اعراب) و یک ترجمه فارسی معتبر از API رایگان
alquran.cloud، سپس ذخیره‌ی نتیجه در verses.json برای استفاده‌ی main.py.

چرا از API استفاده می‌کنیم و متن را دستی وارد نمی‌کنیم؟
چون در متن قرآن حتی یک اشتباه تایپی قابل قبول نیست؛ گرفتن متن از منبع
رسمی و شناخته‌شده، ریسک خطای انسانی را از بین می‌برد.
"""

import json
import sys
import time
import requests

API_BASE = "https://api.alquran.cloud/v1"
ARABIC_EDITION = "quran-uthmani"  # رسم‌الخط عثمانی همراه با اعراب

REFS_FILE = "curated_refs.json"
OUTPUT_FILE = "verses.json"


def pick_persian_edition(preferred: str | None = None) -> str:
    """یک شناسه‌ی ترجمه فارسی معتبر را از فهرست ترجمه‌های API انتخاب می‌کند."""
    resp = requests.get(
        f"{API_BASE}/edition",
        params={"language": "fa", "format": "text", "type": "translation"},
        timeout=30,
    )
    resp.raise_for_status()
    editions = resp.json().get("data", [])
    if not editions:
        raise RuntimeError("هیچ ترجمه فارسی‌ای از API برگردانده نشد.")

    identifiers = [e["identifier"] for e in editions]

    if preferred and preferred in identifiers:
        return preferred

    # اولویت با ترجمه‌ی مکارم شیرازی، در غیر این صورت اولین مورد موجود
    for ident in identifiers:
        if "makarem" in ident.lower():
            return ident

    return identifiers[0]


def fetch_ayah(reference: str, edition: str) -> dict:
    resp = requests.get(f"{API_BASE}/ayah/{reference}/{edition}", timeout=30)
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("code") != 200:
        raise RuntimeError(f"خطا در دریافت {reference} ({edition}): {payload}")
    return payload["data"]


def main():
    with open(REFS_FILE, "r", encoding="utf-8") as f:
        refs = json.load(f)

    persian_edition = pick_persian_edition()
    print(f"ترجمه فارسی انتخاب‌شده: {persian_edition}")

    verses = []
    for ref in refs:
        reference = f"{ref['surah']}:{ref['ayah']}"
        try:
            arabic_data = fetch_ayah(reference, ARABIC_EDITION)
            time.sleep(0.3)  # ملایمت با سرور API
            fa_data = fetch_ayah(reference, persian_edition)
            time.sleep(0.3)

            verses.append({
                "surah": ref["surah"],
                "ayah": ref["ayah"],
                "surah_name_ar": arabic_data["surah"]["name"],
                "surah_name_en": arabic_data["surah"]["englishName"],
                "arabic": arabic_data["text"],
                "translation_fa": fa_data["text"],
                "translation_edition": persian_edition,
                "theme": ref.get("theme", ""),
            })
            print(f"✔ دریافت شد: {reference}")
        except Exception as e:
            print(f"✘ خطا در {reference}: {e}", file=sys.stderr)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(verses, f, ensure_ascii=False, indent=2)

    print(f"\n{len(verses)} آیه در {OUTPUT_FILE} ذخیره شد.")


if __name__ == "__main__":
    main()
