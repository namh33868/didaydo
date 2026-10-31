"""Bridge between Travel Content Bot and the Next.js ingest API.

Publishes completed, AI-written articles directly to the website. It requires an
explicitly enabled auto-publish health flag from the deployed website before posting.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv

PROJECT_DIR = Path(__file__).resolve().parent
load_dotenv(PROJECT_DIR / ".env")

SITE_SYNC_ENABLED = os.getenv("SITE_SYNC_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
SITE_URL = os.getenv("SITE_URL", os.getenv("NEXT_PUBLIC_SITE_URL", "")).strip().rstrip("/")
SITE_INGEST_API_KEY = os.getenv("SITE_INGEST_API_KEY", "").strip()
SITE_API_TIMEOUT = max(5, min(int(os.getenv("SITE_API_TIMEOUT_SECONDS", "20")), 60))
SOURCE_IMAGE_REUSE_AUTHORIZED = os.getenv("SOURCE_IMAGE_REUSE_AUTHORIZED", "false").strip().lower() in {"1", "true", "yes", "on"}
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


def _cover_credit(image: dict) -> str:
    creator = clean(image.get("credit") or image.get("creator") or "Không rõ tác giả")
    provider = clean(image.get("source_name") or image.get("provider") or "Kho ảnh mở")
    license_name = clean(image.get("license") or "")
    source_page = clean(image.get("source_page_url") or "")
    license_url = clean(image.get("license_url") or "")
    parts = [f"Ảnh: {creator}", provider]
    if license_name:
        parts.append(license_name)
    if source_page:
        parts.append("Nguồn ảnh: " + source_page)
    if license_url:
        parts.append("Giấy phép: " + license_url)
    return " · ".join(parts)[:1200]


def _ensure_editorial_cover_image(article: dict, db_path: str) -> dict | None:
    """Reuse a cached, license-checked cover or find one; persist it for safe retries."""
    from image_finder import find_cover_image, is_license_allowed, verify_image_url

    source_url = normalize_source_url(article.get("source_url", ""))
    stored_images = _stored_image_list(article)
    if source_url:
        try:
            with sqlite3.connect(db_path, timeout=30) as conn:
                row = conn.execute(
                    "SELECT source_images_json FROM articles WHERE source_url=?",
                    (source_url,),
                ).fetchone()
            if row and row[0]:
                cached_images = json.loads(row[0])
                if isinstance(cached_images, list):
                    stored_images = [item for item in cached_images if isinstance(item, dict)]
        except (sqlite3.Error, TypeError, json.JSONDecodeError):
            pass

    existing = article.get("editorial_cover_image")
    if not isinstance(existing, dict):
        existing = next(
            (item for item in stored_images
             if item.get("is_cover") is True and item.get("rights_status") == "license_metadata_checked"),
            None,
        )

    if isinstance(existing, dict):
        valid = (
            clean(existing.get("url")).startswith("https://")
            and existing.get("rights_status") == "license_metadata_checked"
            and is_license_allowed(clean(existing.get("license")))
            and clean(existing.get("source_page_url")).startswith("https://")
            and clean(existing.get("license_url")).startswith("https://")
            and verify_image_url(existing.get("url", ""))
        )
        if valid:
            selected = dict(existing)
        else:
            selected = None
            log.warning("Ảnh đại diện đã lưu không còn hợp lệ; sẽ tìm ảnh khác cho %s", article.get("source_url"))
    else:
        selected = None

    if selected is None:
        selected = find_cover_image(article)
    if not selected:
        return None

    article["editorial_cover_image"] = selected
    images = stored_images
    images = [item for item in images if item.get("image_id") != "COVER_LIBRARY"]
    images.append(selected)
    serialized = json.dumps(images, ensure_ascii=False)
    article["source_images"] = images
    article["source_images_json"] = serialized

    if source_url:
        with sqlite3.connect(db_path, timeout=30) as conn:
            conn.execute(
                "UPDATE articles SET source_images_json=?, updated_at=? WHERE source_url=?",
                (serialized, now_iso(), source_url),
            )
            conn.commit()
    return selected


def build_site_payload(article: dict, draft: dict) -> dict:
    title = clean(draft.get("seo_title") or article.get("source_title"))[:220]
    content_html = draft.get("seo_content") or ""
    # Auto-publishing must not put unlicensed source images or rights-review placeholders live.
    if not SOURCE_IMAGE_REUSE_AUTHORIZED and content_html:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(content_html, "html.parser")
        for placeholder in soup.select("figure.image-rights-review"):
            placeholder.decompose()
        content_html = str(soup)
    if not title or len(clean(re.sub(r"<[^>]+>", " ", content_html))) < 120:
        raise ValueError("Bản nháp không đủ tiêu đề hoặc nội dung để gửi website.")
    if len(content_html) > 490_000:
        raise ValueError("Nội dung HTML quá dài so với giới hạn API website 500 KB.")

    excerpt = clean(draft.get("seo_description") or article.get("source_summary"))[:500]
    seo_description = clean(draft.get("seo_description") or article.get("source_summary"))[:320]
    images = _image_candidates(article)
    cover_image = ""
    cover_alt = ""
    cover_credit = ""
    editorial_cover = article.get("editorial_cover_image")
    if isinstance(editorial_cover, dict):
        from image_finder import is_license_allowed
        if (
            editorial_cover.get("rights_status") != "license_metadata_checked"
            or not is_license_allowed(clean(editorial_cover.get("license")))
            or not clean(editorial_cover.get("url")).startswith("https://")
        ):
            raise ValueError("Ảnh đại diện không đạt kiểm tra giấy phép hoặc URL.")
        cover_image = clean(editorial_cover.get("url"))
        cover_alt = clean(editorial_cover.get("alt") or title)[:300]
        cover_credit = _cover_credit(editorial_cover)
    elif SOURCE_IMAGE_REUSE_AUTHORIZED:
        cover_image = clean(article.get("source_image_url"))
        if not cover_image and images:
            cover_image = clean(images[0].get("url"))
        if not cover_image.startswith("https://"):
            cover_image = ""
        if images:
            cover_alt = clean(images[0].get("alt") or images[0].get("caption") or title)[:300]
        else:
            cover_alt = title[:300]

    if not cover_image:
        raise ValueError("Không xuất bản bài viết khi thiếu ảnh đại diện hợp lệ.")

    tags = []
    tags.extend(_parse_list(draft.get("primary_keyword")))
    tags.extend(_parse_list(draft.get("secondary_keywords")))
    tags.extend(_parse_list(article.get("destination_countries")))
    tags.extend([clean(article.get("destination_country")), clean(article.get("destination_city"))])
    topic_labels = {
        "travel-guide": "cẩm nang du lịch", "travel-tips": "kinh nghiệm du lịch",
        "food-culture": "ẩm thực địa phương", "food": "ẩm thực", "hotel-review": "review khách sạn",
        "hotel-lodging": "khách sạn và lưu trú", "culture-local-life": "văn hóa địa phương",
        "itinerary": "lịch trình du lịch", "outdoor-adventure": "du lịch khám phá",
        "city-guide": "cẩm nang thành phố", "destination-guide": "điểm đến",
        "budget-travel": "du lịch tiết kiệm", "family-travel": "du lịch gia đình",
    }
    for topic in _parse_list(article.get("topic_categories")):
        tags.append(topic_labels.get(topic.casefold(), topic.replace("-", " ")))
    final_tags, seen = [], set()
    for tag in tags:
        tag = clean(tag)[:80]
        if tag and tag.casefold() not in seen:
            final_tags.append(tag)
            seen.add(tag.casefold())
        if len(final_tags) >= 20:
            break

    category = _category_for(article)
    source_url = normalize_source_url(clean(article.get("source_url")))
    source_name = clean(article.get("source_name") or article.get("source_publisher") or article.get("source_domain") or urlparse(source_url).hostname or "Nguồn tham khảo")[:200]
    return {
        "title": title,
        "excerpt": excerpt,
        "contentHtml": content_html,
        "coverImage": cover_image,
        "coverAlt": cover_alt,
        "coverCredit": cover_credit,
        "category": category,
        "tags": final_tags,
        "sourceUrl": source_url,
        "sourceName": source_name,
        "authorName": "Ban biên tập",
        "seoTitle": title,
        "seoDescription": seo_description,
        "featured": False,
        # API publishes this new article only when INGEST_AUTO_PUBLISH=true is enabled.
        "status": "published",
    }


def _record_sync(db_path: str, source_url: str, *, post_id=None, slug=None, status="failed", site_url=None, error=None):
    with sqlite3.connect(db_path, timeout=30) as conn:
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("""
            INSERT INTO website_sync(source_url, site_post_id, site_slug, site_status, site_url, last_synced_at, sync_error)
            VALUES(?,?,?,?,?,?,?)
            ON CONFLICT(source_url) DO UPDATE SET
                site_post_id=COALESCE(excluded.site_post_id, website_sync.site_post_id),
                site_slug=COALESCE(excluded.site_slug, website_sync.site_slug),
                site_status=excluded.site_status,
                site_url=COALESCE(excluded.site_url, website_sync.site_url),
                last_synced_at=excluded.last_synced_at,
                sync_error=excluded.sync_error
        """, (source_url, str(post_id) if post_id else None, slug, status, site_url, now_iso(), clean(error)[:1000] or None))
        conn.commit()


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
        if not SOURCE_IMAGE_REUSE_AUTHORIZED:
            selected_cover = _ensure_editorial_cover_image(article, target_db)
            if not selected_cover:
                raise RuntimeError("Không tìm được ảnh đại diện phù hợp có giấy phép sử dụng; bài được giữ lại, chưa xuất bản.")
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
