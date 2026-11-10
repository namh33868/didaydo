"""Tests for the single consolidated daily crawler email."""
import unittest
from unittest.mock import patch

import send_daily_report as report


class DailyReportEmailTests(unittest.TestCase):
    def test_provider_errors_are_summarized_in_vietnamese(self):
        self.assertEqual(
            report._short_error("Groq returned HTTP 429 TPM rate limit exceeded"),
            "Groq vượt giới hạn tốc độ (429/TPM).",
        )
        self.assertEqual(
            report._short_error("Gemini RESOURCE_EXHAUSTED daily quota exceeded"),
            "Gemini đã hết hạn mức sử dụng.",
        )
        self.assertEqual(
            report._short_error("OpenRouter invalid JSON response"),
            "AI trả về dữ liệu sai định dạng.",
        )

    def test_long_error_is_truncated_with_ellipsis(self):
        shortened = report._short_error("x" * 400)
        self.assertLessEqual(len(shortened), 112)
        self.assertTrue(shortened.endswith("..."))

    def test_final_email_uses_compact_layout_and_clips_long_errors(self):
        long_reason = "Provider failure detail " * 30
        html_body = report._build_html(
            {
                "date": "2026-11-04",
                "status": "warning",
                "published_count": 2,
                "failed_count": 1,
                "review_required_count": 3,
                "minimum": 3,
                "preferred": 5,
                "maximum": 10,
                "successful_feed_count": 8,
                "failed_feed_count": 1,
                "articles": [{"title": "Bài đã đăng", "url": "https://example.test/post"}],
                "failures": [{
                    "stage": "ai",
                    "title": "Bài chưa đăng",
                    "reason": long_reason,
                }],
            },
            "success",
            "https://github.com/example/repo/actions/runs/1",
        )
        self.assertIn("Bài đã xuất bản", html_body)
        self.assertIn("Chờ duyệt", html_body)
        self.assertIn("Lỗi cần chú ý", html_body)
        text_body = report._build_text(
            {"date": "2026-11-10", "published_count": 2, "failed_count": 1, "review_required_count": 3},
            "success",
            "",
        )
        self.assertIn("Bài chờ kiểm duyệt: 3.", text_body)
        self.assertIn("text-overflow:ellipsis", html_body)
        self.assertNotIn(long_reason, html_body)
        self.assertIn("...", html_body)



    def test_report_command_sends_one_final_summary_only(self):
        with (
            patch("sys.argv", ["send_daily_report.py"]),
            patch.object(report, "_load_report", return_value={
                "date": "2026-11-10",
                "status": "completed",
                "published_count": 2,
                "articles": [],
                "failures": [],
            }),
            patch.object(report, "_recipients", return_value=["test@example.com"]),
            patch.object(report, "_run_url", return_value=""),
            patch.object(report, "_write_summary"),
            patch.object(report, "_send_email", return_value=True) as send_email,
        ):
            self.assertEqual(report.main(), 0)

        send_email.assert_called_once()
        self.assertEqual(send_email.call_args.args[4], "final")


if __name__ == "__main__":
    unittest.main()
