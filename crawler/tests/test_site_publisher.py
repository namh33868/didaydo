"""Regression tests for the crawler-to-website sync state."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import site_publisher


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.reason = "OK"
        self.ok = 200 <= status_code < 400

    def json(self):
        return self._payload

    def raise_for_status(self):
        if not self.ok:
            raise RuntimeError(f"HTTP {self.status_code}")


class SitePublisherSyncStateTests(unittest.TestCase):
    def test_record_sync_upserts_status_and_keeps_known_remote_ids(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "crawler.sqlite")
            source_url = "https://example.com/travel/story"

            site_publisher._record_sync(
                db_path,
                source_url,
                status="failed",
                error="Cover image: no licensed match",
            )
            site_publisher._record_sync(
                db_path,
                source_url,
                post_id=123,
                slug="story",
                status="published",
                site_url="https://didaydo.vercel.app/bai-viet/story",
            )

            record = site_publisher.get_sync_record(source_url, db_path)
            self.assertIsNotNone(record)
            self.assertEqual(record["site_post_id"], "123")
            self.assertEqual(record["site_slug"], "story")
            self.assertEqual(record["site_status"], "published")
            self.assertEqual(record["site_url"], "https://didaydo.vercel.app/bai-viet/story")
            self.assertIsNone(record["sync_error"])

    def test_missing_licensed_cover_is_recorded_without_masking_original_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "crawler.sqlite")
            article = {
                "source_url": "https://example.com/travel/no-cover",
                "source_title": "A travel article",
            }
            draft = {
                "seo_title": "A travel article",
                "seo_content": "<p>Editorial content.</p>",
            }

            with (
                patch.object(site_publisher, "SITE_SYNC_ENABLED", True),
                patch.object(site_publisher, "SITE_URL", "https://didaydo.example"),
                patch.object(site_publisher, "SITE_INGEST_API_KEY", "x" * 32),
                patch.object(site_publisher, "_check_api_ready"),
                patch(
                    "site_publisher.requests.get",
                    return_value=FakeResponse({"found": False}),
                ),
                patch.object(site_publisher, "_ensure_editorial_cover_image", return_value=None),
            ):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "Không tìm được ảnh đại diện phù hợp",
                ):
                    site_publisher.sync_draft_to_site(article, draft, db_path)

            record = site_publisher.get_sync_record(article["source_url"], db_path)
            self.assertIsNotNone(record)
            self.assertEqual(record["site_status"], "failed")
            self.assertIn("Cover image: RuntimeError", record["sync_error"])


if __name__ == "__main__":
    unittest.main()
