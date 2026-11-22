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
                "editorial_warning_count": 1,
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
        self.assertIn("Có cảnh báo", html_body)
        self.assertIn("Lỗi cần chú ý", html_body)
        text_body = report._build_text(
            {"date": "2026-11-10", "published_count": 2, "failed_count": 1, "review_required_count": 3},
            "success",
            "",
        )
        self.assertIn("Bản nháp cũ còn chờ duyệt trong Admin: 3.", text_body)
        self.assertIn("text-overflow:ellipsis", html_body)
        self.assertNotIn(long_reason, html_body)
        self.assertIn("...", html_body)



    def test_final_report_names_the_strict_gemini_writer(self):
        report_data = {
            "date": "2026-11-17",
            "status": "warning",
            "published_count": 1,
            "failed_count": 1,
            "review_required_count": 0,
            "editorial_warning_count": 1,
            "minimum": 3,
            "preferred": 10,
            "maximum": 10,
            "article_writer_provider": "Gemini",
            "article_writer_mode": "strict",
            "article_writer_attempt_count": 3,
            "article_writer_success_count": 2,
            "article_writer_failed_count": 1,
            "article_writer_model_stats": {
                "gemini-3.8-flash": 1,
                "gemini-3.1-flash-lite": 1,
            },
            "review_required_articles": [{
                "title": "Bài đang chờ biên tập",
                "source": "VnTravel",
                "reason": "Fact reviewer đánh giá rủi ro medium; có thông tin thay đổi theo thời gian.",
                "writer_provider": "Gemini",
                "writer_model": "gemini-3.1-flash-lite",
            }],
            "review_role_provider_stats": {
                "fact": {"OpenRouter": {"success": 1, "failed": 1}, "OpenAI": {"success": 1, "failed": 0}},
                "seo": {"Groq": {"success": 2, "failed": 0}},
            },
            "articles": [{
                "title": "Bài du lịch",
                "url": "https://example.test/post",
                "ai_provider": "Gemini (viết bài từ source context)",
                "writer_provider": "Gemini",
                "review_providers": {"fact": "OpenRouter", "seo": "Groq"},
                "editorial_warnings": [
                    "Không có fact reviewer độc lập.",
                    "Ảnh đại diện chưa có metadata giấy phép rõ ràng.",
                ],
            }],
        }
        html_body = report._build_html(report_data, "success", "")
        text_body = report._build_text(report_data, "success", "")

        self.assertIn("AI viết bài:", html_body)
        self.assertIn("Gemini", html_body)
        self.assertIn("writer độc quyền", html_body)
        self.assertIn("AI viết bài: Gemini", text_body)
        self.assertIn("writer độc quyền", text_body)
        self.assertIn("AI viết: Gemini", text_body)
        self.assertIn("Gemini viết xong", html_body)
        self.assertIn("AI viết xong: <strong>2/3</strong>", html_body)
        self.assertIn("Lỗi writer: 1", html_body)
        self.assertIn("AI kiểm duyệt (không viết bài)", html_body)
        self.assertIn("Kiểm chứng nguồn — OpenAI: 1 thành công", html_body)
        self.assertIn("SEO — Groq: 2 thành công", html_body)
        self.assertIn("AI kiểm duyệt (không viết bài):", text_body)
        self.assertIn("Groq: 2 thành công", text_body)
        self.assertIn("Model Gemini thực tế", html_body)
        self.assertIn("gemini-3.1-flash-lite: 1 bản", html_body)
        self.assertIn("Bản nháp cũ còn chờ duyệt trong Admin", html_body)
        self.assertIn("Bài đang chờ biên tập", html_body)
        self.assertIn("Fact reviewer đánh giá rủi ro medium", html_body)
        self.assertIn("Model Gemini thực tế:", text_body)
        self.assertIn("BẢN NHÁP CŨ CÒN CHỜ DUYỆT TRONG ADMIN:", text_body)
        self.assertIn("Bài đang chờ biên tập", text_body)
        self.assertIn("Có cảnh báo", html_body)
        self.assertIn("Cảnh báo nội dung/ảnh", html_body)
        self.assertIn("Không có fact reviewer độc lập", html_body)
        self.assertIn("Bài đã đăng có cảnh báo nội dung/ảnh: 1.", text_body)
        self.assertIn("Cảnh báo: Không có fact reviewer độc lập", text_body)

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
