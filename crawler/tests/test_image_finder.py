import unittest
from unittest.mock import patch

from image_finder import (
    _license_from_landing_page,
    _article_context_phrases,
    _article_context_terms,
    _best_original_image,
    _rank_candidates,
    is_license_allowed,
)


class ArticleImageRelevanceTests(unittest.TestCase):
    def setUp(self):
        self.article = {
            "source_title": "Bún quậy Kiến Xây ở Phú Quốc: món ăn nên thử",
            "visual_search_title": "Bún quậy Kiến Xây: hương vị đặc trưng Phú Quốc",
            "visual_search_summary": "Tìm hiểu món bún quậy Kiến Xây và cách thưởng thức tại Phú Quốc.",
            "destination_city": "Phú Quốc",
            "destination_country": "Vietnam",
            "primary_category": "food-and-drink",
            "source_images": [
                {
                    "image_id": "IMG_01",
                    "url": "https://source.example/images/bun-quay.jpg",
                    "alt": "Bún quậy Kiến Xây",
                    "caption": "Bún quậy Kiến Xây được phục vụ tại quán",
                    "nearby_heading": "Thưởng thức bún quậy ở Phú Quốc",
                    "placement_source": "article_body",
                },
                {
                    "image_id": "IMG_02",
                    "url": "https://source.example/images/og.jpg",
                    "alt": "Travel guide",
                    "placement_source": "og:image_fallback",
                },
            ],
        }

    def test_original_caption_and_alt_drive_visual_context(self):
        terms = _article_context_terms(self.article)
        phrases = _article_context_phrases(self.article)
        self.assertIn("bun", terms)
        self.assertIn("kien", terms)
        self.assertTrue(any("bun quay kien xay" in phrase for phrase in phrases))

    def test_best_reference_is_an_actual_article_photo_not_og_fallback(self):
        selected = _best_original_image(self.article)
        self.assertIsNotNone(selected)
        self.assertEqual(selected["image_id"], "IMG_01")

    def test_exact_dish_and_destination_match_is_accepted(self):
        candidate = {
            "title": "Bún quậy Kiến Xây, Phú Quốc, Vietnam",
            "description": "Vietnamese food at a local restaurant",
            "tags_text": "food restaurant noodles",
            "width": 1600,
            "visual_reference_match": False,
        }
        ranked = _rank_candidates(
            [candidate],
            ["Phú Quốc"],
            ["Vietnam"],
            ["food", "restaurant", "noodles"],
            require_place=True,
            require_country=True,
            context_terms=_article_context_terms(self.article),
            context_phrases=_article_context_phrases(self.article),
            require_context=True,
        )
        self.assertEqual(len(ranked), 1)

    def test_same_destination_but_wrong_dish_is_rejected(self):
        candidate = {
            "title": "Bánh mì Phú Quốc, Vietnam",
            "description": "Vietnamese food",
            "tags_text": "food restaurant",
            "width": 1600,
        }
        ranked = _rank_candidates(
            [candidate],
            ["Phú Quốc"],
            ["Vietnam"],
            ["food", "restaurant"],
            require_place=True,
            require_country=True,
            context_terms=_article_context_terms(self.article),
            context_phrases=_article_context_phrases(self.article),
            require_context=True,
        )
        self.assertEqual(ranked, [])

    def test_lens_visual_match_can_compensate_for_missing_place_metadata(self):
        candidate = {
            "title": "Bún quậy Kiến Xây",
            "description": "Vietnamese noodle dish",
            "tags_text": "food restaurant",
            "width": 1600,
            "visual_reference_match": True,
        }
        ranked = _rank_candidates(
            [candidate],
            ["Phú Quốc"],
            ["Vietnam"],
            ["food", "restaurant"],
            require_place=True,
            require_country=True,
            context_terms=_article_context_terms(self.article),
            context_phrases=_article_context_phrases(self.article),
            require_context=True,
        )
        self.assertEqual(len(ranked), 1)

    def test_advertising_and_gif_candidates_are_filtered(self):
        from image_finder import _rank_candidates

        candidates = [
            {"url": "https://example.com/ad-banner.jpg", "title": "Beautiful Kyoto temple", "description": "Kyoto temple", "width": 1600},
            {"url": "https://example.com/animated.gif", "title": "Kyoto temple", "description": "Kyoto temple", "width": 1600},
            {"url": "https://example.com/kyoto-temple.jpg", "title": "Kyoto temple", "description": "Historic Kyoto temple", "width": 1600},
        ]
        ranked = _rank_candidates(
            candidates, ["Kyoto"], ["Japan"], ["temple"],
            require_place=True, require_country=True,
            context_terms=["historic", "temple"], require_context=True,
        )
        self.assertEqual([item["url"] for item in ranked], ["https://example.com/kyoto-temple.jpg"])

    def test_generic_travel_copy_does_not_produce_specific_context(self):
        generic = {
            "source_title": "Travel guide",
            "source_summary": "Discover the best travel experiences and places.",
            "primary_category": "travel-guide",
        }
        self.assertEqual(_article_context_terms(generic), [])


    def test_article_author_and_page_license_are_not_photo_rights(self):
        html = """
        <html><head><script type="application/ld+json">
        {
          "@type": "Article",
          "license": "https://creativecommons.org/licenses/by/4.0/",
          "author": {"@type": "Person", "name": "Article Writer"}
        }
        </script></head><body></body></html>
        """

        class FakeResponse:
            status_code = 200
            headers = {"Content-Type": "text/html; charset=utf-8"}
            encoding = "utf-8"

            def iter_content(self, chunk_size=16384):
                yield html.encode("utf-8")

            def close(self):
                return None

        with patch("image_finder._public_https_url", return_value=True), \
             patch("image_finder.requests.get", return_value=FakeResponse()):
            result = _license_from_landing_page("https://example.com/article")
        self.assertIsNone(result)

    def test_imageobject_license_and_creator_are_accepted(self):
        html = """
        <html><head><script type="application/ld+json">
        {
          "@type": "ImageObject",
          "contentUrl": "https://images.example/photo.jpg",
          "license": "https://creativecommons.org/licenses/by/4.0/",
          "creator": {"@type": "Person", "name": "Photo Creator"}
        }
        </script></head><body></body></html>
        """

        class FakeResponse:
            status_code = 200
            headers = {"Content-Type": "text/html; charset=utf-8"}
            encoding = "utf-8"

            def iter_content(self, chunk_size=16384):
                yield html.encode("utf-8")

            def close(self):
                return None

        with patch("image_finder._public_https_url", return_value=True), \
             patch("image_finder.requests.get", return_value=FakeResponse()):
            result = _license_from_landing_page("https://example.com/image")
        self.assertIsNotNone(result)
        self.assertEqual(result["license"], "CC BY 4.0")
        self.assertEqual(result["creator"], "Photo Creator")

    def test_imageobject_cc_by_without_photographer_is_rejected(self):
        html = """
        <html><head><script type="application/ld+json">
        {
          "@type": "ImageObject",
          "license": "https://creativecommons.org/licenses/by/4.0/"
        }
        </script></head><body></body></html>
        """

        class FakeResponse:
            status_code = 200
            headers = {"Content-Type": "text/html; charset=utf-8"}
            encoding = "utf-8"

            def iter_content(self, chunk_size=16384):
                yield html.encode("utf-8")

            def close(self):
                return None

        with patch("image_finder._public_https_url", return_value=True), \
             patch("image_finder.requests.get", return_value=FakeResponse()):
            result = _license_from_landing_page("https://example.com/image")
        self.assertIsNone(result)

    def test_only_commercial_friendly_licenses_are_allowed(self):
        self.assertTrue(is_license_allowed("CC BY 4.0"))
        self.assertFalse(is_license_allowed("CC BY-SA 4.0"))
        self.assertTrue(is_license_allowed("CC0"))
        self.assertFalse(is_license_allowed("CC BY-NC 4.0"))
        self.assertFalse(is_license_allowed("CC BY-ND 4.0"))
        self.assertFalse(is_license_allowed("CC BY-NC 4.0"))



if __name__ == "__main__":
    unittest.main()
