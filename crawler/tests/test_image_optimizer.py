import io
import os
import unittest
from unittest.mock import patch

from PIL import Image

from image_optimizer import (
    ImageProcessingError,
    build_vietnamese_alt_text,
    optimize_image_bytes,
    slugify_filename,
    upload_webp_to_vercel_blob,
    _has_watermark_hint,
)


class ImageOptimizerTests(unittest.TestCase):
    def test_filename_is_unaccented_and_hyphenated(self):
        self.assertEqual(
            slugify_filename("Hướng dẫn tối ưu hình ảnh"),
            "huong-dan-toi-uu-hinh-anh",
        )

    def test_cover_alt_falls_back_to_vietnamese_page_context(self):
        alt = build_vietnamese_alt_text(
            {"title": "Aerial view of a bay"},
            {
                "visual_search_title": "Cẩm nang khám phá vịnh Hạ Long",
                "destination_city": "Hạ Long",
                "destination_country": "Việt Nam",
            },
        )
        self.assertIn("Ảnh minh họa", alt)
        self.assertIn("Hạ Long", alt)

    def test_png_is_converted_to_webp_and_resized(self):
        source = io.BytesIO()
        Image.new("RGB", (1600, 900), (35, 120, 190)).save(source, format="PNG")
        result = optimize_image_bytes(
            source.getvalue(),
            max_width=800,
            max_bytes=100 * 1024,
        )
        self.assertLessEqual(result["width"], 800)
        self.assertLessEqual(result["size_bytes"], 100 * 1024)
        with Image.open(io.BytesIO(result["data"])) as output:
            self.assertEqual(output.format, "WEBP")
            self.assertEqual(output.width, result["width"])

    def test_watermark_preview_metadata_is_flagged(self):
        from image_optimizer import _has_watermark_hint
        self.assertTrue(_has_watermark_hint({"title": "Watermarked preview"}, "https://example.com/a.jpg"))
        self.assertFalse(_has_watermark_hint({"title": "Ha Long Bay landscape"}, "https://example.com/a.jpg"))

    def test_upload_uses_authenticated_site_api_not_blob_token(self):
        class FakeResponse:
            ok = True
            status_code = 200

            @staticmethod
            def json():
                return {
                    "ok": True,
                    "url": "https://public.example.blob.vercel-storage.com/images/covers/test-0123456789ab.webp",
                    "pathname": "images/covers/test-0123456789ab.webp",
                }

        image_bytes = b"RIFF0000WEBP"
        filename = "test-0123456789ab.webp"
        with patch.dict(os.environ, {
            "SITE_URL": "https://didaydo.vercel.app",
            "SITE_INGEST_API_KEY": "x" * 32,
        }, clear=False), patch("image_optimizer.requests.post", return_value=FakeResponse()) as post:
            result = upload_webp_to_vercel_blob(image_bytes, filename)

        self.assertTrue(result["url"].startswith("https://"))
        self.assertEqual(result["pathname"], "images/covers/test-0123456789ab.webp")
        self.assertEqual(post.call_args.args[0], "https://didaydo.vercel.app/api/internal/images")
        self.assertEqual(post.call_args.kwargs["data"], image_bytes)
        self.assertEqual(post.call_args.kwargs["headers"]["Content-Type"], "image/webp")
        self.assertIn("Bearer ", post.call_args.kwargs["headers"]["Authorization"])

    def test_invalid_bytes_are_rejected(self):
        with self.assertRaises(ImageProcessingError):
            optimize_image_bytes(b"not-an-image")


    def test_metadata_logo_hint_is_rejected(self):
        self.assertTrue(_has_watermark_hint(
            {"alt": "Travel photo with logo in bottom corner"},
            "https://example.com/photos/travel.jpg",
        ))



if __name__ == "__main__":
    unittest.main()
