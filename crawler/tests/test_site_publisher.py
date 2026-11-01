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
                patch.object(site_publisher, "_ensure_source_article_images", return_value=None),
            ):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "Không tìm được ảnh trong bài nguồn",
                ):
                    site_publisher.sync_draft_to_site(article, draft, db_path)

            record = site_publisher.get_sync_record(article["source_url"], db_path)
            self.assertIsNotNone(record)
            self.assertEqual(record["site_status"], "failed")
            self.assertIn("Cover image: RuntimeError", record["sync_error"])


    def test_source_article_photo_is_webp_hosted_and_rewritten_in_article_html(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "crawler.sqlite")
            original_url = "https://travel.example.com/media/ha-long-bay.jpg"
            hosted_url = "https://public.example.blob.vercel-storage.com/images/covers/ha-long-bay-0123456789ab.webp"
            article = {
                "source_url": "https://travel.example.com/ha-long-bay",
                "source_title": "Khám phá vịnh Hạ Long",
                "source_name": "Travel Example",
                "source_images": [{
                    "image_id": "IMG_01",
                    "url": original_url,
                    "alt": "Vịnh Hạ Long nhìn từ trên cao",
                    "caption": "Toàn cảnh vịnh Hạ Long",
                    "position_index": 1,
                    "placement_source": "article_body",
                }],
                "destination_country": "Việt Nam",
                "destination_city": "Hạ Long",
                "primary_category": "travel-guide",
            }
            draft = {
                "seo_title": "Khám phá vịnh Hạ Long",
                "meta_description": "Cẩm nang khám phá vịnh Hạ Long.",
                "secondary_keywords": ["du lịch Hạ Long", "vịnh Hạ Long"],
                "seo_content": (
                    '<p>Giới thiệu điểm đến.</p>'
                    f'<figure><img src="{original_url}" alt="Vịnh Hạ Long" /></figure>'
                ),
            }
            processed = {
                **article["source_images"][0],
                "original_url": original_url,
                "url": hosted_url,
                "asset_storage": "vercel_blob",
                "processed_format": "webp",
                "width": 1200,
                "height": 800,
                "file_size_bytes": 48000,
                "alt": "Ảnh minh họa vịnh Hạ Long tại Hạ Long, Việt Nam",
                "logo_review": {
                    "status": "no_visible_logo",
                    "confidence": "high",
                    "model": "gemini-3.8-flash",
                },
            }

            with patch(
                "image_optimizer.process_and_upload_cover_image",
                return_value=processed,
            ) as process_image:
                cover = site_publisher._ensure_source_article_images(article, db_path, draft)

            process_image.assert_called_once()
            self.assertEqual(cover["url"], hosted_url)
            self.assertTrue(cover["is_cover"])
            self.assertEqual(article["source_image_url"], hosted_url)
            self.assertIn(hosted_url, draft["seo_content"])
            self.assertNotIn(original_url, draft["seo_content"])

            payload = site_publisher.build_site_payload(article, draft)
            self.assertEqual(payload["coverImage"], hosted_url)
            self.assertNotIn(original_url, payload["contentHtml"])
            self.assertEqual(payload["status"], "published")
            self.assertEqual(payload["sourceUrl"], "https://travel.example.com/ha-long-bay")
            self.assertIn("vịnh Hạ Long", payload["coverAlt"])

    def test_site_payload_requires_self_hosted_cover(self):
        with self.assertRaisesRegex(RuntimeError, "URL HTTPS"):
            site_publisher.build_site_payload(
                {"source_title": "Bài viết", "editorial_cover_image": {"url": "http://source.example/image.jpg"}},
                {"seo_title": "Bài viết", "seo_content": "<p>Nội dung.</p>"},
            )


if __name__ == "__main__":
    unittest.main()
