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
                    "Bài nguồn không có ảnh hợp lệ",
                ):
                    site_publisher.sync_draft_to_site(article, draft, db_path)

            record = site_publisher.get_sync_record(article["source_url"], db_path)
            self.assertIsNotNone(record)
            self.assertEqual(record["site_status"], "failed")
            self.assertIn("Cover image: RuntimeError", record["sync_error"])


    def test_source_article_photo_uses_original_url_without_processing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "crawler.sqlite")
            original_url = "http://travel.example.com/media/ha-long-bay.jpg"
            normalized_url = "https://travel.example.com/media/ha-long-bay.jpg"
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

            with (
                patch("image_optimizer.process_and_upload_cover_image") as process_image,
                patch("image_finder.find_cover_image") as external_search,
            ):
                cover = site_publisher._ensure_source_article_images(article, db_path, draft)

            process_image.assert_not_called()
            external_search.assert_not_called()
            self.assertEqual(cover["url"], normalized_url)
            self.assertTrue(cover["is_cover"])
            self.assertEqual(article["source_image_url"], normalized_url)
            self.assertIn(normalized_url, draft["seo_content"])
            self.assertNotIn(original_url, draft["seo_content"])
            self.assertIn("loading=", draft["seo_content"])

            payload = site_publisher.build_site_payload(article, draft)
            self.assertEqual(payload["coverImage"], normalized_url)
            self.assertEqual(payload["status"], "published")
            self.assertEqual(payload["sourceUrl"], "https://travel.example.com/ha-long-bay")
            self.assertIn("Vịnh Hạ Long", payload["coverAlt"])

    def test_external_image_search_runs_only_when_source_has_no_image(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "crawler.sqlite")
            article = {
                "source_url": "https://travel.example.com/no-image",
                "source_title": "Khám phá một điểm đến",
                "source_name": "Travel Example",
                "source_images": [],
                "destination_country": "Việt Nam",
                "destination_city": "Đà Nẵng",
                "primary_category": "travel-guide",
            }
            draft = {
                "seo_title": "Khám phá một điểm đến",
                "seo_content": "<p>Nội dung biên tập.</p>",
            }
            external = {
                "url": "https://images.example.net/da-nang-coast.jpg",
                "title": "Da Nang coastline",
                "creator": "Photo creator",
                "provider": "Openverse",
                "source_page_url": "https://openverse.example.net/photo/123",
                "license": "CC BY 4.0",
                "license_url": "https://creativecommons.org/licenses/by/4.0/",
                "image_scope": "exact_destination",
                "relevance_verified": True,
            }

            with (
                patch("image_finder.find_cover_image", return_value=external) as external_search,
                patch("image_optimizer.process_and_upload_cover_image") as process_image,
            ):
                cover = site_publisher._ensure_source_article_images(article, db_path, draft)

            external_search.assert_called_once()
            process_image.assert_not_called()
            self.assertEqual(cover["url"], external["url"])
            self.assertEqual(cover["asset_storage"], "external_source")
            self.assertEqual(cover["license"], "CC BY 4.0")
            self.assertEqual(cover["source_page_url"], external["source_page_url"])
            self.assertEqual(cover["cover_role"], "external_fallback_cover")

    def test_no_source_photo_or_external_match_returns_none(self):
        article = {
            "source_url": "https://travel.example.com/no-photo",
            "source_title": "Bài viết không có ảnh",
            "source_images": [],
        }
        with patch("image_finder.find_cover_image", return_value=None) as search:
            result = site_publisher._ensure_source_article_images(article, ":memory:")
        search.assert_called_once()
        self.assertIsNone(result)

    def test_historical_backfill_uses_source_image_before_external_search(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "crawler.sqlite")
            source_url = "https://travel.example.com/old-story"
            source_image = "https://travel.example.com/images/old-story.jpg"
            article_extractor = lambda item: {
                "source_url": item["source_url"],
                "source_title": item["rss_title"],
                "source_name": "Travel Example",
                "source_images": [{
                    "image_id": "IMG_01",
                    "url": source_image,
                    "alt": "Ảnh bãi biển",
                    "caption": "Bãi biển",
                    "position_index": 1,
                    "placement_source": "article_body",
                    "source_page_url": source_url,
                }],
            }

            with (
                patch.object(site_publisher, "SITE_SYNC_ENABLED", True),
                patch.object(site_publisher, "SITE_URL", "https://didaydo.example"),
                patch.object(site_publisher, "SITE_INGEST_API_KEY", "x" * 32),
                patch.object(site_publisher, "_check_api_ready"),
                patch(
                    "site_publisher.requests.get",
                    return_value=FakeResponse({"posts": [{
                        "source_url": source_url,
                        "title": "Bài cũ",
                        "excerpt": "Tóm tắt bài cũ",
                        "source_name": "Travel Example",
                        "category_name": "Điểm đến",
                        "country_name": "Việt Nam",
                        "destination_name": "Đà Nẵng",
                    }]}),
                ),
                patch("site_publisher.requests.post", return_value=FakeResponse({"success": True, "failed": 0})) as post,
                patch("image_finder.find_cover_image") as external_search,
                patch("image_optimizer.process_and_upload_cover_image") as process_image,
            ):
                result = site_publisher.backfill_missing_cover_images(
                    db_path,
                    limit=1,
                    article_extractor=article_extractor,
                )

            self.assertEqual(result["updated"], 1)
            external_search.assert_not_called()
            process_image.assert_not_called()
            payload = post.call_args.kwargs["json"]
            self.assertEqual(payload["coverImage"], source_image)
            self.assertEqual(payload["sourceUrl"], source_url)

    def test_site_payload_requires_self_hosted_cover(self):
        with self.assertRaisesRegex(RuntimeError, "URL HTTPS"):
            site_publisher.build_site_payload(
                {"source_title": "Bài viết", "editorial_cover_image": {"url": "http://source.example/image.jpg"}},
                {"seo_title": "Bài viết", "seo_content": "<p>Nội dung.</p>"},
            )


if __name__ == "__main__":
    unittest.main()
