"""Bridge between Travel Content Bot and the Next.js ingest API.

Publishes completed, AI-written articles directly to the website. It requires an
explicitly enabled auto-publish health flag from the deployed website before posting.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

log = logging.getLogger("travel-content-bot.site-publisher")

PROJECT_DIR = Path(__file__).resolve().parent
load_dotenv(PROJECT_DIR / ".env")

SITE_SYNC_ENABLED = os.getenv("SITE_SYNC_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
SITE_URL = os.getenv("SITE_URL", os.getenv("NEXT_PUBLIC_SITE_URL", "")).strip().rstrip("/")
SITE_INGEST_API_KEY = os.getenv("SITE_INGEST_API_KEY", "").strip()
SITE_API_TIMEOUT = max(5, min(int(os.getenv("SITE_API_TIMEOUT_SECONDS", "20")), 60))
SOURCE_IMAGE_REUSE_AUTHORIZED = os.getenv("SOURCE_IMAGE_REUSE_AUTHORIZED", "true").strip().lower() in {"1", "true", "yes", "on"}
DATABASE_PATH = os.getenv("DATABASE_PATH", "data/travel_content.db").strip() or "data/travel_content.db"
if not os.path.isabs(DATABASE_PATH):
    DATABASE_PATH = str(PROJECT_DIR / DATABASE_PATH)

_HEALTH_CHECKED = False


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def clean(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        value = " ".join(clean(x) for x in value if x is not None)
    elif isinstance(value, dict):
        value = value.get("name") or value.get("text") or value.get("value") or json.dumps(value, ensure_ascii=False)
    else:
        value = str(value)
    return re.sub(r"\s+", " ", value).strip()


def normalize_source_url(url: str) -> str:
    value = clean(url)
    parsed = urlparse(value)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return value
    host = parsed.hostname.lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    if path != "/":
        path = path.rstrip("/")
    return parsed._replace(scheme="https", netloc=host, path=path or "/", params="", query="", fragment="").geturl()


def _enabled() -> bool:
    return SITE_SYNC_ENABLED and bool(SITE_URL) and bool(SITE_INGEST_API_KEY)


def ensure_table(db_path: str | None = None) -> None:
    target = db_path or DATABASE_PATH
    os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
    with sqlite3.connect(target, timeout=30) as conn:
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS website_sync (
                source_url TEXT PRIMARY KEY,
                site_post_id TEXT,
                site_slug TEXT,
                site_status TEXT NOT NULL DEFAULT 'pending',
                site_url TEXT,
                last_synced_at TEXT,
                last_checked_at TEXT,
                local_cleanup_done INTEGER NOT NULL DEFAULT 0,
                sync_error TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_website_sync_status ON website_sync(site_status, last_synced_at)")
        conn.commit()


def _record_sync(
    db_path: str,
    source_url: str,
    *,
    post_id: str | int | None = None,
    slug: str | None = None,
    status: str = "pending",
    site_url: str | None = None,
    error: str | None = None,
) -> None:
    """Persist the latest website sync outcome without discarding known remote IDs."""
    target = db_path or DATABASE_PATH
    canonical_url = normalize_source_url(source_url)
    if not canonical_url:
        raise ValueError("Không thể ghi trạng thái đồng bộ khi thiếu source_url.")

    ensure_table(target)
    values = (
        canonical_url,
        clean(post_id) or None,
        clean(slug) or None,
        clean(status).lower() or "pending",
        clean(site_url) or None,
        now_iso(),
        clean(error) or None,
    )
    with sqlite3.connect(target, timeout=30) as conn:
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute(
            """
            INSERT INTO website_sync (
                source_url, site_post_id, site_slug, site_status,
                site_url, last_synced_at, sync_error
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_url) DO UPDATE SET
                site_post_id = COALESCE(excluded.site_post_id, website_sync.site_post_id),
                site_slug = COALESCE(excluded.site_slug, website_sync.site_slug),
                site_status = excluded.site_status,
                site_url = COALESCE(excluded.site_url, website_sync.site_url),
                last_synced_at = excluded.last_synced_at,
                sync_error = excluded.sync_error
            """,
            values,
        )
        conn.commit()


def _endpoint(path: str = "") -> str:
    return f"{SITE_URL}/api/ingest/posts{path}"


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {SITE_INGEST_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "TravelContentBot/1.0",
    }


def _check_api_ready() -> None:
    global _HEALTH_CHECKED
    if _HEALTH_CHECKED:
        return
    if not SITE_URL or not SITE_URL.startswith(("http://", "https://")):
        raise RuntimeError("SITE_URL phải là URL http:// hoặc https:// của website.")
    if not SITE_INGEST_API_KEY or len(SITE_INGEST_API_KEY) < 24:
        raise RuntimeError("SITE_INGEST_API_KEY chưa hợp lệ hoặc ngắn hơn 24 ký tự.")
    try:
        response = requests.get(
            _endpoint(), params={"health": "1"}, headers=_headers(),
            timeout=(5, SITE_API_TIMEOUT),
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"Không kết nối được website API ({type(exc).__name__}). Kiểm tra SITE_URL và website đang chạy.") from None
    try:
        data = response.json()
    except ValueError:
        data = {}
    if (
        not response.ok
        or not data.get("ok")
        or data.get("feature") != "auto-publish-ingest-v2"
        or data.get("autoPublishEnabled") is not True
    ):
        raise RuntimeError(
            "Website API chưa xác nhận chế độ tự xuất bản. Hãy cập nhật route.ts, "
            "đặt INGEST_AUTO_PUBLISH=true trên Vercel và redeploy trước khi chạy crawler."
        )
    _HEALTH_CHECKED = True


def _parse_list(value) -> list[str]:
    if isinstance(value, list):
        items = value
    elif isinstance(value, str):
        try:
            parsed = json.loads(value)
            items = parsed if isinstance(parsed, list) else re.split(r"[,;\n]", value)
        except json.JSONDecodeError:
            items = re.split(r"[,;\n]", value)
    else:
        items = []
    output, seen = [], set()
    for item in items:
        text = clean(item)
        if text and text.casefold() not in seen:
            output.append(text)
            seen.add(text.casefold())
    return output


def _category_for(article: dict) -> str:
    """Map the crawler's canonical topic slug to an existing public editorial category.

    Geography (country/city) is stored separately; it must not override article topic.
    """
    primary = clean(article.get("primary_category")).casefold()
    topic_map = {
        "travel-guide": "Cẩm nang",
        "travel-tips": "Kinh nghiệm du lịch",
        "things-to-do": "Check-in",
        "food-and-drink": "Ẩm thực",
        "hotel-review": "Hotel review",
        "itinerary": "Lịch trình",
        "transport": "Di chuyển",
        "culture-local-life": "Văn hóa & địa phương",
        "budget-travel": "Chi phí & ngân sách",
        "destination-news": "Tin du lịch",
        "outdoor-adventure": "Điểm đến",
        "family-travel": "Kinh nghiệm du lịch",
        "sustainable-travel": "Văn hóa & địa phương",
        "luxury-travel": "Hotel review",
        "beach-island": "Check-in",
    }
    if primary in topic_map:
        return topic_map[primary]

    for topic in _parse_list(article.get("topic_categories")):
        mapped = topic_map.get(clean(topic).casefold())
        if mapped:
            return mapped

    top = clean(article.get("top_level_section") or "")
    top_map = {
        "Thế giới": "Điểm đến",
        "Cẩm nang": "Cẩm nang",
        "Ẩm thực": "Ẩm thực",
        "Khách sạn & lưu trú": "Hotel review",
        "Khách sạn & Resort": "Hotel review",
        "Điểm check-in": "Check-in",
        "Lịch trình": "Lịch trình",
        "Kinh nghiệm du lịch": "Kinh nghiệm du lịch",
    }
    if top in top_map:
        return top_map[top]

    country = clean(article.get("destination_country") or "").casefold()
    if country and country not in {"world / chưa phân loại", "world", "chưa phân loại"}:
        return "Điểm đến"
    return "Cẩm nang"


def _image_candidates(article: dict) -> list[dict]:
    images = article.get("source_images")
    if not isinstance(images, list):
        raw = article.get("source_images_json")
        try:
            images = json.loads(raw) if raw else []
        except (TypeError, json.JSONDecodeError):
            images = []
    return [image for image in images if isinstance(image, dict) and clean(image.get("url")).startswith("https://")]



def _stored_image_list(article: dict) -> list[dict]:
    images = article.get("source_images")
    if not isinstance(images, list):
        try:
            images = json.loads(article.get("source_images_json") or "[]")
        except (TypeError, json.JSONDecodeError):
            images = []
    return [item for item in images if isinstance(item, dict)]


def build_site_payload(article: dict, draft: dict) -> dict:
    """Build the exact payload accepted by the website's authenticated ingest route."""
    cover = article.get("editorial_cover_image")
    cover_url = clean(cover.get("url")) if isinstance(cover, dict) else ""
    if not cover_url.startswith("https://"):
        raise RuntimeError("Ảnh đại diện phải có URL HTTPS hợp lệ trước khi xuất bản.")

    title = clean(draft.get("seo_title") or article.get("source_title"))
    content_html = str(draft.get("seo_content") or "").strip()
    if len(title) < 3 or not content_html:
        raise RuntimeError("Bài viết chưa có tiêu đề hoặc nội dung HTML hợp lệ.")

    tags = []
    for value in (
        draft.get("primary_keyword"),
        draft.get("secondary_keywords"),
        article.get("rss_categories"),
        article.get("topic_categories"),
        article.get("destination_city"),
    ):
        for item in _parse_list(value):
            candidate = clean(item)[:80]
            if candidate and candidate.casefold() not in {tag.casefold() for tag in tags}:
                tags.append(candidate)
            if len(tags) >= 20:
                break
        if len(tags) >= 20:
            break

    excerpt = clean(
        draft.get("meta_description")
        or draft.get("seo_description")
        or article.get("source_summary")
    )[:500]
    seo_description = clean(
        draft.get("meta_description")
        or draft.get("seo_description")
        or excerpt
    )[:320]
    return {
        "title": title[:220],
        "excerpt": excerpt,
        "contentHtml": content_html[:500000],
        "coverImage": cover_url,
        "coverAlt": clean(cover.get("alt") or title)[:300],
        "country": clean(article.get("destination_country"))[:120],
        "destination": clean(article.get("destination_city") or article.get("destination"))[:120],
        "category": _category_for(article),
        "tags": tags,
        "status": "published",
        "featured": False,
        "authorName": "Ban biên tập",
        "sourceUrl": normalize_source_url(article.get("source_url", "")),
        "sourceName": clean(
            article.get("source_name")
            or article.get("source_publisher")
            or article.get("source_domain")
        )[:200],
        "seoTitle": title[:220],
        "seoDescription": seo_description,
    }


def _normalize_source_image_url(value: str, base_url: str = "") -> str:
    """Normalize an extracted image URL without downloading, rewriting paths, or losing CDN query tokens."""
    raw = clean(value)
    if not raw or raw.startswith(("data:", "blob:", "javascript:")):
        return ""
    if raw.startswith("//"):
        raw = "https:" + raw
    elif base_url:
        raw = urljoin(base_url, raw)

    parsed = urlparse(raw)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return ""
    if parsed.username or parsed.password:
        return ""
    # The public site only accepts HTTPS image URLs. Preserve host, path and
    # query string because some image CDNs use signed URLs.
    return parsed._replace(scheme="https", fragment="").geturl()


def _persist_source_image_metadata(article: dict, db_path: str, images: list[dict]) -> None:
    source_url = normalize_source_url(article.get("source_url", ""))
    if not source_url:
        return
    try:
        with sqlite3.connect(db_path, timeout=30) as conn:
            conn.execute(
                "UPDATE articles SET source_images_json=?, updated_at=? WHERE source_url=?",
                (json.dumps(images, ensure_ascii=False), now_iso(), source_url),
            )
            conn.commit()
    except sqlite3.Error as exc:
        log.debug("Không cập nhật được metadata ảnh nguồn (%s)", type(exc).__name__)


def _ensure_source_article_images(
    article: dict,
    db_path: str,
    draft: dict | None = None,
) -> dict | None:
    """Use the article's own image URLs directly; search external images only when none exist.

    Source photos are not downloaded, sent to vision models, cropped, re-encoded,
    or uploaded. Only their URL scheme and descriptive metadata are normalized.
    """
    from image_finder import find_cover_image
    from image_optimizer import build_vietnamese_alt_text

    source_url = normalize_source_url(article.get("source_url", ""))
    stored_images = _stored_image_list(article)
    if not stored_images and source_url:
        try:
            with sqlite3.connect(db_path, timeout=30) as conn:
                row = conn.execute(
                    "SELECT source_images_json FROM articles WHERE source_url=?",
                    (source_url,),
                ).fetchone()
            if row and row[0]:
                decoded = json.loads(row[0])
                if isinstance(decoded, list):
                    stored_images = [item for item in decoded if isinstance(item, dict)]
        except (sqlite3.Error, TypeError, json.JSONDecodeError):
            log.debug("Không đọc được metadata ảnh nguồn cho %s", source_url)

    body_images = [
        item for item in stored_images
        if item.get("placement_source") == "article_body"
    ]
    fallback_images = [
        item for item in stored_images
        if item.get("placement_source") in {"og:image_fallback", "rss_image_fallback"}
    ]
    candidates = body_images or fallback_images

    source_name = clean(
        article.get("source_name")
        or article.get("source_publisher")
        or article.get("source_domain")
        or (urlparse(source_url).hostname if source_url else "")
        or "Bài viết nguồn"
    )
    search_article = dict(article)
    if isinstance(draft, dict):
        search_article["visual_search_title"] = clean(
            draft.get("seo_title") or article.get("source_title")
        )
        search_article["visual_search_summary"] = clean(
            draft.get("meta_description")
            or draft.get("seo_description")
            or article.get("source_summary")
        )

    # Fast path: keep the original source image URL. No image network request,
    # image decode, AI vision call, crop/inpaint, WebP encode, or Blob upload.
    # Do not add image inspection here; it would reintroduce the per-photo bottleneck.
    source_images: list[dict] = []
    by_original_url: dict[str, dict] = {}
    raw_source_urls: set[str] = set()
    try:
        max_images = max(1, min(int(os.getenv("SOURCE_ARTICLE_MAX_IMAGES", "8")), 12))
    except ValueError:
        max_images = 8

    ordered = sorted(
        candidates,
        key=lambda item: (
            int(item.get("position_index") or 9999),
            clean(item.get("image_id")),
        ),
    )
    for index, image in enumerate(ordered[:max_images], start=1):
        candidate = dict(image)
        raw_url = clean(candidate.get("original_url") or candidate.get("url"))
        if raw_url:
            raw_source_urls.add(raw_url)
        image_url = _normalize_source_image_url(raw_url, source_url)
        if not image_url:
            log.debug("Bỏ URL ảnh nguồn không hợp lệ: image_id=%s", candidate.get("image_id"))
            continue

        candidate["original_url"] = raw_url or image_url
        candidate["url"] = image_url
        candidate["image_id"] = clean(candidate.get("image_id")) or f"IMG_{index:02d}"
        candidate["source_name"] = clean(candidate.get("source_name") or source_name)
        candidate["source_page_url"] = clean(candidate.get("source_page_url") or source_url)
        candidate["alt"] = build_vietnamese_alt_text(candidate, search_article)
        candidate["rights_status"] = "operator_authorized_all_configured_sources"
        candidate["asset_storage"] = "source_remote"
        candidate["processed_format"] = "original"
        candidate["is_cover"] = False

        source_images.append(candidate)
        by_original_url[raw_url] = candidate
        by_original_url[image_url] = candidate

    if source_images:
        selected_cover = dict(source_images[0])
        selected_cover["is_cover"] = True
        selected_cover["cover_role"] = "article_source_cover"
        article["editorial_cover_image"] = selected_cover
        article["source_image_url"] = selected_cover["url"]
        article["image_credit"] = clean(selected_cover.get("credit") or source_name)

        if isinstance(draft, dict):
            soup = BeautifulSoup(str(draft.get("seo_content") or ""), "html.parser")
            for image_tag in list(soup.find_all("img")):
                raw_src = clean(image_tag.get("src"))
                image = by_original_url.get(raw_src)
                if image is None:
                    normalized_src = _normalize_source_image_url(raw_src, source_url)
                    image = by_original_url.get(normalized_src)
                if image:
                    image_tag["src"] = image["url"]
                    image_tag["alt"] = clean(image.get("alt") or image_tag.get("alt") or article.get("source_title"))[:300]
                    image_tag["loading"] = "lazy"
                    image_tag["decoding"] = "async"
                    # Image rights/source metadata stays in the crawler's private
                    # state only. Never publish attribution text below an image.
                    figure = image_tag.find_parent("figure")
                    caption = figure.find("figcaption") if figure else None
                    if caption:
                        caption_text = clean(caption.get_text(" ", strip=True)).casefold()
                        attribution_markers = (
                            "nguồn ảnh", "giấy phép", "ảnh:", "photo by",
                            "image credit", "credit:", "courtesy of",
                        )
                        if any(marker in caption_text for marker in attribution_markers):
                            caption.decompose()
                    # Use one stable original URL instead of asking the browser
                    # to choose a potentially stale srcset candidate.
                    image_tag.attrs.pop("srcset", None)
                    image_tag.attrs.pop("sizes", None)
                elif raw_src in raw_source_urls:
                    parent = image_tag.parent
                    image_tag.decompose()
                    if parent and parent.name == "figure" and not parent.find("img"):
                        parent.decompose()
            draft["seo_content"] = "".join(str(child) for child in soup.contents)

        article["source_images"] = source_images
        article["source_images_json"] = json.dumps(source_images, ensure_ascii=False)
        _persist_source_image_metadata(article, db_path, source_images)
        log.info(
            "Ảnh bài nguồn được tái sử dụng trực tiếp: %s ảnh; không tải lại hoặc xử lý ảnh.",
            len(source_images),
        )
        return selected_cover

    # Only reach the external image providers when the source article (including
    # OG/RSS image fallback) contains no usable image URL.
    external = find_cover_image(search_article)
    if not isinstance(external, dict):
        log.warning("Bài nguồn không có ảnh và không tìm được ảnh ngoài phù hợp: %s", source_url)
        return None

    external = dict(external)
    external_url = _normalize_source_image_url(external.get("url"), external.get("source_page_url") or source_url)
    if not external_url:
        log.warning("Ảnh ngoài trả về URL không hợp lệ: %s", source_url)
        return None

    external["original_url"] = clean(external.get("url"))
    external["url"] = external_url
    external["alt"] = build_vietnamese_alt_text(external, search_article)
    external["source_name"] = clean(external.get("provider") or external.get("source_name") or "Kho ảnh mở")
    external["source_page_url"] = clean(external.get("source_page_url") or source_url)
    external["is_cover"] = True
    external["cover_role"] = "external_fallback_cover"
    external["asset_storage"] = "external_source"
    external["processed_format"] = "original"
    article["editorial_cover_image"] = external
    article["source_image_url"] = external_url
    article["image_credit"] = clean(external.get("creator") or external.get("credit") or external["source_name"])

    log.info(
        "Bài nguồn không có ảnh; dùng ảnh ngoài có metadata giấy phép: provider=%s",
        external["source_name"],
    )
    return external


def _ensure_editorial_cover_image(
    article: dict,
    db_path: str,
    draft: dict | None = None,
) -> dict | None:
    """Compatibility wrapper; use the source-first, metadata-only image path."""
    return _ensure_source_article_images(article, db_path, draft=draft)


def backfill_missing_cover_images(
    db_path: str | None = None,
    limit: int = 5,
    article_extractor=None,
) -> dict:
    """Fill old missing covers with source photos first, external licensed photos second."""
    if not SITE_SYNC_ENABLED or not SITE_URL or not SITE_INGEST_API_KEY:
        return {"checked": 0, "updated": 0, "unmatched": 0, "failed": 0, "skipped": True}

    target_db = db_path or DATABASE_PATH
    _check_api_ready()
    maximum = max(1, min(int(limit), 25))
    try:
        response = requests.get(
            _endpoint(),
            params={"missingCover": "1", "limit": maximum},
            headers=_headers(),
            timeout=(5, SITE_API_TIMEOUT),
        )
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError) as exc:
        log.warning("Không tải được danh sách bài thiếu ảnh để bù ảnh (%s)", type(exc).__name__)
        return {"checked": 0, "updated": 0, "unmatched": 0, "failed": 1, "error": type(exc).__name__}

    posts = data.get("posts") if isinstance(data, dict) else []
    if not isinstance(posts, list):
        posts = []

    category_map = {
        "cẩm nang": "travel-guide",
        "kinh nghiệm du lịch": "travel-tips",
        "điểm đến": "travel-guide",
        "check-in": "things-to-do",
        "ẩm thực": "food-and-drink",
        "hotel review": "hotel-review",
        "lịch trình": "itinerary",
        "di chuyển": "transport",
        "văn hóa & địa phương": "culture-local-life",
        "chi phí & ngân sách": "budget-travel",
        "tin du lịch": "destination-news",
    }
    result = {"checked": len(posts), "updated": 0, "unmatched": 0, "failed": 0, "items": []}

    for post in posts:
        source_url = normalize_source_url(clean(post.get("source_url")))
        title = clean(post.get("title"))
        if not source_url or not title:
            result["failed"] += 1
            continue

        category_name = clean(post.get("category_name")).casefold()
        article = {
            "source_url": source_url,
            "source_title": title,
            "source_name": clean(post.get("source_name")),
            "source_summary": clean(post.get("excerpt")),
            "visual_search_title": clean(post.get("seo_title") or title),
            "visual_search_summary": clean(post.get("seo_description") or post.get("excerpt")),
            "destination_country": clean(post.get("country_name")),
            "destination_city": clean(post.get("destination_name")),
            "primary_category": category_map.get(category_name, "travel-guide"),
            "topic_categories": [category_map.get(category_name, "travel-guide")],
        }

        # Older posts may not have source_images in the local SQLite cache.
        # Re-read only the page metadata/image tags; don't download image files.
        if article_extractor is not None:
            host = urlparse(source_url).hostname or ""
            item = {
                "source_url": source_url,
                "rss_title": title,
                "rss_summary": clean(post.get("excerpt")),
                "rss_published_at": "",
                "rss_categories": [clean(post.get("category_name"))],
                "rss_image_url": "",
                "source_id": "",
                "source_name": clean(post.get("source_name")),
                "source_homepage": f"https://{host}" if host else "",
                "source_domain": host,
                "source_language": "vi",
                "source_focus": [category_map.get(category_name, "travel-guide")],
                "allowed_domains": [host] if host else [],
                "permission_status": "operator_authorized_all_configured_sources",
            }
            try:
                extracted = article_extractor(item)
                if isinstance(extracted, dict):
                    article.update(extracted)
            except Exception as exc:
                log.info(
                    "Không lấy được metadata ảnh bài cũ; sẽ dùng ảnh ngoài nếu cache cũng trống (%s).",
                    type(exc).__name__,
                )

            # Keep the website's canonical metadata as the source of truth.
            article["source_url"] = source_url
            article["source_title"] = title
            article["source_name"] = clean(post.get("source_name") or article.get("source_name"))
            article["source_summary"] = clean(post.get("excerpt") or article.get("source_summary"))
            article["destination_country"] = clean(post.get("country_name") or article.get("destination_country"))
            article["destination_city"] = clean(post.get("destination_name") or article.get("destination_city"))
            article["primary_category"] = category_map.get(category_name, article.get("primary_category") or "travel-guide")
            article["topic_categories"] = [article["primary_category"]]

        draft = {
            "seo_title": clean(post.get("seo_title") or title),
            "meta_description": clean(post.get("seo_description") or post.get("excerpt")),
            "seo_content": "",
        }
        try:
            cover = _ensure_source_article_images(article, target_db, draft=draft)
            if not cover:
                result["unmatched"] += 1
                result["items"].append({"title": title[:160], "status": "no_source_or_external_image"})
                continue

            payload = {
                "title": title,
                "excerpt": clean(post.get("excerpt")),
                "coverImage": clean(cover.get("url")),
                "coverAlt": clean(cover.get("alt") or title)[:300],
                "country": clean(post.get("country_name")),
                "destination": clean(post.get("destination_name")),
                "category": clean(post.get("category_name")) or "Cẩm nang",
                "tags": post.get("tags") if isinstance(post.get("tags"), list) else [],
                "authorName": "Ban biên tập",
                "sourceUrl": source_url,
                "sourceName": clean(post.get("source_name")),
                "seoTitle": clean(post.get("seo_title") or title),
                "seoDescription": clean(post.get("seo_description") or post.get("excerpt")),
                "status": "published",
            }
            if not payload["coverImage"].startswith("https://"):
                raise ValueError("Ảnh bù phải dùng URL HTTPS.")

            update_response = requests.post(
                _endpoint(), headers=_headers(), json=payload,
                timeout=(8, SITE_API_TIMEOUT),
            )
            update_response.raise_for_status()
            update_data = update_response.json()
            if not update_data.get("success") or int(update_data.get("failed", 0) or 0) > 0:
                raise RuntimeError("Website từ chối cập nhật ảnh đại diện.")
            result["updated"] += 1
            result["items"].append({
                "title": title[:160],
                "status": "updated",
                "provider": cover.get("source_name") or cover.get("provider"),
                "image_url": payload["coverImage"],
                "image_origin": cover.get("cover_role") or cover.get("placement_source"),
            })
            log.info(
                "Đã bù ảnh cho bài cũ bằng URL trực tiếp: title=%s origin=%s",
                title[:120],
                cover.get("cover_role") or cover.get("placement_source"),
            )
        except Exception as exc:
            result["failed"] += 1
            result["items"].append({"title": title[:160], "status": "failed", "error": type(exc).__name__})
            log.warning("Không bổ sung được ảnh cho bài cũ '%s' (%s)", title[:100], type(exc).__name__)

    return result


def recheck_published_cover_images(
    db_path: str | None = None,
    limit: int = 3,
    article_extractor=None,
) -> dict:
    """Review a small batch of old published covers against their original article photos."""
    if not SITE_SYNC_ENABLED or not SITE_URL or not SITE_INGEST_API_KEY:
        return {"checked": 0, "updated": 0, "unmatched": 0, "failed": 0, "skipped": True}
    if article_extractor is None:
        raise ValueError("An article_extractor callback is required for safe source-page inspection.")

    _check_api_ready()
    maximum = max(1, min(int(limit), 10))
    try:
        response = requests.get(
            _endpoint(),
            params={"recheckCovers": "1", "limit": maximum},
            headers=_headers(),
            timeout=(5, SITE_API_TIMEOUT),
        )
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError) as exc:
        log.warning("Không tải được danh sách ảnh cần rà soát (%s)", type(exc).__name__)
        return {"checked": 0, "updated": 0, "unmatched": 0, "failed": 1, "error": type(exc).__name__}

    posts = data.get("posts") if isinstance(data, dict) else []
    if not isinstance(posts, list):
        posts = []

    category_map = {
        "cẩm nang": "travel-guide",
        "kinh nghiệm du lịch": "travel-tips",
        "điểm đến": "travel-guide",
        "check-in": "things-to-do",
        "ẩm thực": "food-and-drink",
        "hotel review": "hotel-review",
        "lịch trình": "itinerary",
        "di chuyển": "transport",
        "văn hóa & địa phương": "culture-local-life",
        "chi phí & ngân sách": "budget-travel",
        "tin du lịch": "destination-news",
    }
    result = {"checked": len(posts), "updated": 0, "unmatched": 0, "failed": 0, "items": []}

    for post in posts:
        source_url = normalize_source_url(clean(post.get("source_url")))
        title = clean(post.get("title"))
        if not source_url or not title:
            result["failed"] += 1
            continue
        host = urlparse(source_url).hostname or ""
        item = {
            "source_url": source_url,
            "rss_title": title,
            "rss_summary": clean(post.get("excerpt")),
            "rss_published_at": "",
            "rss_categories": [clean(post.get("category_name"))],
            "rss_image_url": "",
            "source_id": "",
            "source_name": clean(post.get("source_name")),
            "source_homepage": f"https://{host}" if host else "",
            "source_domain": host,
            "source_language": "vi",
            "source_focus": [category_map.get(clean(post.get("category_name")).casefold(), "travel-guide")],
            "allowed_domains": [host] if host else [],
            "permission_status": "review_terms_before_commercial_reuse",
        }
        try:
            # Re-fetch the original page to capture its real images, captions and nearby headings.
            article = article_extractor(item)
            article["source_url"] = source_url
            article["source_title"] = title
            article["source_summary"] = clean(post.get("excerpt"))
            article["destination_country"] = clean(post.get("country_name")) or article.get("destination_country") or ""
            article["destination_city"] = clean(post.get("destination_name")) or article.get("destination_city") or ""
            category_name = clean(post.get("category_name")).casefold()
            article["primary_category"] = category_map.get(category_name, article.get("primary_category") or "travel-guide")
            article["topic_categories"] = [article["primary_category"]]
            article["top_level_section"] = {
                "điểm đến": "Thế giới",
                "hotel review": "Khách sạn & lưu trú",
                "check-in": "Điểm check-in",
            }.get(category_name, clean(post.get("category_name")) or "Cẩm nang")
            article["destination_countries"] = [article["destination_country"]] if article["destination_country"] else []
            article["source_name"] = clean(post.get("source_name")) or article.get("source_name")
            article["visual_search_title"] = clean(post.get("seo_title") or title)
            article["visual_search_summary"] = clean(post.get("seo_description") or post.get("excerpt"))
            draft = {
                "seo_title": clean(post.get("seo_title") or title),
                "seo_description": clean(post.get("seo_description") or post.get("excerpt")),
                "seo_content": clean(post.get("content_html")),
            }
            old_url = clean(post.get("cover_image"))
            selected_cover = _ensure_editorial_cover_image(article, db_path or DATABASE_PATH, draft=draft)
            if not selected_cover:
                result["unmatched"] += 1
                result["items"].append({"title": title[:160], "status": "no_relevant_licensed_match"})
                continue
            if clean(selected_cover.get("url")) == old_url:
                result["items"].append({"title": title[:160], "status": "already_matching"})
                continue

            payload = build_site_payload(article, draft)
            payload["status"] = "published"
            update_response = requests.post(
                _endpoint(), headers=_headers(), json=payload, timeout=(8, SITE_API_TIMEOUT)
            )
            try:
                update_data = update_response.json()
            except ValueError:
                update_data = {}
            if not update_response.ok or not update_data.get("success") or int(update_data.get("failed", 0) or 0) > 0:
                raise RuntimeError(clean(update_data.get("error") or update_response.reason or "API update failed")[:300])

            result["updated"] += 1
            result["items"].append({
                "title": title[:160],
                "status": "updated",
                "provider": selected_cover.get("source_name"),
                "scope": selected_cover.get("image_scope"),
            })
            log.info("Đã thay ảnh bài cũ bằng ảnh khớp đề tài hơn: %s | %s", title[:100], selected_cover.get("source_name"))
        except Exception as exc:
            result["failed"] += 1
            result["items"].append({"title": title[:160], "status": "failed", "error": type(exc).__name__})
            log.warning("Không rà được ảnh bài cũ '%s' (%s)", title[:100], type(exc).__name__)

    return result


def sync_draft_to_site(article: dict, draft: dict, db_path: str | None = None, force: bool = False) -> dict:
    """Idempotently send one complete AI article to the website for publication."""
    if not SITE_SYNC_ENABLED:
        return {"ok": True, "skipped": True, "reason": "SITE_SYNC_ENABLED=false"}
    if not SITE_URL or not SITE_INGEST_API_KEY:
        raise RuntimeError("SITE_SYNC_ENABLED=true nhưng thiếu SITE_URL hoặc SITE_INGEST_API_KEY trong crawler .env.")
    target_db = db_path or DATABASE_PATH
    ensure_table(target_db)
    source_url = normalize_source_url(article.get("source_url", ""))
    if not source_url:
        raise ValueError("Thiếu URL nguồn ổn định; không thể đồng bộ chống trùng.")

    with sqlite3.connect(target_db, timeout=30) as conn:
        conn.row_factory = sqlite3.Row
        existing = conn.execute("SELECT * FROM website_sync WHERE source_url=?", (source_url,)).fetchone()
    if existing and existing["site_status"] == "published":
        return {"ok": True, "skipped": True, "status": "published", "slug": existing["site_slug"], "site_url": existing["site_url"]}
    _check_api_ready()
    # Preflight by source URL handles the case where POST succeeded remotely but the
    # client lost the response. Never overwrite a live/published post by retrying.
    try:
        status_response = requests.get(_endpoint(), params={"sourceUrl": source_url}, headers=_headers(), timeout=(5, SITE_API_TIMEOUT))
        status_response.raise_for_status()
        remote_data = status_response.json()
    except requests.RequestException as exc:
        raise RuntimeError(f"Không kiểm tra được bài trên website trước khi ghi ({type(exc).__name__}); dừng để tránh tạo trùng.") from None
    except ValueError:
        raise RuntimeError("Website status API không trả JSON hợp lệ; dừng đồng bộ an toàn.") from None
    remote_post = remote_data.get("post") if remote_data.get("found") else None
    if isinstance(remote_post, dict):
        remote_status = clean(remote_post.get("status")).lower()
        remote_slug = clean(remote_post.get("slug"))
        remote_id = remote_post.get("id")
        remote_url = f"{SITE_URL}/bai-viet/{remote_slug}" if remote_slug else None
        if remote_status == "published":
            _record_sync(target_db, source_url, post_id=remote_id, slug=remote_slug, status="published", site_url=remote_url)
            return {"ok": True, "skipped": True, "status": "published", "slug": remote_slug, "site_url": remote_url}
        if remote_status == "archived":
            _record_sync(target_db, source_url, post_id=remote_id, slug=remote_slug, status="archived", site_url=remote_url)
            return {"ok": True, "skipped": True, "status": "archived", "slug": remote_slug, "site_url": remote_url}
        # If a previous run left this source as draft, explicitly retry with
        # status=published. The API only promotes a draft when its auto-publish
        # switch is enabled and the authenticated client requests publication.

    try:
        selected_cover = _ensure_source_article_images(article, target_db, draft=draft)
        if not selected_cover:
            raise RuntimeError("Bài nguồn không có ảnh hợp lệ và cũng không tìm được ảnh ngoài phù hợp; bài được giữ lại.")
        payload = build_site_payload(article, draft)
    except Exception as exc:
        _record_sync(target_db, source_url, status="failed", error=f"Cover image: {type(exc).__name__}: {clean(exc)[:700]}")
        raise

    try:
        response = requests.post(_endpoint(), headers=_headers(), json=payload, timeout=(8, SITE_API_TIMEOUT))
    except requests.RequestException as exc:
        _record_sync(target_db, source_url, status="failed", error=f"HTTP request failed: {type(exc).__name__}")
        raise RuntimeError(f"Không gọi được API nhận bài website ({type(exc).__name__}).") from None

    try:
        data = response.json()
    except ValueError:
        data = {}
    if not response.ok or not data.get("success") or int(data.get("failed", 0) or 0) > 0:
        message = clean(data.get("error") or data.get("details") or data.get("results") or response.reason or "API trả lỗi")
        _record_sync(target_db, source_url, status="failed", error=f"HTTP {response.status_code}: {message[:700]}")
        raise RuntimeError(f"Website ingest API lỗi HTTP {response.status_code}: {message[:400]}")

    results = data.get("results") or []
    result = results[0] if results and isinstance(results[0], dict) else {}
    status = clean(result.get("status") or "draft").lower()
    post_id = result.get("id")
    slug = clean(result.get("slug"))
    post_url = f"{SITE_URL}/bai-viet/{slug}" if slug else None
    _record_sync(target_db, source_url, post_id=post_id, slug=slug, status=status, site_url=post_url)

    if status != "published":
        # Do not mark this as a completed sync; a later run must be able to retry.
        _record_sync(target_db, source_url, post_id=post_id, slug=slug, status="failed", site_url=post_url, error=f"Expected published; API returned {status!r}")
        raise RuntimeError(
            f"Website API trả status={status!r}, chưa xuất bản bài. Kiểm tra INGEST_AUTO_PUBLISH trên Vercel; output local được giữ nguyên."
        )
    return {"ok": True, "created": result.get("action") == "created", "action": result.get("action"), "status": status, "id": post_id, "slug": slug, "site_url": post_url}


def reconcile_published_posts(db_path: str | None = None, mark_published_callback=None, check_limit: int = 30) -> list[dict]:
    """Poll website drafts; once admin publishes one, record status and invoke safe cleanup."""
    if not SITE_SYNC_ENABLED or not SITE_URL or not SITE_INGEST_API_KEY:
        return []
    target_db = db_path or DATABASE_PATH
    ensure_table(target_db)
    _check_api_ready()
    with sqlite3.connect(target_db, timeout=30) as conn:
        conn.row_factory = sqlite3.Row
        pending = conn.execute("""
            SELECT s.source_url, s.site_post_id, s.site_slug, s.site_url
            FROM website_sync s
            WHERE s.site_status='draft'
            ORDER BY COALESCE(s.last_checked_at, s.last_synced_at) ASC
            LIMIT ?
        """, (max(1, min(int(check_limit), 100)),)).fetchall()

    for row in pending:
        source_url = row["source_url"]
        try:
            response = requests.get(_endpoint(), params={"sourceUrl": source_url}, headers=_headers(), timeout=(5, SITE_API_TIMEOUT))
            response.raise_for_status()
            data = response.json()
            post = data.get("post") if data.get("found") else None
            now = now_iso()
            if isinstance(post, dict) and clean(post.get("status")).lower() in {"published", "archived", "draft"}:
                status = clean(post.get("status")).lower()
                slug = clean(post.get("slug") or row["site_slug"])
                post_id = post.get("id") or row["site_post_id"]
                url = f"{SITE_URL}/bai-viet/{slug}" if slug else row["site_url"]
                with sqlite3.connect(target_db, timeout=30) as conn:
                    conn.execute("UPDATE website_sync SET site_post_id=?, site_slug=?, site_status=?, site_url=?, last_checked_at=?, sync_error=NULL WHERE source_url=?",
                                 (str(post_id) if post_id else None, slug, status, url, now, source_url))
                    conn.commit()
            else:
                with sqlite3.connect(target_db, timeout=30) as conn:
                    conn.execute("UPDATE website_sync SET last_checked_at=?, sync_error=? WHERE source_url=?",
                                 (now, "Bản ghi chưa tìm thấy trên website; giữ nguyên để kiểm tra lại." if not data.get("found") else None, source_url))
                    conn.commit()
        except Exception as exc:
            with sqlite3.connect(target_db, timeout=30) as conn:
                conn.execute("UPDATE website_sync SET last_checked_at=?, sync_error=? WHERE source_url=?",
                             (now_iso(), f"Status check error: {type(exc).__name__}"[:300], source_url))
                conn.commit()

    # Finalize any site-published records not yet reflected/cleaned locally.
    with sqlite3.connect(target_db, timeout=30) as conn:
        conn.row_factory = sqlite3.Row
        finalized = conn.execute("""
            SELECT s.source_url, s.site_post_id, s.site_slug, s.site_url
            FROM website_sync s
            JOIN articles a ON a.source_url=s.source_url
            WHERE s.site_status='published' AND a.status <> 'published'
            ORDER BY s.last_checked_at ASC LIMIT 100
        """).fetchall()

    outcomes = []
    for row in finalized:
        try:
            published_url = row["site_url"] or (f"{SITE_URL}/bai-viet/{row['site_slug']}" if row["site_slug"] else SITE_URL)
            if mark_published_callback:
                outcome = mark_published_callback(row["source_url"], published_url, row["site_post_id"])
            else:
                outcome = {"source_url": row["source_url"], "publish_url": published_url, "cleanup_complete": False}
            with sqlite3.connect(target_db, timeout=30) as conn:
                conn.execute("UPDATE website_sync SET local_cleanup_done=1, sync_error=NULL WHERE source_url=?", (row["source_url"],))
                conn.commit()
            outcomes.append({"status": "published", **(outcome if isinstance(outcome, dict) else {})})
        except Exception as exc:
            with sqlite3.connect(target_db, timeout=30) as conn:
                conn.execute("UPDATE website_sync SET sync_error=? WHERE source_url=?", (f"Local cleanup failed: {type(exc).__name__}: {clean(exc)[:400]}", row["source_url"]))
                conn.commit()
    return outcomes


def get_sync_record(source_url: str, db_path: str | None = None):
    target_db = db_path or DATABASE_PATH
    ensure_table(target_db)
    canonical = normalize_source_url(source_url)
    with sqlite3.connect(target_db, timeout=30) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM website_sync WHERE source_url=?", (canonical,)).fetchone()
        return dict(row) if row else None


def list_pending_drafts(db_path: str | None = None, limit: int = 3):
    target_db = db_path or DATABASE_PATH
    ensure_table(target_db)
    with sqlite3.connect(target_db, timeout=30) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT a.*, t.destination_country, t.destination_city, t.primary_category,
                   t.categories_json AS topic_categories_json
            FROM articles a
            LEFT JOIN article_taxonomy t ON t.source_url=a.source_url
            LEFT JOIN website_sync s ON s.source_url=a.source_url
            WHERE COALESCE(a.seo_title,'')<>'' AND COALESCE(a.seo_content,'')<>''
              AND a.status NOT IN ('published','duplicate','canonical_alias','duplicate_title')
              AND (s.source_url IS NULL OR s.site_status IN ('failed','pending'))
            ORDER BY a.id ASC LIMIT ?
        """, (max(1, min(int(limit), 10)),)).fetchall()
        return [dict(row) for row in rows]
