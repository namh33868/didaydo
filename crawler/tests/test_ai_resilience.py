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
