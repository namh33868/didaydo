"""Tests for the parallel editorial AI roles, adaptive cooldowns and HTML sources."""
import json
import tempfile
import threading
import time
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

import main


class AdaptiveCooldownTests(unittest.TestCase):
    def setUp(self):
        self.previous = {
            "disabled": dict(main._AI_PROVIDERS_DISABLED_FOR_RUN),
            "cooldowns": dict(main._AI_PROVIDER_COOLDOWN_UNTIL),
            "meta": dict(main._AI_PROVIDER_COOLDOWN_META),
            "counts": dict(main._AI_PROVIDER_FAILURE_COUNTS),
            "loaded": main._AI_PROVIDER_STATE_LOADED,
        }
        main._AI_PROVIDERS_DISABLED_FOR_RUN.clear()
        main._AI_PROVIDER_COOLDOWN_UNTIL.clear()
        main._AI_PROVIDER_COOLDOWN_META.clear()
        main._AI_PROVIDER_FAILURE_COUNTS.clear()
        main._AI_PROVIDER_STATE_LOADED = True
        self.temp_dir = tempfile.TemporaryDirectory()
        self.state_path = str(Path(self.temp_dir.name) / "ai_provider_state.json")
        self.path_patch = patch.object(main, "_AI_PROVIDER_STATE_PATH", self.state_path)
        self.path_patch.start()

    def tearDown(self):
        self.path_patch.stop()
        main._AI_PROVIDERS_DISABLED_FOR_RUN.clear()
        main._AI_PROVIDERS_DISABLED_FOR_RUN.update(self.previous["disabled"])
        main._AI_PROVIDER_COOLDOWN_UNTIL.clear()
        main._AI_PROVIDER_COOLDOWN_UNTIL.update(self.previous["cooldowns"])
        main._AI_PROVIDER_COOLDOWN_META.clear()
        main._AI_PROVIDER_COOLDOWN_META.update(self.previous["meta"])
        main._AI_PROVIDER_FAILURE_COUNTS.clear()
        main._AI_PROVIDER_FAILURE_COUNTS.update(self.previous["counts"])
        main._AI_PROVIDER_STATE_LOADED = self.previous["loaded"]
        self.temp_dir.cleanup()

    def test_parse_retry_durations(self):
        self.assertAlmostEqual(main._parse_duration_seconds("7.66s"), 7.66)
        self.assertAlmostEqual(main._parse_duration_seconds("2m13.4s"), 133.4)
        self.assertEqual(main._parse_duration_seconds("1h2m"), 3720)
        self.assertEqual(main._parse_duration_seconds("00:02:03"), 123)

    def test_groq_token_reset_header_controls_cooldown_and_persists(self):
        error = RuntimeError("429 rate limit: tokens per minute exceeded")
        error.response = SimpleNamespace(headers={"x-ratelimit-reset-tokens": "7.66s"})

        main._record_provider_failure("Groq", error)

        metadata = main._AI_PROVIDER_COOLDOWN_META["Groq"]
        until = datetime.fromisoformat(metadata["until"])
        remaining = (until - datetime.now(until.tzinfo)).total_seconds()
        self.assertEqual(metadata["kind"], "rate_limit_or_transient")
        self.assertGreater(remaining, 5)
        self.assertLess(remaining, 10)
        saved = json.loads(Path(self.state_path).read_text(encoding="utf-8"))
        self.assertIn("Groq", saved["cooldowns"])

    def test_gemini_daily_quota_waits_for_next_pacific_midnight(self):
        reset = main._next_gemini_daily_reset_utc().astimezone(ZoneInfo("America/Los_Angeles"))
        now = datetime.now(ZoneInfo("America/Los_Angeles"))
        self.assertGreater(reset.date(), now.date())
        self.assertEqual((reset.hour, reset.minute, reset.second), (0, 0, 0))

        main._record_provider_failure(
            "Gemini",
            RuntimeError("Generate content requests per day limit exceeded"),
        )
        metadata = main._AI_PROVIDER_COOLDOWN_META["Gemini"]
        self.assertEqual(metadata["kind"], "daily_quota")
        until = datetime.fromisoformat(metadata["until"]).astimezone(ZoneInfo("America/Los_Angeles"))
        self.assertEqual((until.hour, until.minute, until.second), (0, 0, 0))
        self.assertIn("Gemini", main._AI_PROVIDERS_DISABLED_FOR_RUN)


class ParallelEditorialTests(unittest.TestCase):
    def test_groq_and_openrouter_reviews_run_concurrently(self):
        barrier = threading.Barrier(2)
        seo_result = json.dumps({
            "score": 84,
            "seo_title": "Kinh nghiệm du lịch Đà Nẵng tự túc",
            "meta_description": "Cẩm nang du lịch Đà Nẵng với các gợi ý thực tế về lịch trình, ăn uống và điểm tham quan phù hợp.",
            "primary_keyword": "du lịch Đà Nẵng",
            "secondary_keywords": ["kinh nghiệm Đà Nẵng", "điểm tham quan Đà Nẵng", "ẩm thực Đà Nẵng"],
            "critical_issues": [],
            "improvements": ["Bổ sung thêm thông tin chi phí nếu nguồn hỗ trợ."]
        }, ensure_ascii=False)
        fact_result = json.dumps({
            "risk_level": "low",
            "unsupported_claims": [],
            "contradictions": [],
            "time_sensitive_claims": [],
            "notes": "Bản nháp bám sát tư liệu tham khảo được cung cấp."
        }, ensure_ascii=False)

        def groq_call(*_args, **_kwargs):
            barrier.wait(timeout=5)
            return seo_result

        def openrouter_call(*_args, **_kwargs):
            barrier.wait(timeout=5)
            return fact_result

        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = str(Path(temp_dir) / "ai_provider_state.json")
            with (
                patch.object(main, "GROQ_API_KEY", "test-groq"),
                patch.object(main, "OPENROUTER_API_KEY", "test-openrouter"),
                patch.object(main, "_AI_PROVIDER_STATE_PATH", state_path),
                patch.object(main, "_AI_PROVIDER_STATE_LOADED", True),
                patch.object(main, "_call_groq", side_effect=groq_call),
                patch.object(main, "_call_openrouter", side_effect=openrouter_call),
            ):
                main._AI_PROVIDER_COOLDOWN_UNTIL.clear()
                main._AI_PROVIDER_COOLDOWN_META.clear()
                main._AI_PROVIDER_FAILURE_COUNTS.clear()
                reviews = main._run_parallel_editorial_reviews(
                    article={
                        "source_title": "Khám phá Đà Nẵng",
                        "source_summary": "Gợi ý điểm đến tại Đà Nẵng.",
                        "source_url": "https://example.test/danang",
                        "source_body": "Thông tin điểm đến và trải nghiệm. " * 150,
                    },
                    draft={
                        "seo_title": "Du lịch Đà Nẵng",
                        "seo_description": "Gợi ý du lịch Đà Nẵng và trải nghiệm địa phương.",
                        "primary_keyword": "du lịch Đà Nẵng",
                        "secondary_keywords": '["ẩm thực Đà Nẵng", "điểm đến Đà Nẵng", "kinh nghiệm du lịch"]',
                        "seo_content": "<h2>Khám phá Đà Nẵng</h2><p>" + ("Đà Nẵng có nhiều trải nghiệm du lịch hấp dẫn. " * 80) + "</p>",
                    },
                    writer_provider="Gemini",
                )

        self.assertEqual(reviews["seo"]["score"], 84)
        self.assertEqual(reviews["fact"]["risk_level"], "low")

    def test_seo_quality_check_rewards_complete_vietnamese_structure(self):
        body = (
            "<h2>Trải nghiệm du lịch Đà Nẵng</h2>"
            + "".join(
                "<p>" + ("Du lịch Đà Nẵng có nhiều trải nghiệm hữu ích cho hành trình khám phá thành phố. " * 30) + "</p>"
                for _ in range(4)
            )
            + "<h2>Kinh nghiệm cần biết</h2>"
        )
        draft = {
            "seo_title": "Kinh nghiệm du lịch Đà Nẵng tự túc",
            "seo_description": "Cẩm nang du lịch Đà Nẵng với những gợi ý thiết thực về lịch trình, ăn uống và điểm tham quan.",
            "primary_keyword": "du lịch Đà Nẵng",
            "secondary_keywords": json.dumps(["ẩm thực Đà Nẵng", "điểm tham quan", "kinh nghiệm du lịch"]),
            "seo_content": body,
        }
        score, checks = main._evaluate_seo_quality(draft)
        self.assertGreaterEqual(score, 90)
        self.assertTrue(checks["primary_keyword_early"])
        self.assertGreaterEqual(checks["word_count"], 350)


class HtmlSourceTests(unittest.TestCase):
    def test_vinpearl_listing_parser_extracts_article_cards_not_navigation(self):
        html = """
        <html lang="vi"><body>
          <nav><a href="/vi/news/travel-guide">Cẩm nang du lịch</a></nav>
          <article class="article-card">
            <a href="/vi/vinpearl-harbour-nha-trang-kinh-nghiem-kham-pha">
              <img src="/sites/default/files/harbour.jpg" alt="Vinpearl Harbour">
              Kinh nghiệm khám phá Vinpearl Harbour Nha Trang
            </a>
            <p>Gợi ý vui chơi và trải nghiệm tại Nha Trang.</p>
            <time>23/08/2026</time>
          </article>
        </body></html>
        """
        source = {
            "id": "vinpearl_travel_guide",
            "name": "Vinpearl – Cẩm nang du lịch",
            "homepage": "https://vinpearl.com/vi",
            "feed_url": "https://vinpearl.com/vi/news/travel-guide",
            "article_domains": ["vinpearl.com"],
            "language": "vi",
            "allow_source_images": False,
            "permission_status": "metadata_and_reference_only",
            "focus": ["travel-guide"],
        }
        items = main._parse_html_listing_items(html, source)
        self.assertEqual(len(items), 1)
        self.assertIn("/vi/vinpearl-harbour-nha-trang-kinh-nghiem-kham-pha", items[0]["source_url"])
        self.assertEqual(items[0]["source_id"], "vinpearl_travel_guide")
        self.assertFalse(items[0]["allow_source_images"])

    def test_source_with_unapproved_images_has_markers_removed(self):
        draft = {"seo_content": "<p>Mở bài.</p><p>[[IMAGE:IMG_01]]</p><p>Nội dung.</p>"}
        result = main._insert_inline_images({"allow_source_images": False}, draft)
        self.assertNotIn("[[IMAGE:", result["seo_content"])
        self.assertNotIn("image-rights-review", result["seo_content"])
        self.assertNotIn("<figure", result["seo_content"])


if __name__ == "__main__":
    unittest.main()
