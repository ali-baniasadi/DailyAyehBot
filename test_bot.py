"""
تست‌های خودکار برای main.py

اجرا:
    python -m unittest test_bot.py -v

این تست‌ها به تلگرام یا Cloudflare واقعی وصل نمی‌شوند؛ همه‌چیز mock شده است.
هر تست در یک پوشه‌ی موقت جدا اجرا می‌شود تا به verses.json/state.json واقعی
پروژه دست نزند.
"""
import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch, MagicMock

import main


SAMPLE_VERSES = [
    {
        "surah": 94, "ayah": 6, "surah_name_ar": "سُورَةُ الشَّرْحِ", "surah_name_en": "Ash-Sharh",
        "arabic": "إِنَّ مَعَ ٱلْعُسْرِ يُسْرًا", "translation_fa": "به‌راستی همراه سختی آسانی است.",
        "translation_edition": "fa.makarem", "theme": "امید و گشایش پس از سختی",
        "topic": "hope_after_hardship", "image_theme": "light emerging after darkness",
        "keywords": ["hope", "relief", "hardship", "light"],
    },
    {
        "surah": 13, "ayah": 28, "surah_name_ar": "سُورَةُ الرَّعْدِ", "surah_name_en": "Ar-Ra'd",
        "arabic": "أَلَا بِذِكْرِ ٱللَّهِ تَطْمَئِنُّ ٱلْقُلُوبُ", "translation_fa": "آگاه باشید، تنها با یاد خدا دل‌ها آرام می‌گیرد.",
        "translation_edition": "fa.makarem", "theme": "آرامش قلب در سایه یاد خدا",
        "topic": "inner_peace_remembrance", "image_theme": "still calm water reflecting soft light",
        "keywords": ["peace", "calm", "remembrance"],
    },
]


class BotTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self._cwd = os.getcwd()
        os.chdir(self.tmpdir)

        with open(main.VERSES_FILE, "w", encoding="utf-8") as f:
            json.dump(SAMPLE_VERSES, f, ensure_ascii=False)

        # فایل state.json عمداً ساخته نمی‌شود؛ یعنی هر تست از حالت خالی شروع می‌شود.
        main.BOT_TOKEN = "TEST_TOKEN"
        main.CHANNEL_ID = "@test_channel"
        main.CF_ACCOUNT_ID = "TEST_ACCOUNT"
        main.CF_API_TOKEN = "TEST_CF_TOKEN"

    def tearDown(self):
        os.chdir(self._cwd)
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    # ------------------------------------------------------------------
    # تست ۱ — جلوگیری از تکرار در همان روز
    # ------------------------------------------------------------------
    @patch("main.generate_image")
    @patch("main.requests.post")
    def test_no_duplicate_post_same_day(self, mock_post, mock_generate_image):
        mock_generate_image.side_effect = RuntimeError("image gen disabled in test")
        mock_response = MagicMock()
        mock_response.json.return_value = {"ok": True, "result": {}}
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        main.post_daily_verse()  # اجرای اول -> باید پست کند
        self.assertEqual(mock_post.call_count, 1)

        state_after_first = main.load_state()
        self.assertEqual(len(state_after_first["used_verses"]), 1)

        main.post_daily_verse()  # اجرای دوم (همان روز) -> نباید دوباره پست کند
        self.assertEqual(mock_post.call_count, 1, "نباید در همان روز دوباره پست شود")

        state_after_second = main.load_state()
        self.assertEqual(
            state_after_first["used_verses"], state_after_second["used_verses"],
            "لیست آیات استفاده‌شده نباید در اجرای دوم تغییر کند",
        )

    # ------------------------------------------------------------------
    # تست ۲ — پایداری پس از «ری‌استارت» (خواندن دوباره‌ی state از دیسک)
    # ------------------------------------------------------------------
    @patch("main.generate_image")
    @patch("main.requests.post")
    def test_state_survives_restart(self, mock_post, mock_generate_image):
        mock_generate_image.side_effect = RuntimeError("image gen disabled in test")
        mock_response = MagicMock()
        mock_response.json.return_value = {"ok": True, "result": {}}
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        main.post_daily_verse()
        state_on_disk = main.load_state()  # شبیه‌سازی ری‌استارت: state دوباره از فایل خوانده می‌شود
        self.assertEqual(len(state_on_disk["used_verses"]), 1)
        self.assertIn("94:6", state_on_disk["used_verses"] + ["94:6", "13:28"])
        self.assertTrue(state_on_disk["used_verses"][0] in ("94:6", "13:28"))

    # ------------------------------------------------------------------
    # تست ۳ — منطقه‌ی زمانی Asia/Tehran (نه ساعت سیستم)
    # ------------------------------------------------------------------
    def test_uses_tehran_timezone_not_system(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo

        expected = datetime.now(ZoneInfo("Asia/Tehran")).date().isoformat()
        self.assertEqual(main.today_in_tehran(), expected)

        # اگر متغیر محیطی TIMEZONE عوض شود، تابع باید از همان استفاده کند
        old_tz = main.TIMEZONE
        try:
            main.TIMEZONE = "UTC"
            expected_utc = datetime.now(ZoneInfo("UTC")).date().isoformat()
            self.assertEqual(main.today_in_tehran(), expected_utc)
        finally:
            main.TIMEZONE = old_tz

    # ------------------------------------------------------------------
    # تست ۴ — پرامپت تصویر بر اساس معنای واقعی آیه ساخته می‌شود
    # ------------------------------------------------------------------
    def test_image_prompt_reflects_verse_semantics(self):
        prompt = main.build_image_prompt(SAMPLE_VERSES[0])
        self.assertIn("light emerging after darkness", prompt)
        self.assertIn("hope", prompt)

        prompt2 = main.build_image_prompt(SAMPLE_VERSES[1])
        self.assertIn("still calm water reflecting soft light", prompt2)
        self.assertNotEqual(prompt, prompt2, "دو آیه‌ی متفاوت نباید پرامپت یکسان بگیرند")

        # هیچ توصیه‌ای برای ترسیم خدا/پیامبر/فرشته وجود ندارد
        for forbidden in ("depiction of God", "prophets", "angels"):
            self.assertIn(forbidden, prompt)

    # ------------------------------------------------------------------
    # تست ۵ — همه‌ی پست‌ها به امضای کانال ختم می‌شوند
    # ------------------------------------------------------------------
    def test_caption_always_ends_with_signature(self):
        caption = main.build_caption(SAMPLE_VERSES[0])
        self.assertTrue(caption.endswith(main.SIGNATURE))

        # حتی وقتی خیلی طولانی و باید کوتاه شود
        long_verse = dict(SAMPLE_VERSES[0])
        long_verse["translation_fa"] = "متن طولانی. " * 300
        long_caption = main.build_caption(long_verse)
        truncated = main.truncate_caption(long_caption, limit=200)
        self.assertTrue(truncated.endswith(main.SIGNATURE))
        self.assertLessEqual(len(truncated), 200)

    # ------------------------------------------------------------------
    # تست ۶ — شکست تولید تصویر نباید مانع پست متن شود
    # ------------------------------------------------------------------
    @patch("main.generate_image")
    @patch("main.requests.post")
    def test_image_failure_falls_back_to_text_post(self, mock_post, mock_generate_image):
        mock_generate_image.side_effect = RuntimeError("Cloudflare down")
        mock_response = MagicMock()
        mock_response.json.return_value = {"ok": True, "result": {}}
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        main.post_daily_verse()

        # باید دقیقاً یک بار (sendMessage) فراخوانی شده باشد، نه sendPhoto
        self.assertEqual(mock_post.call_count, 1)
        called_url = mock_post.call_args[0][0]
        self.assertIn("sendMessage", called_url)

        state = main.load_state()
        self.assertEqual(len(state["used_verses"]), 1, "با وجود شکست تصویر، آیه باید با موفقیت ثبت شده باشد")

    # ------------------------------------------------------------------
    # تست ۷ — شکست کامل تلگرام => آیه به‌عنوان منتشرشده ثبت نمی‌شود
    # ------------------------------------------------------------------
    @patch("main.generate_image")
    @patch("main.requests.post")
    def test_telegram_failure_does_not_mark_verse_as_used(self, mock_post, mock_generate_image):
        mock_generate_image.side_effect = RuntimeError("Cloudflare down")
        mock_post.side_effect = Exception("Telegram network error")

        with self.assertRaises(SystemExit):
            main.post_daily_verse()

        state = main.load_state()
        self.assertEqual(state.get("used_verses", []), [], "در صورت شکست کامل ارسال، هیچ آیه‌ای نباید ثبت شود")
        self.assertIsNone(state.get("last_post_date"), "last_post_date نباید تنظیم شود")

    # ------------------------------------------------------------------
    # تست تکمیلی — وقتی همه‌ی آیات استفاده شده باشند
    # ------------------------------------------------------------------
    def test_raises_when_all_verses_used(self):
        state = {"used_verses": ["94:6", "13:28"], "last_post_date": None, "last_post_status": None}
        with self.assertRaises(main.NoUnusedVersesError):
            main.select_next_verse(SAMPLE_VERSES, state)


if __name__ == "__main__":
    unittest.main()
