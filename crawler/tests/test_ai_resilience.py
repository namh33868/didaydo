"""Regression tests for AI request sizing and fallback resilience."""
import unittest
from unittest.mock import patch

import main


class AIResilienceTests(unittest.TestCase):
    def test_source_reference_is_bounded_and_preserves_both_ends(self):
        source = "INTRO " + ("A" * 180) + " MIDDLE " + ("B" * 180) + " ENDING"
        prepared = main._prepare_source_reference_text(source, max_chars=120)

        self.assertLessEqual(len(prepared), 120)
        self.assertTrue(prepared.startswith("INTRO"))
        self.assertTrue(prepared.endswith("ENDING"))
        self.assertIn("đã lược bớt", prepared)

    def test_default_output_budgets_are_bounded_for_constrained_groq(self):
        self.assertLessEqual(main.AI_MAX_OUTPUT_TOKENS, 8000)
        self.assertLessEqual(main.GROQ_MAX_OUTPUT_TOKENS, main.AI_MAX_OUTPUT_TOKENS)
        self.assertLess(main.GROQ_MAX_OUTPUT_TOKENS, main.AI_MAX_OUTPUT_TOKENS)

    def test_single_ai_failure_does_not_trigger_run_stop(self):
        self.assertFalse(main._should_stop_after_ai_failures(1, threshold=2))
        self.assertTrue(main._should_stop_after_ai_failures(2, threshold=2))

    def test_request_too_large_is_not_misclassified_as_global_quota(self):
        self.assertFalse(main._is_ai_capacity_error("HTTP 413: Request too large for model"))
        self.assertTrue(main._is_ai_capacity_error("HTTP 429: rate limit exceeded"))

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
