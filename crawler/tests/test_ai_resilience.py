"""Regression tests for AI request sizing and fallback resilience."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import main


class AIResilienceTests(unittest.TestCase):
    def setUp(self):
        self.previous = {
            "disabled": dict(main._AI_PROVIDERS_DISABLED_FOR_RUN),
            "cooldowns": dict(main._AI_PROVIDER_COOLDOWN_UNTIL),
            "meta": dict(main._AI_PROVIDER_COOLDOWN_META),
            "counts": dict(main._AI_PROVIDER_FAILURE_COUNTS),
            "loaded": main._AI_PROVIDER_STATE_LOADED,
            "last_gemini_model": main._LAST_GEMINI_MODEL_USED,
        }
        self.production_state_path = main._AI_PROVIDER_STATE_PATH
        self.temp_dir = tempfile.TemporaryDirectory()
        self.state_path = str(Path(self.temp_dir.name) / "ai_provider_state.json")
        self.path_patch = patch.object(main, "_AI_PROVIDER_STATE_PATH", self.state_path)
        self.path_patch.start()

        # These tests deliberately simulate provider failures. Never let those
        # synthetic cooldowns read from or overwrite crawler/data state that the
        # real daily crawler restores from the GitHub Actions cache.
        main._AI_PROVIDERS_DISABLED_FOR_RUN.clear()
        main._AI_PROVIDER_COOLDOWN_UNTIL.clear()
        main._AI_PROVIDER_COOLDOWN_META.clear()
        main._AI_PROVIDER_FAILURE_COUNTS.clear()
        main._AI_PROVIDER_STATE_LOADED = True

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
        with main._LAST_GEMINI_MODEL_USED_LOCK:
            main._LAST_GEMINI_MODEL_USED = self.previous["last_gemini_model"]
        self.temp_dir.cleanup()

    def test_gemini_transient_and_model_daily_quota_can_use_same_provider_fallback(self):
        self.assertTrue(main._gemini_model_fallback_allowed(RuntimeError("503 UNAVAILABLE")))
        self.assertTrue(main._gemini_model_fallback_allowed(RuntimeError("504 DEADLINE_EXCEEDED")))
        self.assertTrue(main._gemini_model_fallback_allowed(RuntimeError(
            "429 RESOURCE_EXHAUSTED: GenerateRequestsPerDayPerModel-FreeTier"
        )))
        self.assertFalse(main._gemini_model_fallback_allowed(RuntimeError(
            "429 rate limit: tokens per minute exceeded"
        )))
        self.assertFalse(main._gemini_model_fallback_allowed(RuntimeError(
            "401 UNAUTHENTICATED: API key invalid"
        )))

    def test_gemini_writer_retries_with_lite_model_without_changing_provider(self):
        with (
            patch.object(main, "GEMINI_MODEL", "gemini-3.1-flash-lite"),
            patch.object(main, "GEMINI_FALLBACK_MODEL", "gemini-3.8-flash"),
            patch.object(main, "GEMINI_TIMEOUT_MS", 120000),
            patch.object(main, "GEMINI_FALLBACK_TIMEOUT_MS", 180000),
            patch.object(main, "GEMINI_RETRY_ATTEMPTS", 2),
            patch.object(
                main,
                "_call_gemini_model",
                side_effect=[
                    RuntimeError("503 UNAVAILABLE: model overloaded"),
                    '{"seo_title":"Bài thử","content_html":"<p>Nội dung thử</p>"}',
                ],
            ) as model_call,
        ):
            raw = main._call_gemini("instructions", {"source": "facts"}, max_output_tokens=4000)

        self.assertIn("seo_title", raw)
        self.assertEqual(
            [call.args[0] for call in model_call.call_args_list],
            ["gemini-3.1-flash-lite", "gemini-3.8-flash"],
        )
        self.assertEqual(model_call.call_args_list[0].args[4:], (120000, 2))
        self.assertEqual(model_call.call_args_list[1].args[4:], (180000, 2))
        self.assertEqual(main._LAST_GEMINI_MODEL_USED, "gemini-3.8-flash")

    def test_gemini_retry_options_use_backoff_and_do_not_retry_quota_429(self):
        class RetryOptionsCapture:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        fake_types = type("FakeTypes", (), {"HttpRetryOptions": RetryOptionsCapture})
        with (
            patch.object(main, "GEMINI_RETRY_INITIAL_DELAY_SECONDS", 2.0),
            patch.object(main, "GEMINI_RETRY_MAX_DELAY_SECONDS", 20.0),
        ):
            options = main._build_gemini_http_retry_options(fake_types, 2)

        self.assertEqual(options.kwargs["attempts"], 2)
        self.assertEqual(options.kwargs["initial_delay"], 2.0)
        self.assertEqual(options.kwargs["max_delay"], 20.0)
        self.assertEqual(options.kwargs["exp_base"], 2.0)
        self.assertEqual(options.kwargs["jitter"], 1.0)
        self.assertEqual(options.kwargs["http_status_codes"], [408, 500, 502, 503, 504])
        self.assertNotIn(429, options.kwargs["http_status_codes"])

    def test_reviewer_payload_includes_source_dates_and_temporal_prompt(self):
        payload = main._review_payload(
            {
                "source_title": "Thông báo du lịch",
                "source_summary": "Sự kiện diễn ra theo thời hạn công bố.",
                "source_url": "https://example.test/source",
                "published_at": "2026-11-19",
                "source_modified_at": "2026-11-19",
                "source_body": "Thông tin nguồn " * 40,
            },
            {"seo_content": "<p>Bài viết</p>"},
            8000,
            7000,
        )
        self.assertEqual(payload["source_published_at"], "2026-11-19")
        self.assertEqual(payload["source_updated_at"], "2026-11-19")
        self.assertIn("KHÔNG đánh dấu", main.FACT_REVIEW_INSTRUCTIONS)
        self.assertIn("mốc ngày", main.FACT_REVIEW_INSTRUCTIONS)

    def test_source_reference_is_bounded_and_preserves_both_ends(self):
        source = "INTRO " + ("A" * 180) + " MIDDLE " + ("B" * 180) + " ENDING"
        prepared = main._prepare_source_reference_text(source, max_chars=120)

        self.assertLessEqual(len(prepared), 120)
        self.assertTrue(prepared.startswith("INTRO"))
        self.assertTrue(prepared.endswith("ENDING"))
        self.assertIn("đã lược bớt", prepared)

    def test_primary_providers_keep_a_larger_output_budget(self):
        self.assertGreaterEqual(main.AI_MAX_OUTPUT_TOKENS, 9000)
        self.assertLessEqual(main.AI_MAX_OUTPUT_TOKENS, 12000)
        self.assertLessEqual(main.GROQ_MAX_OUTPUT_TOKENS, main.AI_MAX_OUTPUT_TOKENS)
        self.assertLess(main.GROQ_MAX_OUTPUT_TOKENS, main.AI_MAX_OUTPUT_TOKENS)

    def test_only_groq_fallback_gets_compacted_source_context(self):
        source = "INTRO " + ("source detail " * 1000) + " ENDING"
        payload = {
            "source_reference_material": source,
            "source_reference_chars": len(source),
            "source_reference_truncated": False,
            "structured_fact_sheet": {"facts": [{"fact": "Retained fact"}]},
        }

        compacted = main._groq_request_input(payload, max_chars=4000)

        self.assertEqual(len(payload["source_reference_material"]), len(source))
        self.assertEqual(compacted["source_reference_chars"], len(compacted["source_reference_material"]))
        self.assertLessEqual(compacted["source_reference_chars"], 4000)
        self.assertTrue(compacted["source_reference_truncated"])
        self.assertEqual(compacted["structured_fact_sheet"], payload["structured_fact_sheet"])

    def test_single_ai_failure_does_not_trigger_run_stop(self):
        self.assertFalse(main._should_stop_after_ai_failures(1, threshold=2))
        self.assertTrue(main._should_stop_after_ai_failures(2, threshold=2))

    def test_request_too_large_is_not_misclassified_as_global_quota(self):
        self.assertFalse(main._is_ai_capacity_error("HTTP 413: Request too large for model"))
        self.assertTrue(main._is_ai_capacity_error("HTTP 429: rate limit exceeded"))

    def test_advertising_gif_and_banner_images_are_rejected(self):
        from bs4 import BeautifulSoup

        gif = BeautifulSoup('<img src="https://example.com/animated.gif" alt="Aerial view">', "html.parser").img
        banner = BeautifulSoup('<div class="advertisement-banner"><img src="https://example.com/photo.jpg"></div>', "html.parser").img
        photo = BeautifulSoup('<figure><img src="https://example.com/coast.jpg" width="1600" height="900" alt="Coast"></figure>', "html.parser").img

        self.assertTrue(main._is_promotional_or_decorative_image(gif, gif["src"]))
        self.assertTrue(main._is_promotional_or_decorative_image(banner, banner["src"]))
        self.assertFalse(main._is_promotional_or_decorative_image(photo, photo["src"]))

    def test_english_output_is_rejected_but_vietnamese_is_accepted(self):
        with self.assertRaisesRegex(ValueError, "tiếng Anh"):
            main._validate_vietnamese_output(
                "Best places to visit in Japan",
                "Discover the best things to do in Kyoto.",
                "The city is one of the most popular places for travelers. " * 12,
            )

        main._validate_vietnamese_output(
            "Kinh nghiệm khám phá Kyoto vào mùa thu",
            "Những gợi ý hữu ích cho chuyến đi Kyoto.",
            "Kyoto có nhiều ngôi đền và khu phố cổ đáng khám phá vào mùa thu. " * 12,
        )

    def test_daily_quota_provider_is_skipped_for_rest_of_run(self):
        with (
            patch.object(main, "GEMINI_API_KEY", "test-gemini-key"),
            patch.object(main, "OPENAI_API_KEY", ""),
            patch.object(main, "GROQ_API_KEY", "test-groq-key"),
            patch.object(main, "OPENROUTER_API_KEY", ""),
            patch.object(
                main,
                "_call_gemini",
                side_effect=RuntimeError(
                    "429 RESOURCE_EXHAUSTED: Generate content requests per day limit exceeded"
                ),
            ) as gemini,
            patch.object(main, "_call_groq", return_value='{"ok": true}') as groq,
        ):
            for _ in range(2):
                result, provider, _reason = main._call_json_with_fallback(
                    "test",
                    "instructions",
                    {"input": "small"},
                    lambda raw, _provider: raw,
                )
                self.assertEqual(result, '{"ok": true}')
                self.assertEqual(provider, "Groq")

        self.assertEqual(gemini.call_count, 1)
        self.assertEqual(groq.call_count, 2)
        self.assertIn("Gemini", main._AI_PROVIDERS_DISABLED_FOR_RUN)
        self.assertTrue(Path(self.state_path).is_file())
        self.assertNotEqual(self.state_path, self.production_state_path)

    def test_transient_rate_limit_puts_provider_on_cooldown(self):
        with (
            patch.object(main, "GEMINI_API_KEY", "test-gemini-key"),
            patch.object(main, "OPENAI_API_KEY", ""),
            patch.object(main, "GROQ_API_KEY", "test-groq-key"),
            patch.object(main, "OPENROUTER_API_KEY", ""),
            patch.object(
                main,
                "_call_gemini",
                side_effect=RuntimeError("429 rate limit: tokens per minute exceeded"),
            ) as gemini,
            patch.object(main, "_call_groq", return_value='{"ok": true}') as groq,
        ):
            for _ in range(2):
                result, provider, _reason = main._call_json_with_fallback(
                    "test",
                    "instructions",
                    {"input": "small"},
                    lambda raw, _provider: raw,
                )
                self.assertEqual(result, '{"ok": true}')
                self.assertEqual(provider, "Groq")

        self.assertEqual(gemini.call_count, 1)
        self.assertEqual(groq.call_count, 2)
        self.assertIn("Gemini", main._AI_PROVIDER_COOLDOWN_UNTIL)
        self.assertTrue(Path(self.state_path).is_file())

    def test_cover_image_failure_is_article_level_not_site_failure(self):
        self.assertTrue(main._is_cover_only_publish_failure(
            "RuntimeError: Bài nguồn không có ảnh hợp lệ và cũng không tìm được ảnh ngoài phù hợp; bài được giữ lại."
        ))
        self.assertFalse(main._is_cover_only_publish_failure("HTTP 500: Vercel ingest API unavailable"))

    def test_article_writing_never_falls_back_from_gemini_to_groq(self):
        with (
            patch.object(main, "AI_WRITER_PROVIDER", "Gemini"),
            patch.object(main, "GEMINI_API_KEY", "test-gemini-key"),
            patch.object(main, "OPENAI_API_KEY", ""),
            patch.object(main, "GROQ_API_KEY", "test-groq-key"),
            patch.object(main, "OPENROUTER_API_KEY", "test-openrouter-key"),
            patch.object(
                main,
                "_call_gemini",
                side_effect=RuntimeError("503 UNAVAILABLE: Gemini is temporarily overloaded"),
            ) as gemini,
            patch.object(main, "_call_groq", return_value='{"ok": true}') as groq,
            patch.object(main, "_call_openrouter", return_value='{"ok": true}') as openrouter,
        ):
            with self.assertRaisesRegex(
                RuntimeError, "không chuyển sang AI provider khác để viết bài"
            ):
                main._call_json_with_fallback(
                    "article-writing",
                    "instructions",
                    {"input": "small"},
                    lambda raw, _provider: raw,
                )

        gemini.assert_called_once()
        groq.assert_not_called()
        openrouter.assert_not_called()

    def test_review_attempts_are_attributed_to_reviewers_not_the_writer(self):
        with (
            patch.object(main, "OPENROUTER_API_KEY", "test-openrouter-key"),
            patch.object(main, "OPENAI_API_KEY", ""),
            patch.object(main, "GEMINI_API_KEY", "test-gemini-key"),
            patch.object(main, "GROQ_API_KEY", "test-groq-key"),
            patch.object(main, "_provider_unavailable_reason", return_value=""),
            patch.object(main, "_review_payload", return_value={}),
            patch.object(
                main,
                "_run_one_editorial_review",
                side_effect=lambda role, provider, *_args: (
                    {"status": "passed"} if role == "fact" else {"score": 88}
                ),
            ),
        ):
            reviews = main._run_parallel_editorial_reviews({}, {}, "Gemini")

        self.assertEqual(reviews["fact"]["provider"], "OpenRouter")
        self.assertEqual(reviews["seo"]["provider"], "Groq")
        self.assertEqual(
            reviews["_attempts"],
            [
                {"role": "fact", "provider": "OpenRouter", "outcome": "success"},
                {"role": "seo", "provider": "Groq", "outcome": "success"},
            ],
        )
        self.assertNotIn("Groq", [reviews.get("writer_provider")])

    def test_fallback_tries_next_provider_after_one_provider_fails(self):
        def fail():
            raise RuntimeError("temporary provider outage")

        with patch.object(
            main,
            "_configured_ai_providers",
            return_value=[("Gemini", fail), ("Groq", lambda: '{"ok": true}')],
        ):
            result, provider, fallback_reason = main._call_json_with_fallback(
                "test",
                "instructions",
                {"input": "small"},
                lambda raw, _provider: raw,
            )

        self.assertEqual(result, '{"ok": true}')
        self.assertEqual(provider, "Groq")
        self.assertIn("Gemini", fallback_reason)


if __name__ == "__main__":
    unittest.main()
