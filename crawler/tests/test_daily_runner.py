"""Regression tests for daily runner report defaults."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import daily_runner


class DailyRunnerTests(unittest.TestCase):
    def test_disabled_cover_recheck_still_writes_zeroed_report_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "crawler.sqlite")
            backfill_result = {
                "checked": 0,
                "updated": 0,
                "unmatched": 0,
                "failed": 0,
            }
            crawler_result = {
                "published_count": 1,
                "failed": 1,
                "fatal_error": False,
                "ai_quota_stop": False,
                "attempted": 1,
                "processed_articles": 1,
                "duplicate_skipped_count": 0,
                "irrelevant_skipped_count": 0,
                "duration_seconds": 1.0,
                "discovery": {
                    "enabled_sources": 1,
                    "successful_feeds": 1,
                    "failed_feeds": 0,
                    "feeds_with_items": 1,
                    "candidate_urls": 1,
                    "feed_errors": [],
                    "feed_stats": [],
                },
                "failure_items": [{
                    "stage": "ai",
                    "title": "Bài thử nghiệm chưa tạo được bản AI hoàn chỉnh",
                    "source": "Test source",
                    "reason": "Các AI provider đang tạm ngưng do quota.",
                }],
                "published_articles": [],
            }

            with (
                patch.dict(
                    os.environ,
                    {"IMAGE_BACKFILL_PER_RUN": "1", "IMAGE_RECHECK_PER_RUN": "0"},
                    clear=False,
                ),
                patch.object(daily_runner, "parse_args", return_value=SimpleNamespace(limit=1)),
                patch.object(daily_runner.bot, "DATABASE_PATH", db_path),
                patch.object(daily_runner.bot, "PROJECT_DIR", temp_dir),
                patch.object(daily_runner.bot, "init_db"),
                patch.object(daily_runner.bot, "main", return_value=crawler_result),
                patch.object(daily_runner.site_publisher, "ensure_table"),
                patch.object(daily_runner.site_publisher, "SITE_SYNC_ENABLED", True),
                patch.object(daily_runner.site_publisher, "SITE_URL", "https://didaydo.example"),
                patch.object(daily_runner.site_publisher, "SITE_INGEST_API_KEY", "test-key"),
                patch.object(daily_runner.site_publisher, "_check_api_ready"),
                patch.object(
                    daily_runner.site_publisher,
                    "backfill_missing_cover_images",
                    return_value=backfill_result,
                ),
                patch.object(daily_runner.site_publisher, "list_pending_drafts", return_value=[]),
                patch.object(daily_runner.site_publisher, "recheck_published_cover_images") as recheck,
            ):
                daily_runner.main()

            report_path = Path(temp_dir) / "logs" / "daily-report.json"
            report = json.loads(report_path.read_text(encoding="utf-8"))

            self.assertEqual(report["cover_recheck_checked"], 0)
            self.assertEqual(report["cover_recheck_updated"], 0)
            self.assertEqual(report["cover_recheck_unmatched"], 0)
            self.assertEqual(report["cover_recheck_failed"], 0)
            self.assertEqual(report["status"], "warning")
            self.assertEqual(report["failed_count"], 1)
            self.assertFalse(report["fatal_error"])
            recheck.assert_not_called()


if __name__ == "__main__":
    unittest.main()
