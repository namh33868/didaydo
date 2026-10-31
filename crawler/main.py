import argparse
import os
import re
import json
import time
import logging
import sqlite3
import unicodedata
import hashlib
from concurrent.futures import ThreadPoolExecutor
from html import escape as html_escape
from pathlib import Path
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(PROJECT_DIR, ".env"))

MAX_ARTICLES = max(1, min(int(os.getenv("MAX_ARTICLES", "10")), 10))
MAX_FEED_ITEMS_PER_SOURCE = max(5, min(int(os.getenv("MAX_FEED_ITEMS_PER_SOURCE", "20")), 60))
SOURCES_CONFIG_PATH = os.getenv("SOURCES_CONFIG_PATH", "sources.json").strip() or "sources.json"
TAXONOMY_CONFIG_PATH = os.getenv("TAXONOMY_CONFIG_PATH", "taxonomy.json").strip() or "taxonomy.json"
if not os.path.isabs(SOURCES_CONFIG_PATH):
    SOURCES_CONFIG_PATH = os.path.join(PROJECT_DIR, SOURCES_CONFIG_PATH)
if not os.path.isabs(TAXONOMY_CONFIG_PATH):
    TAXONOMY_CONFIG_PATH = os.path.join(PROJECT_DIR, TAXONOMY_CONFIG_PATH)

def _read_json_config(path, fallback):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        logging.getLogger("travel-content-bot").warning("Không đọc được cấu hình %s: %s", path, exc)
        return fallback

_SOURCE_CONFIG = _read_json_config(SOURCES_CONFIG_PATH, {"sources": []})
SOURCES = [s for s in _SOURCE_CONFIG.get("sources", []) if isinstance(s, dict)]
_TAXONOMY = _read_json_config(TAXONOMY_CONFIG_PATH, {"countries": [], "topics": []})
# Only retain complete source text in SQLite if the source is owned/licensed for this use.
ALLOW_FULL_TEXT_STORAGE = os.getenv("ALLOW_FULL_TEXT_STORAGE", "false").strip().lower() in {"1", "true", "yes"}
# Chỉ nhúng ảnh nguồn thật vào HTML đăng bài khi người vận hành xác nhận đã có quyền sử dụng.
# Nếu false, ảnh vẫn được trích xuất/tham chiếu và đặt placeholder đúng vị trí trong bản nháp.
SOURCE_IMAGE_REUSE_AUTHORIZED = os.getenv("SOURCE_IMAGE_REUSE_AUTHORIZED", "false").strip().lower() in {"1", "true", "yes"}
MAX_SOURCE_BODY_CHARS = max(3000, min(int(os.getenv("MAX_SOURCE_BODY_CHARS", "22000")), 40000))
# Smart context mode: fetch the accessible article text in memory so the writer has
# enough facts, but do not persist the source's full text by default. Crucially, this
# is passed to the writer in ONE AI call; no separate AI fact-extraction stage is needed.
# Set SOURCE_CONTEXT_MODE=metadata_only only if intentionally accepting shorter drafts.
SOURCE_CONTEXT_MODE = os.getenv("SOURCE_CONTEXT_MODE", "smart").strip().lower() or "smart"
if SOURCE_CONTEXT_MODE not in {"smart", "metadata_only"}:
    SOURCE_CONTEXT_MODE = "smart"
CRAWL_SOURCE_BODY = SOURCE_CONTEXT_MODE == "smart"  # compatibility alias for existing code
DATABASE_PATH = os.getenv("DATABASE_PATH", "data/travel_content.db")
if not os.path.isabs(DATABASE_PATH):
    # Luôn dùng đường dẫn tương đối với thư mục project, không phụ thuộc CWD/Task Scheduler.
    DATABASE_PATH = os.path.join(PROJECT_DIR, DATABASE_PATH)
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "output").strip() or "output"
if not os.path.isabs(OUTPUT_DIR):
    OUTPUT_DIR = os.path.join(PROJECT_DIR, OUTPUT_DIR)
OUTPUT_DIR = os.path.abspath(OUTPUT_DIR)
DRAFT_OUTPUT_DIR = os.path.join(OUTPUT_DIR, "drafts")
# AI failover order: Gemini -> direct OpenAI API -> optional legacy OpenRouter.
# Gemini is the preferred provider. OpenAI API can incur separate charges.
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash").strip() or "gemini-3.8-flash"
# Timeout tối đa cho từng lần gọi provider. Mặc định 300 giây (5 phút).
# Lưu ý: bài có nhiều stage AI thì tổng thời gian có thể lớn hơn 300 giây.
try:
    AI_PROVIDER_TIMEOUT_SECONDS = max(15, min(int(os.getenv("AI_PROVIDER_TIMEOUT_SECONDS", "300")), 300))
except ValueError:
    AI_PROVIDER_TIMEOUT_SECONDS = 300

# Gemini: dùng thinking thấp và timeout tối đa 300 giây. Biến GEMINI_TIMEOUT_MS
# là mili giây; ưu tiên biến này nếu người dùng đã đặt rõ trong .env.
GEMINI_THINKING_LEVEL = os.getenv("GEMINI_THINKING_LEVEL", "low").strip().lower()
if GEMINI_THINKING_LEVEL not in {"low", "medium", "high"}:
    GEMINI_THINKING_LEVEL = "low"
try:
    _gemini_timeout_default = str(AI_PROVIDER_TIMEOUT_SECONDS * 1000)
    GEMINI_TIMEOUT_MS = max(15000, min(int(os.getenv("GEMINI_TIMEOUT_MS", _gemini_timeout_default)), 300000))
except ValueError:
    GEMINI_TIMEOUT_MS = AI_PROVIDER_TIMEOUT_SECONDS * 1000
try:
    GEMINI_RETRY_ATTEMPTS = max(1, min(int(os.getenv("GEMINI_RETRY_ATTEMPTS", "2")), 3))
except ValueError:
    GEMINI_RETRY_ATTEMPTS = 2

# Output limit shared by providers. Free routed models may need more room for JSON.
try:
    AI_MAX_OUTPUT_TOKENS = max(2048, min(int(os.getenv("AI_MAX_OUTPUT_TOKENS", "7000")), 10000))
except ValueError:
    AI_MAX_OUTPUT_TOKENS = 7000

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini").strip() or "gpt-4.1-mini"

# Groq is a separate OpenAI-compatible provider. Keys that start with gsk_ belong
# to Groq, not api.openai.com; auto-correct a common .env misconfiguration.
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b").strip() or "openai/gpt-oss-120b"
_MISPLACED_GROQ_KEY = False
if OPENAI_API_KEY.startswith("gsk_"):
    if not GROQ_API_KEY:
        GROQ_API_KEY = OPENAI_API_KEY
    OPENAI_API_KEY = ""
    _MISPLACED_GROQ_KEY = True

# Optional fallback to keep a previously configured OpenRouter key usable.
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "openrouter/free").strip() or "openrouter/free"
OPENROUTER_SITE_URL = os.getenv("OPENROUTER_SITE_URL", "http://localhost").strip()
OPENROUTER_APP_NAME = os.getenv("OPENROUTER_APP_NAME", "Travel Content Bot").strip()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

HEADERS = {
    "User-Agent": os.getenv(
        "CRAWLER_USER_AGENT",
        "TravelResearchBot/1.0 (content research; contact: replace-with-your-email@example.com)",
    ),
    "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.5",
}
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("travel-content-bot")
if os.getenv("CRAWL_SOURCE_BODY") is not None and not os.getenv("SOURCE_CONTEXT_MODE"):
    log.info(
        "Đã chuyển từ CRAWL_SOURCE_BODY cũ sang SOURCE_CONTEXT_MODE=%s; có thể đặt SOURCE_CONTEXT_MODE=metadata_only để tắt trích thân bài.",
        SOURCE_CONTEXT_MODE,
    )
if _MISPLACED_GROQ_KEY:
    log.warning(
        "OPENAI_API_KEY có tiền tố gsk_; đây là định dạng key Groq. Đã tự chuyển key này sang provider Groq cho phiên chạy hiện tại; hãy chuyển key sang GROQ_API_KEY trong .env. Không có key nào được in ra log."
    )
log.info(
    "AI config loaded: dotenv=%s | Gemini timeout=%.0fs | provider timeout=%ss | Gemini attempts=%s | max output tokens=%s | Groq configured=%s | source image embedding authorized=%s | source context mode=%s | enabled RSS sources=%s",
    os.path.join(PROJECT_DIR, ".env"), GEMINI_TIMEOUT_MS / 1000.0,
    AI_PROVIDER_TIMEOUT_SECONDS, GEMINI_RETRY_ATTEMPTS, AI_MAX_OUTPUT_TOKENS, bool(GROQ_API_KEY), SOURCE_IMAGE_REUSE_AUTHORIZED, SOURCE_CONTEXT_MODE,
    sum(1 for source in SOURCES if source.get("enabled")),
)


def _sync_draft_to_site_if_enabled(article, draft):
    """Send a complete AI-written article to the website for publication."""
    if not draft or not draft.get("seo_title") or not draft.get("seo_content"):
        return None
    try:
        import site_publisher
        return site_publisher.sync_draft_to_site(article, draft, DATABASE_PATH)
    except Exception as exc:
        # Website integration must not lose the local artifact when publication fails.
        log.exception("Xuất bản website thất bại; vẫn giữ artifact local (%s)", type(exc).__name__)
        return {"ok": False, "error": f"{type(exc).__name__}: {clean_text(str(exc))[:400]}"}


def _reconcile_site_publications():
    """Detect posts published in website admin and perform existing safe cleanup."""
    try:
        import site_publisher
        results = site_publisher.reconcile_published_posts(DATABASE_PATH, mark_published)
        for result in results:
            if result.get("cleanup_complete"):
                log.info("Website xác nhận đã đăng; đã dọn output: %s", result.get("source_url"))
            elif result.get("status") == "published":
                log.warning("Bài đã đăng nhưng chưa dọn được output; sẽ thử lại lần sau: %s", result.get("source_url"))
        return results
    except Exception as exc:
        log.warning("Chưa đồng bộ được trạng thái website (%s); tiếp tục crawl bình thường.", type(exc).__name__)
        return []


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def clean_text(value):
    """Safely normalize metadata values from RSS/JSON-LD, which may be None, list, or dict."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    elif isinstance(value, dict):
        # Prefer common human-readable fields in structured metadata.
        preferred_keys = ("name", "value", "text", "headline", "description", "content", "@id")
        selected = [value.get(key) for key in preferred_keys if value.get(key) is not None]
        if selected:
            value = " ".join(clean_text(part) for part in selected if clean_text(part))
        else:
            value = " ".join(clean_text(part) for part in value.values() if part is not None)
    elif isinstance(value, (list, tuple, set)):
        value = " ".join(clean_text(part) for part in value if part is not None)
    else:
        value = str(value)
    return re.sub(r"\s+", " ", value).strip()


def normalize_url(url):
    """Normalize generic source URLs across multiple domains; strip tracking query/fragment."""
    if not url:
        return None
    parsed = urlparse(str(url).strip())
    if parsed.scheme.lower() not in ("http", "https") or not parsed.hostname:
        return None
    host = parsed.hostname.lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    if path != "/":
        path = path.rstrip("/")
    return parsed._replace(scheme="https", netloc=host, path=path or "/", params="", query="", fragment="").geturl()


def _normalize_host(host):
    value = (host or "").lower().rstrip(".")
    return value[4:] if value.startswith("www.") else value


def _url_allowed_for_source(url, source):
    host = _normalize_host(urlparse(url).hostname or "")
    allowed = source.get("article_domains") or source.get("allowed_domains") or [
        urlparse(source.get("homepage") or source.get("source_homepage") or url).hostname or ""
    ]
    for domain in allowed:
        domain = _normalize_host(str(domain))
        if domain and (host == domain or host.endswith("." + domain)):
            return True
    return False


def _source_domain(source, url=""):
    allowed = source.get("article_domains") or []
    return _normalize_host(allowed[0] if allowed else (urlparse(url).hostname or ""))


def _source_by_id(source_id):
    for item in SOURCES:
        if item.get("id") == source_id:
            return item
    return None


def normalize_title(title):
    """Chuẩn hóa tiêu đề để nhận ra bài giống nhau dù dấu câu/spacing khác."""
    text = unicodedata.normalize("NFKC", title or "").casefold()
    # Bỏ hậu tố tên trang thường được gắn vào title metadata.
    text = re.sub(r"\s*[|–—-]\s*(vnexpress|báo điện tử vnexpress).*$", "", text, flags=re.I)
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    return clean_text(text)


def normalize_published_day(value):
    """Quy ngày đăng về YYYY-MM-DD để đối chiếu RSS và metadata HTML."""
    value = clean_text(value)
    if not value:
        return ""

    try:
        # ISO format, bao gồm Z và offset timezone.
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.date().isoformat()
    except (ValueError, TypeError):
        pass

    try:
        parsed = parsedate_to_datetime(value)
        return parsed.date().isoformat()
    except (ValueError, TypeError, OverflowError):
        pass

    match = re.search(r"\b(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\b", value)
    if match:
        year, month, day = map(int, match.groups())
        try:
            return datetime(year, month, day).date().isoformat()
        except ValueError:
            return ""

    # Hỗ trợ ngày dạng dd/mm/yyyy.
    match = re.search(r"\b(\d{1,2})/(\d{1,2})/(20\d{2})\b", value)
    if match:
        day, month, year = map(int, match.groups())
        try:
            return datetime(year, month, day).date().isoformat()
        except ValueError:
            return ""
    return ""


def title_key(title):
    return normalize_title(title)[:600]


def init_db():
    """Tạo schema và nâng cấp an toàn database cũ, không xóa lịch sử đã crawl."""
    os.makedirs(os.path.dirname(DATABASE_PATH) or ".", exist_ok=True)
    with sqlite3.connect(DATABASE_PATH, timeout=30) as conn:
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_url TEXT UNIQUE NOT NULL,
                source_title TEXT NOT NULL,
                source_summary TEXT,
                published_at TEXT,
                source_modified_at TEXT,
                source_image_url TEXT,
                image_credit TEXT,
                image_credit_url TEXT,
                source_author TEXT,
                source_publisher TEXT,
                source_section TEXT,
                source_meta_keywords TEXT,
                source_images_json TEXT,
                source_fact_sheet_json TEXT,
                source_body_chars INTEGER,
                content_extraction_status TEXT,
                source_content TEXT,
                seo_title TEXT,
                seo_description TEXT,
                seo_content TEXT,
                primary_keyword TEXT,
                secondary_keywords TEXT,
                editorial_angle TEXT,
                fact_check_notes TEXT,
                source_facts_used TEXT,
                ai_provider TEXT,
                status TEXT NOT NULL DEFAULT 'discovered',
                telegram_message_id INTEGER,
                error_message TEXT,
                title_key TEXT,
                published_day TEXT,
                output_json_path TEXT,
                output_md_path TEXT,
                publish_url TEXT,
                cms_post_id TEXT,
                site_published_at TEXT,
                publish_error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

        # Migration cho database cũ: thêm cột còn thiếu, giữ nguyên bài đã lưu.
        existing_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(articles)").fetchall()
        }
        if "title_key" not in existing_columns:
            conn.execute("ALTER TABLE articles ADD COLUMN title_key TEXT")
        if "published_day" not in existing_columns:
            conn.execute("ALTER TABLE articles ADD COLUMN published_day TEXT")
        # AI metadata migrations: preserve already-saved crawler history.
        ai_columns = {
            "primary_keyword": "TEXT",
            "secondary_keywords": "TEXT",
            "editorial_angle": "TEXT",
            "fact_check_notes": "TEXT",
            "source_facts_used": "TEXT",
            "ai_provider": "TEXT",
        }
        for column, column_type in ai_columns.items():
            if column not in existing_columns:
                conn.execute(f"ALTER TABLE articles ADD COLUMN {column} {column_type}")

        extended_columns = {
            "source_modified_at": "TEXT",
            "source_author": "TEXT",
            "source_publisher": "TEXT",
            "source_section": "TEXT",
            "source_meta_keywords": "TEXT",
            "source_images_json": "TEXT",
            "source_fact_sheet_json": "TEXT",
            "source_body_chars": "INTEGER",
            "content_extraction_status": "TEXT",
            "source_content": "TEXT",
        }
        # Refresh because the earlier migration may have added some columns.
        existing_columns = {row[1] for row in conn.execute("PRAGMA table_info(articles)").fetchall()}
        for column, column_type in extended_columns.items():
            if column not in existing_columns:
                conn.execute(f"ALTER TABLE articles ADD COLUMN {column} {column_type}")

        publication_columns = {
            "output_json_path": "TEXT",
            "output_md_path": "TEXT",
            "publish_url": "TEXT",
            "cms_post_id": "TEXT",
            "site_published_at": "TEXT",
            "publish_error": "TEXT",
        }
        existing_columns = {row[1] for row in conn.execute("PRAGMA table_info(articles)").fetchall()}
        for column, column_type in publication_columns.items():
            if column not in existing_columns:
                conn.execute(f"ALTER TABLE articles ADD COLUMN {column} {column_type}")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS seen_sources (
                source_url TEXT PRIMARY KEY,
                title_key TEXT,
                published_day TEXT,
                status TEXT NOT NULL DEFAULT 'seen',
                duplicate_of TEXT,
                first_seen_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS article_taxonomy (
                source_url TEXT PRIMARY KEY,
                source_id TEXT,
                source_name TEXT,
                source_domain TEXT,
                source_language TEXT,
                source_feed_url TEXT,
                destination_country TEXT,
                destination_city TEXT,
                destination_countries_json TEXT,
                destination_status TEXT,
                primary_category TEXT,
                categories_json TEXT,
                taxonomy_path TEXT,
                topic_confidence TEXT,
                updated_at TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_taxonomy_country_category ON article_taxonomy(destination_country, primary_category)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_articles_title_day ON articles(title_key, published_day)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_seen_title_day ON seen_sources(title_key, published_day)")

        rows = conn.execute(
            "SELECT source_url, source_title, published_at, title_key, published_day FROM articles"
        ).fetchall()
        timestamp = now_iso()
        for source_url, source_title, published_at, saved_title_key, saved_day in rows:
            key = saved_title_key or title_key(source_title)
            day = saved_day or normalize_published_day(published_at)
            conn.execute(
                "UPDATE articles SET title_key=?, published_day=? WHERE source_url=?",
                (key, day, source_url),
            )
            canonical = normalize_url(source_url) or source_url
            # Đánh dấu cả URL cũ và URL chuẩn làm lịch sử đã gặp.
            for seen_url in {source_url, canonical}:
                conn.execute(
                    "INSERT OR IGNORE INTO seen_sources(source_url,title_key,published_day,status,first_seen_at) VALUES(?,?,?,?,?)",
                    (seen_url, key, day, "existing", timestamp),
                )
        conn.commit()


def fetch(url, timeout=20, attempts=3, max_bytes=None, max_elapsed_seconds=None):
    """Fetch with bounded timeouts; optionally cap downloaded page bytes.

    max_bytes is used for article HTML so an unusually large/slow page cannot hold
    the run indefinitely. We never bypass 401/403/429 or TLS verification.
    """
    last_error = None
    retry_count = max(1, int(attempts))
    request_timeout = timeout
    if isinstance(timeout, (int, float)):
        # Separate connect/read limits make stalled sites fail predictably.
        request_timeout = (min(8, max(3, float(timeout))), max(5, float(timeout)))

    for attempt in range(retry_count):
        try:
            with requests.get(
                url,
                headers=HEADERS,
                timeout=request_timeout,
                stream=(max_bytes is not None),
                allow_redirects=True,
            ) as response:
                if response.status_code in (401, 403, 429):
                    raise RuntimeError(f"Nguồn từ chối truy cập HTTP {response.status_code}: {url}")
                response.raise_for_status()

                if max_bytes is None:
                    return response.text

                cap = max(1024, int(max_bytes))
                chunks = []
                total = 0
                deadline = (time.monotonic() + max(1.0, float(max_elapsed_seconds))) if max_elapsed_seconds else None
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    if deadline is not None and time.monotonic() >= deadline:
                        log.warning("Đạt giới hạn thời gian tải HTML; dùng phần HTML đã nhận: %s", url)
                        break
                    if not chunk:
                        continue
                    remaining = cap - total
                    if remaining <= 0:
                        break
                    if len(chunk) > remaining:
                        chunk = chunk[:remaining]
                    chunks.append(chunk)
                    total += len(chunk)
                    if total >= cap:
                        log.warning("HTML bài nguồn vượt giới hạn %s byte; dừng tải phần còn lại: %s", cap, url)
                        break
                encoding = response.encoding or "utf-8"
                return b"".join(chunks).decode(encoding, errors="replace")
        except RuntimeError:
            raise
        except requests.RequestException as exc:
            last_error = exc
            if attempt < retry_count - 1:
                time.sleep(min(2 ** attempt, 3))
    raise RuntimeError(f"Không tải được {url}: {last_error}")


def meta(soup, *keys):
    for key in keys:
        tag = soup.find("meta", attrs={"property": key}) or soup.find("meta", attrs={"name": key})
        if tag and tag.get("content"):
            return clean_text(tag["content"])
    return ""


def _feed_item_url(entry, feed_url):
    links = entry.find_all("link")
    # Atom feeds may expose self/alternate links; prefer the public article permalink.
    for link in links:
        rel = (link.get("rel") or "").lower()
        if link.get("href") and rel not in {"self", "enclosure"}:
            return normalize_url(urljoin(feed_url, link.get("href")))
    for link in links:
        value = link.get("href") or link.get_text(strip=True)
        if value:
            return normalize_url(urljoin(feed_url, value))
    guid = entry.find("guid") or entry.find("id")
    if guid:
        value = guid.get("href") or guid.get_text(strip=True)
        return normalize_url(urljoin(feed_url, value))
    return None


def _feed_item_image(entry, feed_url):
    for node in entry.find_all(True):
        tag_name = str(node.name or "").lower()
        if tag_name in {"enclosure", "media:content", "media:thumbnail", "thumbnail", "content"} or "thumbnail" in tag_name:
            url = node.get("url") or node.get("href") or node.get("src")
            mime = (node.get("type") or node.get("medium") or "").lower()
            url_text = (url or "").lower().split("?", 1)[0]
            looks_like_image = url_text.endswith((".jpg", ".jpeg", ".png", ".webp", ".gif"))
            if url and ("image" in mime or tag_name != "enclosure" or looks_like_image):
                return urljoin(feed_url, url)
    # Some feeds use an image inside the description. Keep only the URL.
    desc = entry.find("description") or entry.find("summary")
    if desc:
        frag = BeautifulSoup(desc.get_text() or "", "html.parser")
        image = frag.find("img")
        if image and (image.get("src") or image.get("data-src")):
            return urljoin(feed_url, image.get("src") or image.get("data-src"))
    return ""


def _feed_entry_summary(entry):
    # Deliberately ignore content:encoded to avoid ingesting full source articles from RSS.
    node = entry.find("description") or entry.find("summary") or entry.find("subtitle")
    if not node:
        return ""
    raw = node.get_text(" ", strip=True)
    summary = clean_text(BeautifulSoup(raw, "html.parser").get_text(" ", strip=True))
    return summary[:1200]


def _parse_feed_items(xml, source):
    feed_url = source.get("feed_url", "")
    soup = BeautifulSoup(xml, "xml")
    entries = soup.find_all("item")
    if not entries:
        entries = soup.find_all("entry")  # Atom feeds
    results, seen = [], set()
    for entry in entries[:MAX_FEED_ITEMS_PER_SOURCE]:
        link_url = _feed_item_url(entry, feed_url)
        path_lower = (urlparse(link_url).path or "/").lower() if link_url else "/"
        if (not link_url or link_url in seen or path_lower in {"", "/"}
                or path_lower.rstrip("/").endswith(("/feed", "/rss", "/rss.xml", "/feed.xml"))
                or not _url_allowed_for_source(link_url, source)):
            continue
        seen.add(link_url)
        title_node = entry.find("title")
        title = clean_text(title_node.get_text(" ", strip=True) if title_node else "")
        if not title:
            continue
        summary = _feed_entry_summary(entry)
        date_node = entry.find("pubDate") or entry.find("published") or entry.find("updated") or entry.find("date")
        published = clean_text(date_node.get_text(strip=True) if date_node else "")
        categories = [clean_text(c.get("term") or c.get_text(" ", strip=True)) for c in entry.find_all("category") if clean_text(c.get("term") or c.get_text(" ", strip=True))]
        item = {
            "source_url": link_url,
            "rss_title": title[:500],
            "rss_summary": summary,
            "rss_published_at": published[:120],
            "rss_categories": categories[:12],
            "rss_image_url": _feed_item_image(entry, feed_url) or None,
            "source_id": source.get("id", ""),
            "source_name": source.get("name", ""),
            "source_homepage": source.get("homepage", ""),
            "source_feed_url": feed_url,
            "source_domain": _source_domain(source, link_url),
            "source_language": source.get("language", "en"),
            "source_focus": source.get("focus", []),
            "allowed_domains": source.get("article_domains", []),
            "permission_status": source.get("permission_status", "review_terms_before_commercial_reuse"),
        }
        results.append(item)
    return results


def _fetch_one_source_feed(source):
    name = source.get("name", source.get("id", "unknown"))
    try:
        xml = fetch(source["feed_url"], timeout=12, attempts=1)
        items = _parse_feed_items(xml, source)
        return source, items, None
    except Exception as exc:
        return source, [], f"{type(exc).__name__}: {clean_text(str(exc))[:180]}"


def discover_from_sources():
    """Read configured English-language RSS/Atom feeds concurrently and interleave candidates."""
    active_sources = []
    for source in SOURCES:
        if not source.get("enabled", False):
            continue
        if str(source.get("language", "en")).lower().split("-")[0] != "en":
            log.warning("Bỏ qua nguồn không khai báo English: %s", source.get("name", source.get("id")))
            continue
        active_sources.append(source)

    per_source = []
    if active_sources:
        # Run a small bounded number of feed requests in parallel; one dead feed won't
        # stall the whole discovery loop for all sources sequentially.
        with ThreadPoolExecutor(max_workers=min(6, len(active_sources))) as pool:
            results = list(pool.map(_fetch_one_source_feed, active_sources))
        for source, items, error in results:
            name = source.get("name", source.get("id", "unknown"))
            if error:
                log.warning("Source feed lỗi; bỏ qua để tiếp tục nguồn khác: %s | %s", name, error)
                continue
            log.info("Source feed=%s entries=%s", name, len(items))
            if items:
                per_source.append((source, items))

    # Round-robin across feeds; one large feed cannot occupy all MAX_ARTICLES slots.
    ordered = []
    max_len = max((len(items) for _source, items in per_source), default=0)
    for index in range(max_len):
        for _source, items in per_source:
            if index < len(items):
                ordered.append(items[index])
    log.info(
        "Multi-source discovery: active_sources=%s feeds_with_items=%s candidate_urls=%s",
        len(active_sources), len(per_source), len(ordered),
    )

    # Always revisit previously saved AI failures, even when their RSS feed has
    # rolled them out of its recent-items window.
    retry_candidates = []
    try:
        with sqlite3.connect(DATABASE_PATH, timeout=30) as conn:
            conn.row_factory = sqlite3.Row
            retry_rows = conn.execute("""
                SELECT a.source_url, a.source_title, a.source_summary, a.published_at,
                       a.source_image_url, t.source_id, t.source_name, t.source_domain,
                       t.source_feed_url, t.source_language
                FROM articles a
                LEFT JOIN article_taxonomy t ON t.source_url=a.source_url
                WHERE a.status IN ('ai_failed_metadata_only','discovered')
                  AND (COALESCE(a.seo_title,'')='' OR COALESCE(a.seo_content,'')='')
                ORDER BY a.updated_at ASC
                LIMIT 30
            """).fetchall()

        for row in retry_rows:
            source = _source_by_id(row["source_id"]) if row["source_id"] else None
            if not source:
                continue
            retry_candidates.append({
                "source_url": row["source_url"],
                "rss_title": row["source_title"],
                "rss_summary": row["source_summary"] or "",
                "rss_published_at": row["published_at"] or "",
                "rss_categories": [],
                "rss_image_url": row["source_image_url"],
                "source_id": source.get("id", ""),
                "source_name": row["source_name"] or source.get("name", ""),
                "source_homepage": source.get("homepage", ""),
                "source_feed_url": row["source_feed_url"] or source.get("feed_url", ""),
                "source_domain": row["source_domain"] or _source_domain(source, row["source_url"]),
                "source_language": row["source_language"] or source.get("language", "en"),
                "source_focus": source.get("focus", []),
                "allowed_domains": source.get("article_domains") or source.get("allowed_domains", []),
                "permission_status": source.get("permission_status", "review_terms_before_commercial_reuse"),
            })
    except sqlite3.Error as exc:
        log.warning("Không nạp được hàng đợi AI lỗi từ SQLite (%s); vẫn crawl RSS mới.", type(exc).__name__)

    if retry_candidates:
        combined, seen_urls = [], set()
        for candidate in retry_candidates + ordered:
            url = normalize_url(candidate.get("source_url", ""))
            if url and url not in seen_urls:
                combined.append(candidate)
                seen_urls.add(url)
        log.info("Ưu tiên thử lại %s bài AI chưa hoàn chỉnh đã lưu trước bài RSS mới.", len(retry_candidates))
        ordered = combined

    return ordered

# Legacy function name retained for callers, but it now reads all configured feeds (never VnExpress).
def discover_from_rss():
    return discover_from_sources()


def classify_article(article, item=None):
    """Deterministic destination/topic classifier for site taxonomy. Never guesses unknown country."""
    item = item or {}
    image_context = " ".join(
        clean_text(f"{image.get('alt', '')} {image.get('caption', '')}")
        for image in (article.get("source_images") or []) if isinstance(image, dict)
    )
    # RSS / JSON-LD feeds sometimes return nulls or arrays where other feeds return strings.
    # Normalize every value before joining so one odd metadata field cannot drop an article.
    parts = [
        clean_text(article.get("source_title")),
        clean_text(article.get("source_summary")),
        clean_text(article.get("source_meta_keywords")),
        clean_text(article.get("source_section")),
        clean_text(item.get("rss_categories")),
        clean_text(article.get("source_url")),
        clean_text(image_context),
    ]
    haystack = " ".join(part for part in parts if part).casefold()
    haystack = re.sub(r"[_/\-]+", " ", haystack)
    matched_countries = []
    matched_city = ""
    matched_city_country = ""
    for country in _TAXONOMY.get("countries", []):
        alias_list = list(country.get("aliases", []))
        cities = country.get("cities", [])
        # Match city aliases alongside country names; longest phrase first to avoid partial matches.
        country_matches = any(re.search(r"(?<!\w)" + re.escape(str(alias).casefold()) + r"(?!\w)", haystack) for alias in sorted(alias_list, key=len, reverse=True) if alias)
        country_city_matches = []
        for city in cities:
            for alias in sorted(city.get("aliases", []), key=len, reverse=True):
                if alias and re.search(r"(?<!\w)" + re.escape(str(alias).casefold()) + r"(?!\w)", haystack):
                    country_city_matches.append(city.get("name", ""))
                    break
        if country_matches or country_city_matches:
            if country.get("name") not in matched_countries:
                matched_countries.append(country.get("name"))
            if country_city_matches and not matched_city:
                matched_city = country_city_matches[0]
                matched_city_country = country.get("name", "")

    # Keyword matching by topic; multiple topic pages may be attached to one article.
    topic_scores = []
    for topic in _TAXONOMY.get("topics", []):
        score = 0
        for alias in topic.get("aliases", []):
            alias_norm = str(alias).casefold().strip()
            if alias_norm and re.search(r"(?<!\w)" + re.escape(alias_norm) + r"(?!\w)", haystack):
                score += max(1, min(len(alias_norm.split()), 3))
        # Boost focus tags for a source when title/meta are not very descriptive.
        if topic.get("slug") in (item.get("source_focus") or []):
            score += 0.25
        if score:
            topic_scores.append((score, topic.get("slug"), topic.get("name")))
    topic_scores.sort(key=lambda v: (-v[0], v[1] or ""))
    category_slugs = [slug for _score, slug, _name in topic_scores[:4] if slug]
    if not category_slugs:
        category_slugs = ["travel-guide"]
    primary_category = category_slugs[0]

    primary_country = matched_countries[0] if matched_countries else ""
    country_node = next((x for x in _TAXONOMY.get("countries", []) if x.get("name") == primary_country), None)
    country_slug = country_node.get("slug", "") if country_node else "world-unclassified"
    topic_map = {topic.get("slug"): topic for topic in _TAXONOMY.get("topics", [])}
    primary_topic = topic_map.get(primary_category, {})
    top_section = {
        "food-and-drink": ("Ẩm thực", "am-thuc"),
        "hotel-review": ("Khách sạn & lưu trú", "khach-san-luu-tru"),
        "things-to-do": ("Điểm check-in", "diem-check-in"),
        "itinerary": ("Lịch trình", "lich-trinh"),
        "travel-guide": ("Cẩm nang", "cam-nang"),
        "outdoor-adventure": ("Thế giới", "the-gioi"),
        "budget-travel": ("Cẩm nang", "cam-nang"),
        "travel-tips": ("Cẩm nang", "cam-nang"),
        "culture-local-life": ("Thế giới", "the-gioi"),
        "sustainable-travel": ("Cẩm nang", "cam-nang"),
        "destination-news": ("Thế giới", "the-gioi"),
        "luxury-travel": ("Khách sạn & lưu trú", "khach-san-luu-tru"),
        "beach-island": ("Điểm check-in", "diem-check-in"),
        "transport": ("Cẩm nang", "cam-nang"),
        "family-travel": ("Cẩm nang", "cam-nang"),
    }.get(primary_category, ("Cẩm nang", "cam-nang"))
    taxonomy_path = f"the-gioi/{country_slug}/{primary_category}" if primary_country else f"{top_section[1]}/{primary_category}"
    country_status = "matched" if len(matched_countries) == 1 else ("multi_destination" if len(matched_countries) > 1 else "needs_review")
    return {
        "source_id": item.get("source_id") or article.get("source_id") or "",
        "source_name": item.get("source_name") or article.get("source_name") or article.get("source_publisher") or "",
        "source_domain": item.get("source_domain") or article.get("source_domain") or _normalize_host(urlparse(article.get("source_url", "")).hostname or ""),
        "source_language": item.get("source_language") or article.get("source_language") or "en",
        "source_feed_url": item.get("source_feed_url") or article.get("source_feed_url") or "",
        "source_focus": item.get("source_focus") or article.get("source_focus") or [],
        "permission_status": item.get("permission_status") or article.get("permission_status") or "review_terms_before_commercial_reuse",
        "destination_country": primary_country or "World / Chưa phân loại",
        "destination_city": matched_city if matched_city_country == primary_country else "",
        "destination_countries": matched_countries,
        "destination_status": country_status,
        "primary_category": primary_category,
        "topic_categories": category_slugs,
        "topic_confidence": "medium" if topic_scores and topic_scores[0][0] >= 2 else "low",
        "taxonomy_path": taxonomy_path,
        "top_level_section": top_section[0],
    }


def _is_ai_capacity_error(message):
    """Recognize provider-wide quota/auth throttling so one exhausted run doesn't burn more calls."""
    value = clean_text(message).casefold()
    markers = (
        "quota", "resource_exhausted", "429", "rate limit", "rate_limit",
        "too many requests", "insufficient_quota", "tokens per minute",
        "requests per minute", "daily request limit", "billing",
        "invalid api key", "unauthorized", "authentication", "http 401", "http 403",
    )
    return any(marker in value for marker in markers)


def already_seen(url):
    """Skip known aliases/duplicates and completed records, but allow incomplete AI failures to retry."""
    url = normalize_url(url) or url
    with sqlite3.connect(DATABASE_PATH, timeout=30) as conn:
        row = conn.execute(
            """SELECT 1 FROM seen_sources
               WHERE source_url=?
                 AND status NOT IN ('ai_failed_metadata_only','discovered','existing')
               UNION
               SELECT 1 FROM articles
               WHERE source_url=?
                 AND (
                     (COALESCE(seo_title,'')<>'' AND COALESCE(seo_content,'')<>'')
                     OR status IN ('published','duplicate','canonical_alias','duplicate_title')
                 )
               LIMIT 1""",
            (url, url),
        ).fetchone()
        return row is not None


def remember_source(url, key="", day="", status="seen", duplicate_of=None):
    """Ghi nhận URL alias/duplicate để lần crawl sau không xử lý lại."""
    url = normalize_url(url) or url
    if not url:
        return
    with sqlite3.connect(DATABASE_PATH, timeout=30) as conn:
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.execute(
            """INSERT OR IGNORE INTO seen_sources
               (source_url,title_key,published_day,status,duplicate_of,first_seen_at)
               VALUES(?,?,?,?,?,?)""",
            (url, key or None, day or None, status, duplicate_of, now_iso()),
        )
        conn.commit()


def find_duplicate_by_title(title, published_at, exclude_source_url=None):
    """Khử trùng tiêu đề/ngày, nhưng không coi chính bản ghi lỗi đang được thử lại là bản trùng."""
    key = title_key(title)
    day = normalize_published_day(published_at)
    if not key:
        return None
    excluded_url = normalize_url(exclude_source_url) if exclude_source_url else None
    with sqlite3.connect(DATABASE_PATH, timeout=30) as conn:
        if day:
            row = conn.execute(
                """SELECT source_url, source_title, published_day FROM articles
                   WHERE title_key=?
                     AND (published_day=? OR published_day IS NULL OR published_day='')
                     AND (? IS NULL OR source_url<>?)
                   ORDER BY id ASC LIMIT 1""",
                (key, day, excluded_url, excluded_url),
            ).fetchone()
        else:
            row = conn.execute(
                """SELECT source_url, source_title, published_day FROM articles
                   WHERE title_key=?
                     AND (published_day IS NULL OR published_day='')
                     AND (? IS NULL OR source_url<>?)
                   ORDER BY id ASC LIMIT 1""",
                (key, excluded_url, excluded_url),
            ).fetchone()
    if not row:
        return None
    return {"source_url": row[0], "source_title": row[1], "published_day": row[2] or ""}


def _jsonld_article_nodes(soup):
    """Return JSON-LD objects that look like article metadata."""
    results = []

    def visit(value):
        if isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, dict):
            if "@graph" in value:
                visit(value.get("@graph"))
            node_type = value.get("@type", "")
            types = node_type if isinstance(node_type, list) else [node_type]
            if any(str(t).lower() in {"article", "newsarticle", "reportagenewsarticle", "blogposting"} for t in types):
                results.append(value)
            # Some pages wrap the JSON-LD article in a graph/list.
            for key in ("mainEntity", "mainEntityOfPage", "itemListElement"):
                if key in value and isinstance(value[key], (dict, list)):
                    visit(value[key])

    for script in soup.select('script[type="application/ld+json"]'):
        raw = script.string or script.get_text()
        if not raw:
            continue
        try:
            visit(json.loads(raw.strip()))
        except (json.JSONDecodeError, TypeError):
            continue
    return results


def _person_field(value):
    if isinstance(value, str):
        return clean_text(value)
    if isinstance(value, dict):
        return clean_text(value.get("name") or value.get("legalName") or "")
    if isinstance(value, list):
        names = [_person_field(item) for item in value]
        return ", ".join(name for name in names if name)
    return ""


def _absolute_image_url(tag, page_url):
    if not tag:
        return ""
    candidate = (
        tag.get("data-src") or tag.get("data-original") or tag.get("data-lazy-src")
        or tag.get("src") or ""
    )
    if not candidate:
        srcset = tag.get("data-srcset") or tag.get("srcset") or ""
        if srcset:
            candidate = srcset.split(",")[0].strip().split(" ")[0]
    if not candidate or candidate.startswith("data:"):
        return ""
    return urljoin(page_url, candidate)


def _parse_explicit_photo_credit(text):
    """Đọc credit ảnh nếu có nhãn rõ ràng; không suy đoán từ tên tác giả bài."""
    text = clean_text(text)
    if not text or len(text) > 240:
        return ""
    # Bao gồm trường hợp CMS sinh nội dung lặp nhãn như "Ảnh:Ảnh: Hà Nghĩa".
    match = re.match(
        r"^(?:(?:Ảnh|Hình ảnh|Nguồn ảnh|Photo(?:\s+credit)?|Image credit)\s*[:：]\s*)+(.{2,180})$",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        credit = clean_text(match.group(1)).rstrip(".。;；")
        # Tránh coi cụm mô tả chung là tên người chụp.
        if credit and not re.fullmatch(r"(?:minh họa|illustration|tư liệu|nguồn|internet)", credit, re.I):
            return credit[:180]
    return ""


def _image_credit_from_caption(caption):
    caption = clean_text(caption)
    if not caption:
        return ""
    # Credit có thể ở đầu caption hoặc cuối caption.
    explicit = _parse_explicit_photo_credit(caption)
    if explicit:
        return explicit
    match = re.search(
        r"(?:Ảnh|Hình ảnh|Nguồn ảnh|Photo(?:\s+credit)?|Image credit)\s*[:：]\s*([^|;；]{2,160})$",
        caption,
        re.I,
    )
    return clean_text(match.group(1)).rstrip(".。")[:180] if match else ""


def _extract_article_footer_photo_credit(container):
    """Tìm credit ảnh nằm cuối bài (ví dụ 'Ảnh: Hà Nghĩa'), không lấy tác giả bài viết."""
    if not container:
        return ""
    candidates = []
    for node in container.find_all(["p", "div", "span", "figcaption"]):
        # Bỏ wrapper có nhiều block con để không lấy toàn đoạn dài làm credit.
        if node.find(["p", "div", "figure", "figcaption"]) and node.name in {"div", "p"}:
            continue
        text = clean_text(node.get_text(" ", strip=True))
        if text and len(text) <= 240:
            candidates.append(text)
    # Tìm ngược ở các nút cuối bài, nơi VnExpress thường ghi credit ảnh chung.
    for text in reversed(candidates[-20:]):
        credit = _parse_explicit_photo_credit(text)
        if credit:
            return credit
    return ""


def _nearest_image_wrapper(image_tag, container):
    """Chọn wrapper bao cả ảnh lẫn caption; ưu tiên tplCaption/figure hơn fig-picture."""
    ancestors = []
    for parent in image_tag.parents:
        if parent is container:
            break
        ancestors.append(parent)
    # Wrapper ngoài thường chứa caption sibling (VnExpress hay dùng .tplCaption).
    for parent in ancestors:
        classes = " ".join(parent.get("class", [])).lower()
        if parent.name == "figure" or "tplcaption" in classes or "image_caption" in classes or "image-caption" in classes:
            return parent
    # Fallback cho markup khác.
    for parent in ancestors:
        classes = " ".join(parent.get("class", [])).lower()
        if any(token in classes for token in ("fig-picture", "imagecaption")):
            return parent
    return image_tag.parent


def _extract_article_images(container, article_url, soup, article_footer_credit=""):
    """Trích ảnh theo thứ tự DOM, cùng alt/caption/credit và vị trí tương đối trong bài."""
    images = []
    seen = set()
    if container:
        img_tags = container.select("img")
        content_nodes = container.find_all(["p", "h2", "h3", "h4", "blockquote", "li"])
        total_text_blocks = max(1, len(content_nodes))
        dom_order = {id(node): index for index, node in enumerate(container.descendants)}
        total_images = max(1, len(img_tags))
        for index, image_tag in enumerate(img_tags, start=1):
            src = _absolute_image_url(image_tag, article_url)
            if not src or src in seen:
                continue
            seen.add(src)
            wrapper = _nearest_image_wrapper(image_tag, container)
            caption_node = None
            if wrapper and wrapper is not image_tag.parent:
                caption_node = wrapper.select_one("figcaption, .caption, .ImageCaption, .image_caption, .image-caption")
                if caption_node is None:
                    # Tìm caption trong các sibling gần ảnh, nhưng đừng lấy toàn văn thân bài.
                    for sibling in wrapper.find_all(["p", "div", "span"], recursive=True):
                        text = clean_text(sibling.get_text(" ", strip=True))
                        if text and len(text) <= 700 and not sibling.find("img"):
                            caption_node = sibling
                            break
            caption = clean_text(caption_node.get_text(" ", strip=True) if caption_node else "")[:600]
            credit = _image_credit_from_caption(caption)
            if not credit:
                credit = article_footer_credit
                credit_source = "article_footer" if credit else None
            else:
                credit_source = "caption"
            image_order = dom_order.get(id(image_tag), 0)
            previous_blocks = [node for node in content_nodes if dom_order.get(id(node), 0) < image_order]
            previous_headings = [node for node in previous_blocks if node.name in {"h2", "h3", "h4"}]
            nearby_heading = clean_text(previous_headings[-1].get_text(" ", strip=True))[:180] if previous_headings else ""
            # Tỉ lệ vị trí chỉ dùng để fallback khi AI không đặt marker ảnh.
            ratio = min(1.0, max(0.0, len(previous_blocks) / total_text_blocks))
            image_id = f"IMG_{len(images) + 1:02d}"
            images.append({
                "image_id": image_id,
                "url": src,
                "alt": clean_text(image_tag.get("alt", ""))[:300],
                "caption": caption,
                "credit": credit or None,
                "credit_source": credit_source,
                "position_index": len(images) + 1,
                "position_ratio": round(ratio, 3),
                "nearby_heading": nearby_heading,
                "rights_status": "unverified",
                "source_page_url": article_url,
                "placement_source": "article_body",
            })

    # og:image chỉ là ảnh đại diện fallback, không chèn thành ảnh inline lặp lại
    # nếu thân bài đã có ảnh riêng.
    if not images:
        og_image = meta(soup, "og:image", "twitter:image")
        if og_image:
            og_image = urljoin(article_url, og_image)
            images.append({
                "image_id": "IMG_01",
                "url": og_image,
                "alt": "",
                "caption": "",
                "credit": article_footer_credit or None,
                "credit_source": "article_footer" if article_footer_credit else None,
                "position_index": 1,
                "position_ratio": 0.0,
                "nearby_heading": "",
                "rights_status": "unverified",
                "source_page_url": article_url,
                "placement_source": "og:image_fallback",
            })
    return images[:20]

def _find_article_container(soup):
    """Find the article DOM container from structural selectors, without extracting prose."""
    selectors = [
        ".fck_detail", ".main_fck_detail", ".content_detail", ".detail-content",
        "article .fck_detail", "article .content_detail", "article .detail-content",
        "article .entry-content", ".entry-content", ".wp-block-post-content",
        ".post-content", ".single-post-content", ".article-body", ".article-content",
        ".td-post-content", ".elementor-widget-theme-post-content", ".prose",
    ]
    for selector in selectors:
        node = soup.select_one(selector)
        # Only inspect DOM structure; do not call get_text() on the article body.
        if node and node.select_one("p, h2, h3, figure, img, .tplCaption, figcaption"):
            return node

    candidates = soup.select("article") or soup.select("main, .content, .article-content, .main-content")
    if not candidates:
        return None

    def structural_score(node):
        paragraphs = len(node.find_all("p"))
        headings = len(node.find_all(["h2", "h3", "h4"]))
        images = len(node.find_all("img"))
        figures = len(node.find_all(["figure", "figcaption"]))
        # Strongly prefer blocks with prose/image structure, without reading paragraph text.
        return paragraphs + (2 * headings) + (4 * images) + (2 * figures)

    best = max(candidates, key=structural_score)
    return best if structural_score(best) > 0 else None


def _is_photo_credit_line(text):
    return bool(_parse_explicit_photo_credit(text))


def _extract_body_text(container):
    if not container:
        return ""
    cloned = BeautifulSoup(str(container), "html.parser")
    for bad in cloned.select(
        "script, style, noscript, iframe, nav, aside, form, button, "
        ".box-tinlienquan, .related-news, .list-news, .ads, .banner, "
        ".social, .share, .comment, .newsletter, .recommendation"
    ):
        bad.decompose()
    # Captions are collected separately as image metadata, not merged into article body.
    for figure in cloned.select("figure, .tplCaption, .fig-picture"):
        figure.decompose()

    parts = []
    for node in cloned.find_all(["h2", "h3", "h4", "p", "li", "blockquote"]):
        if node.find_parent(["p", "li", "h2", "h3", "h4", "blockquote"]):
            continue
        text = clean_text(node.get_text(" ", strip=True))
        if len(text) < 2:
            continue
        classes = " ".join(node.get("class", [])).lower()
        if any(term in classes for term in ("caption", "author", "credit", "related", "ads")):
            continue
        if _is_photo_credit_line(text):
            continue
        parts.append(text)

    if not parts:
        # Fallback while still avoiding obvious navigation/figure noise.
        for node in cloned.select("img, figure, .caption"):
            node.decompose()
        text = clean_text(cloned.get_text("\n", strip=True))
        return text
    return "\n\n".join(parts)




def _prepare_source_reference_text(text, max_chars=None):
    """Bound in-memory source context while keeping opening and final practical details."""
    text = (text or "").strip()
    limit = max_chars or MAX_SOURCE_BODY_CHARS
    if len(text) <= limit:
        return text
    # Guides often put practical details near the end; keep both introduction and ending.
    marker = "\n\n[... phần giữa đã lược bớt để giới hạn ngữ cảnh ...]\n\n"
    head_len = int((limit - len(marker)) * 0.68)
    tail_len = limit - len(marker) - head_len
    return text[:head_len].rstrip() + marker + text[-tail_len:].lstrip()


def extract_article_metadata(item):
    """Fetch article metadata and images; in smart mode extract body text in memory only.

    Body text is passed to the single writing AI call, but is not persisted to outputs/DB
    unless ALLOW_FULL_TEXT_STORAGE=true. If access is denied, use metadata with a clear
    low-confidence note; never bypass 401/403/429, paywalls, or TLS errors.
    """
    candidate_url = normalize_url(item.get("source_url", ""))
    if not candidate_url:
        raise ValueError("URL nguồn không hợp lệ")
    if item.get("allowed_domains") and not _url_allowed_for_source(candidate_url, item):
        raise ValueError("URL bài viết không thuộc domain đã cấu hình cho nguồn RSS")

    page_fetch_error = ""
    try:
        html = fetch(candidate_url, timeout=(5, 10), attempts=1, max_bytes=4 * 1024 * 1024, max_elapsed_seconds=20)
        soup = BeautifulSoup(html, "html.parser")
    except Exception as exc:
        # RSS provides enough metadata to queue a research draft; don't bypass 403/429/paywalls.
        page_fetch_error = f"{type(exc).__name__}: {clean_text(str(exc))[:180]}"
        soup = BeautifulSoup("", "html.parser")

    canonical_tag = soup.find("link", rel=lambda value: value and "canonical" in value)
    canonical_href = canonical_tag.get("href") if canonical_tag else ""
    canonical_candidate = normalize_url(urljoin(candidate_url, canonical_href)) if canonical_href else None
    article_url = candidate_url
    if canonical_candidate and (not item.get("allowed_domains") or _url_allowed_for_source(canonical_candidate, item)):
        article_url = canonical_candidate

    jsonld_nodes = _jsonld_article_nodes(soup)
    article_node = jsonld_nodes[0] if jsonld_nodes else {}

    title = meta(soup, "og:title", "twitter:title") or clean_text(article_node.get("headline", ""))
    if not title:
        h1 = soup.find("h1")
        title = clean_text(h1.get_text(" ", strip=True) if h1 else item.get("rss_title", ""))
    summary = meta(soup, "og:description", "description", "twitter:description")
    if not summary:
        summary = clean_text(article_node.get("description", "")) or item.get("rss_summary", "")
    published = meta(soup, "article:published_time", "pubdate") or clean_text(article_node.get("datePublished", "")) or item.get("rss_published_at", "")
    modified = meta(soup, "article:modified_time") or clean_text(article_node.get("dateModified", ""))
    meta_keywords = meta(soup, "keywords")
    source_publisher = meta(soup, "og:site_name") or item.get("source_name") or _source_domain(item, candidate_url)
    source_section = meta(soup, "article:section") or clean_text(article_node.get("articleSection", ""))
    if not source_section:
        source_section = clean_text(item.get("rss_categories"))[:200]
    if not meta_keywords:
        kw = article_node.get("keywords", [])
        meta_keywords = clean_text(kw)

    # Normalize all high-level metadata here so later slicing/concatenation only sees strings.
    title = clean_text(title)
    summary = clean_text(summary)
    published = clean_text(published)
    modified = clean_text(modified)
    meta_keywords = clean_text(meta_keywords)
    source_publisher = clean_text(source_publisher)
    source_section = clean_text(source_section)

    page_lang = clean_text(soup.html.get("lang", "")) if soup.html else ""
    declared_language = str(item.get("source_language", "en")).lower().split("-")[0]
    html_language = page_lang.lower().replace("_", "-").split("-")[0]
    if html_language and html_language != "en":
        raise ValueError(f"Bỏ qua trang không phải tiếng Anh theo html lang={page_lang}")

    body_container = _find_article_container(soup)
    photo_footer_credit = _extract_article_footer_photo_credit(body_container)
    images = _extract_article_images(body_container, article_url, soup, photo_footer_credit)
    if not images and item.get("rss_image_url"):
        images = [{
            "image_id": "IMG_01", "url": urljoin(article_url, item["rss_image_url"]),
            "alt": "", "caption": "", "credit": None, "credit_source": None,
            "position_index": 1, "position_ratio": 0.0, "nearby_heading": "",
            "rights_status": "unverified", "source_page_url": article_url,
            "placement_source": "rss_image_fallback",
        }]

    source_body = ""
    if SOURCE_CONTEXT_MODE == "smart" and not page_fetch_error and body_container:
        try:
            source_body = _prepare_source_reference_text(
                _extract_body_text(body_container), MAX_SOURCE_BODY_CHARS
            )
        except Exception as exc:
            log.warning("Không trích được phần nội dung chính %s: %s", article_url, clean_text(str(exc))[:180])
            source_body = ""
    # Some blogs expose Article.articleBody in JSON-LD even when the visible DOM selector
    # differs. Use it only as temporary context; do not persist its original wording.
    if SOURCE_CONTEXT_MODE == "smart" and not page_fetch_error and len(source_body) < 300:
        jsonld_body = article_node.get("articleBody") if isinstance(article_node, dict) else ""
        if isinstance(jsonld_body, str) and len(clean_text(jsonld_body)) >= 300:
            source_body = _prepare_source_reference_text(clean_text(jsonld_body), MAX_SOURCE_BODY_CHARS)
    if source_body and len(source_body) >= 300:
        extraction_status = "source_body_extracted_in_memory"
        log.info("Source context extracted: source=%s chars=%s images=%s", _source_domain(item, article_url), len(source_body), len(images))
    else:
        source_body = ""
        extraction_status = "feed_fallback" if page_fetch_error else (
            "body_extraction_short" if SOURCE_CONTEXT_MODE == "smart" else "metadata_only_no_body_extracted"
        )
        if SOURCE_CONTEXT_MODE == "smart":
            log.warning("Thiếu thân bài đủ dài; sẽ viết ngắn từ metadata và đánh dấu cần kiểm chứng: %s", article_url)

    if not title:
        raise ValueError("RSS/trang nguồn không cung cấp tiêu đề bài viết")
    if not summary:
        summary = ""

    # Metadata-only is the default and stays enforced for this multi-source project.
    result = {
        "source_url": article_url,
        "discovered_url": candidate_url,
        "source_title": title[:500],
        "source_summary": clean_text(summary)[:1800],
        "published_at": published[:120] or None,
        "source_modified_at": modified[:120] or None,
        "source_publisher": source_publisher[:160] or None,
        "source_section": source_section[:200] or None,
        "source_meta_keywords": meta_keywords[:1000] or None,
        "source_images": images,
        "source_images_json": json.dumps(images, ensure_ascii=False),
        "source_image_url": next((x.get("url") for x in images if x.get("url")), None),
        "image_credit": next((x.get("credit") for x in images if x.get("credit")), None),
        "image_credit_url": None,
        "source_body": source_body,
        "source_body_chars": len(source_body),
        "content_extraction_status": extraction_status,
        "metadata_fetch_error": page_fetch_error or None,
        "title_key": title_key(title),
        "published_day": normalize_published_day(published),
        "source_id": item.get("source_id", ""),
        "source_name": item.get("source_name") or source_publisher,
        "source_domain": item.get("source_domain") or _source_domain(item, article_url),
        "source_language": item.get("source_language") or declared_language or "en",
        "source_feed_url": item.get("source_feed_url", ""),
        "source_focus": item.get("source_focus", []),
        "permission_status": item.get("permission_status", "review_terms_before_commercial_reuse"),
        "rss_categories": item.get("rss_categories", []),
    }
    result.update(classify_article(result, item))
    return result

FACT_EXTRACTION_INSTRUCTIONS = """
Bạn là chuyên viên kiểm chứng dữ kiện báo chí. Đọc toàn bộ nội dung bài nguồn chỉ để lập một hồ sơ dữ kiện,
không viết lại bài báo, không tóm tắt theo từng đoạn, không trích nguyên câu và không giữ nguyên cách diễn đạt.

Chỉ ghi các thông tin có căn cứ trong nguồn: ai, việc gì, ở đâu, khi nào, con số/ngày tháng, lời nhận định được gán cho ai,
khuyến cáo/cảnh báo được bài nguồn nêu, diễn biến và các điểm còn thiếu. Phân biệt факт được tường thuật với ý kiến,
cáo buộc hoặc nhận định. Không bổ sung tri thức ngoài đầu vào. Nếu thông tin là quan điểm của một người, trường attribution
phải ghi rõ người/tổ chức được nguồn gán phát biểu; nếu không rõ thì ghi "Nguồn không nêu rõ".

Mỗi fact phải là một ghi chú ngắn, tối đa khoảng 25 từ tiếng Việt, không phải câu văn sao chép từ bài nguồn. Không tạo câu trích dẫn.
Nếu nguồn không đủ dữ kiện, trả fewer facts và liệt kê nội dung cần xác minh. Không bịa hoặc suy diễn.

Trả về JSON object duy nhất:
{
  "facts": [
    {"id":"F1","fact":"ghi chú dữ kiện ngắn","category":"event/person/date/location/number/claim/official_advisory/opinion/other","attribution":"ai là nguồn của thông tin hoặc nhận định","certainty":"reported/attributed/unclear"}
  ],
  "unknowns": ["điểm chưa rõ cần xác minh"],
  "brief": "một câu mô tả trung tính về sự kiện"
}
Không dùng Markdown fence. Không đưa lại toàn văn hoặc đoạn dài của nguồn.
""".strip()


def _ai_instructions_and_input(article):
    """Build one-pass writer input with temporary article context when available."""
    fact_sheet = article.get("source_fact_sheet") or {}
    source_reference = _prepare_source_reference_text(article.get("source_body", ""), MAX_SOURCE_BODY_CHARS)
    body_available = len(source_reference) >= 300
    input_data = {
        "source_title": article.get("source_title", ""),
        "source_meta_description": article.get("source_summary", ""),
        "source_published_at": article.get("published_at") or "Không xác định",
        "source_publisher": article.get("source_publisher") or "Không xác định",
        "source_name": article.get("source_name") or article.get("source_publisher") or "Không xác định",
        "source_domain": article.get("source_domain") or "Không xác định",
        "source_language": article.get("source_language") or "en",
        "source_section": article.get("source_section") or "Không xác định",
        "destination_country_hint": article.get("destination_country") or "World / Chưa phân loại",
        "destination_city_hint": article.get("destination_city") or "",
        "destination_status": article.get("destination_status") or "needs_review",
        "primary_site_category_hint": article.get("primary_category") or "travel-guide",
        "all_site_categories_hint": article.get("topic_categories") or ["travel-guide"],
        "source_metadata_keywords": article.get("source_meta_keywords") or "",
        "source_content_mode": "source_body_reference" if body_available else ("metadata_only" if fact_sheet.get("metadata_only") or SOURCE_CONTEXT_MODE == "metadata_only" else "metadata_fallback"),
        "source_url": article.get("source_url", ""),
        "structured_fact_sheet": fact_sheet,
        # Temporary reference context: excluded from output JSON and SQLite by default.
        # Writer must extract verifiable facts and compose an independent article, not translate or paraphrase paragraph-by-paragraph.
        "source_reference_material": source_reference if body_available else "",
        "source_reference_chars": len(source_reference),
        "source_reference_truncated": bool(body_available and len((article.get("source_body") or "")) > len(source_reference)),
        "inline_image_catalog": [
            {
                "image_id": item.get("image_id") or f"IMG_{index:02d}",
                "alt": item.get("alt", ""),
                "caption": item.get("caption", ""),
                "photo_credit": item.get("credit", ""),
                "source_position_ratio": item.get("position_ratio", 0),
                "nearby_source_heading": item.get("nearby_heading", ""),
            }
            for index, item in enumerate((article.get("source_images") or []), start=1)
            if isinstance(item, dict)
        ],
    }
    instructions = """
Bạn là biên tập viên cấp cao của một trang nội dung du lịch tiếng Việt.
Hãy viết một bài biên tập độc lập bằng tiếng Việt từ hồ sơ metadata, danh mục ảnh và TƯ LIỆU THAM KHẢO nếu có.
Nếu input có source_reference_material, hãy dùng nó để lấy các dữ kiện có thể kiểm tra (địa điểm, đặc điểm, lịch trình, điều kiện, lưu ý, số liệu và nguồn quy định), nhưng tuyệt đối không dịch nguyên văn hoặc diễn đạt lại theo từng đoạn.

NGUYÊN TẮC NGUYÊN GỐC
- Không viết lại từng đoạn của bài nguồn, không mô phỏng thứ tự đoạn/tiêu đề/cấu trúc của bài gốc và không thay từ đồng nghĩa để tái tạo câu chữ.
- Dùng dữ kiện như chất liệu báo chí; tự xây dựng cấu trúc và góc biên tập phù hợp, không tối ưu để né công cụ phát hiện trùng lặp.
- Không thêm dữ kiện chỉ vì nó thường đúng trong các bài du lịch. Nếu dữ kiện không có trong hồ sơ, không khẳng định nó như sự thật.
- Không biến ý kiến, cáo buộc hoặc phản ứng dư luận thành sự thật đã được xác minh; phải nêu rõ chủ thể đưa ra nhận định.

GIỌNG VĂN
- Tiếng Việt chuẩn, chuyên nghiệp, tự nhiên, rõ ngôi kể.
- Tin tức dùng ngôi thứ ba, giọng khách quan; không xưng “tôi/chúng tôi”.
- Không tạo tên tác giả bài AI và không thêm dòng tên tác giả nguồn ở cuối bài.
- Tránh câu sáo rỗng, khuyến nghị chung chung, lặp ý hoặc kéo dài bài bằng suy đoán.

SEO
- Tiêu đề SEO chính xác và có ích, không giật tít quá mức.
- Meta description đúng nội dung.
- Chọn một từ khóa chính và 3–6 từ khóa phụ liên quan thực sự.
- Nội dung website dùng taxonomy theo quốc gia và chủ đề. Hãy ưu tiên destination_country_hint / destination_city_hint / primary_site_category_hint đã cung cấp; nếu đang là "World / Chưa phân loại" thì không tự gán quốc gia khi không có căn cứ.
- Nếu source_content_mode=source_body_reference: sử dụng source_reference_material như tài liệu tham khảo để xác định dữ kiện và chủ đề; không sao chép câu, không giữ nguyên thứ tự đoạn/heading và không làm bản dịch sát nghĩa. Tự thiết kế cấu trúc theo nhu cầu độc giả Việt Nam.
- Nếu source_content_mode=metadata_only hoặc metadata_fallback: chỉ dùng title, description, ngày/chuyên mục, từ khóa metadata và ảnh; dữ kiện hạn chế thì chỉ viết bản nháp ngắn và đánh dấu cần bổ sung thông tin.
- Bài có sapo, h2/h3 hợp lý và kết luận tự nhiên. Khi source_reference_material đủ thông tin, mục tiêu khoảng 600–1000 từ cho hướng dẫn du lịch, có các phần thực dụng như cách di chuyển, giấy tờ/điều kiện, chi phí nếu nguồn nêu, lịch trình, điểm cần lưu ý; không tự bịa giá/số liệu/thông tin hiện hành.
- Với chế độ metadata-only, không biến caption ảnh thành bằng chứng chắc chắn về sự kiện; coi caption là gợi ý ngữ cảnh ảnh và ghi cần kiểm tra nếu dùng làm dữ kiện.
- Nếu inline_image_catalog có ảnh, hãy chèn marker [[IMAGE:IMG_01]] (đúng ID có trong catalog) thành một đoạn riêng tại vị trí hợp ngữ cảnh trong content_html, ví dụ sau đoạn đang nói về ngôi làng/nghề thủ công/người được chụp. Giữ thứ tự ảnh nguồn nếu hợp lý; không dồn tất cả ảnh lên đầu. Không tự tạo ID ảnh.
- Marker chỉ là điểm đặt ảnh; chương trình sẽ thay marker bằng HTML ảnh có kiểm soát quyền sử dụng hoặc placeholder duyệt quyền.
- HTML văn bản chỉ dùng p, h2, h3, ul, ol, li, strong, em và marker ảnh dạng văn bản. Không tự tạo thẻ img/figure, script, iframe, style hoặc URL ảnh.

KIỂM CHỨNG
- Chỉ sử dụng hồ sơ dữ kiện, metadata nguồn và các suy luận biên tập không làm phát sinh sự kiện mới.
- Khi có source_reference_material, không dùng số lượng fact metadata để kết luận rằng dữ kiện quá ít; hãy đọc nguồn tham khảo và tự tổng hợp các ý chính hợp lệ. Khi chỉ có metadata, ưu tiên bài ngắn.
- Liệt kê các điều cần kiểm chứng độc lập trong fact_check_notes.
- Không nói rằng AI đã kiểm chứng độc lập.
- Nguồn bài báo gốc sẽ được hiển thị riêng ngoài thân bài. Không thêm tên tác giả hoặc credit ảnh vào cuối bài.

Trả về DUY NHẤT JSON object hợp lệ gồm:
{
  "seo_title":"string",
  "meta_description":"string",
  "primary_keyword":"string",
  "secondary_keywords":["string"],
  "editorial_angle":"string",
  "content_html":"string",
  "source_facts_used":["string"],
  "fact_check_notes":"string"
}
Không bọc JSON trong Markdown code fence.
""".strip()
    return instructions, input_data


def _load_json_object(raw, provider, purpose):
    """Parse a provider's JSON, tolerating Markdown fences or short preambles.

    Some OpenRouter free models ignore JSON mode and wrap the object in prose or
    a code fence. Extracting the first valid JSON object is safer than failing on
    harmless wrappers. Empty provider output is reported explicitly.
    """
    text = (raw or "").strip()
    if not text:
        raise ValueError(f"{provider} trả nội dung rỗng ở bước {purpose}; API có thể kết thúc không tạo text")

    # Remove a common fenced JSON wrapper.
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE).strip()
    text = re.sub(r"\s*```$", "", text).strip()
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass

    # Find a valid JSON object even if a model adds a short preamble/postamble.
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            data, _end = decoder.raw_decode(text[index:])
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            continue

    preview = clean_text(text[:180])
    raise ValueError(
        f"{provider} không trả JSON object hợp lệ ở bước {purpose}. "
        f"Phản hồi bắt đầu bằng: {preview or '(trống sau khi làm sạch)'}"
    )


def _parse_source_fact_sheet(raw, provider):
    data = _load_json_object(raw, provider, "fact-extraction")

    raw_facts = data.get("facts", [])
    if not isinstance(raw_facts, list):
        raise ValueError(f"{provider} trả facts không đúng định dạng")

    facts = []
    for idx, item in enumerate(raw_facts[:20], start=1):
        if isinstance(item, str):
            fact = clean_text(item)
            category, attribution, certainty = "other", "Nguồn bài viết", "reported"
        elif isinstance(item, dict):
            fact = clean_text(item.get("fact") or item.get("statement") or "")
            category = clean_text(item.get("category", "other"))[:40]
            attribution = clean_text(item.get("attribution", "Nguồn bài viết"))[:180]
            certainty = clean_text(item.get("certainty", "reported"))[:40]
        else:
            continue
        if not fact:
            continue
        facts.append({
            "id": clean_text(item.get("id", f"F{idx}"))[:12] if isinstance(item, dict) else f"F{idx}",
            "fact": fact[:300],
            "category": category or "other",
            "attribution": attribution or "Nguồn bài viết",
            "certainty": certainty or "reported",
        })

    if len(facts) < 3:
        raise ValueError(f"{provider} trích được dưới 3 dữ kiện hữu ích; không tạo bài dài từ nguồn quá ít thông tin")
    unknowns = data.get("unknowns", [])
    if not isinstance(unknowns, list):
        unknowns = []
    return {
        "facts": facts,
        "unknowns": [clean_text(x)[:250] for x in unknowns[:12] if isinstance(x, str) and clean_text(x)],
        "brief": clean_text(data.get("brief", ""))[:400],
    }

def _parse_and_validate_ai_draft(raw, provider):
    data = _load_json_object(raw, provider, "article-writing")

    seo_title = clean_text(data.get("seo_title", ""))
    content = data.get("content_html", "")
    if not seo_title or not content:
        raise ValueError(f"{provider} không trả đủ seo_title/content_html")
    if not isinstance(content, str):
        raise ValueError(f"{provider} trả content_html không hợp lệ")
    if re.search(r"<\s*(script|iframe|object|embed|style)\b", content, re.I):
        raise ValueError(f"{provider} trả HTML không an toàn")

    # Chỉ cho phép một tập thẻ HTML cơ bản. Website vẫn phải sanitize trước xuất bản.
    allowed_tags = {"p", "h2", "h3", "ul", "ol", "li", "strong", "em"}
    soup = BeautifulSoup(content, "html.parser")
    for tag in list(soup.find_all(True)):
        if tag.name not in allowed_tags:
            tag.unwrap()
        else:
            for attr in list(tag.attrs):
                del tag.attrs[attr]
    content = str(soup)

    secondary = data.get("secondary_keywords", [])
    facts = data.get("source_facts_used", [])
    if not isinstance(secondary, list):
        secondary = []
    if not isinstance(facts, list):
        facts = []

    return {
        "seo_title": seo_title[:200],
        "seo_description": clean_text(data.get("meta_description", ""))[:500],
        "seo_content": content[:30000],
        "primary_keyword": clean_text(data.get("primary_keyword", ""))[:150],
        "secondary_keywords": json.dumps(
            [clean_text(x)[:100] for x in secondary[:8] if isinstance(x, str) and clean_text(x)],
            ensure_ascii=False,
        ),
        "editorial_angle": clean_text(data.get("editorial_angle", ""))[:500],
        "source_facts_used": json.dumps(
            [clean_text(x)[:300] for x in facts[:12] if isinstance(x, str) and clean_text(x)],
            ensure_ascii=False,
        ),
        "fact_check_notes": clean_text(data.get("fact_check_notes", ""))[:1800],
        "ai_provider": provider,
    }


def _call_gemini(instructions, input_data):
    from google import genai
    from google.genai import types

    # Explicit timeout + bounded retry policy prevents the SDK's default
    # exponential backoff from holding the pipeline for minutes before fallback.
    http_options = types.HttpOptions(
        timeout=GEMINI_TIMEOUT_MS,
        retry_options=types.HttpRetryOptions(attempts=GEMINI_RETRY_ATTEMPTS),
    )
    client = genai.Client(api_key=GEMINI_API_KEY, http_options=http_options)
    prompt = instructions + "\n\nDỮ LIỆU ĐẦU VÀO:\n" + json.dumps(input_data, ensure_ascii=False)
    config_args = {
        "response_mime_type": "application/json",
        "temperature": 0.3,
        "max_output_tokens": AI_MAX_OUTPUT_TOKENS,
        "thinking_config": types.ThinkingConfig(thinking_level=GEMINI_THINKING_LEVEL),
        # This workflow does not define tools; disable AFC explicitly rather than
        # initializing its automatic-call machinery for normal text generation.
        "automatic_function_calling": types.AutomaticFunctionCallingConfig(disable=True),
    }
    log.info(
        "Gemini request config model=%s thinking=%s timeout=%.0fs retries=%s",
        GEMINI_MODEL, GEMINI_THINKING_LEVEL,
        GEMINI_TIMEOUT_MS / 1000.0, GEMINI_RETRY_ATTEMPTS,
    )
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(**config_args),
    )
    return response.text or ""


def _call_openai(instructions, input_data):
    from openai import OpenAI

    client = OpenAI(api_key=OPENAI_API_KEY, timeout=float(AI_PROVIDER_TIMEOUT_SECONDS), max_retries=0)
    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": instructions},
            {"role": "user", "content": json.dumps(input_data, ensure_ascii=False)},
        ],
        response_format={"type": "json_object"},
        temperature=0.4,
        max_tokens=AI_MAX_OUTPUT_TOKENS,
    )
    return response.choices[0].message.content or ""


def _call_groq(instructions, input_data):
    """Call Groq via its OpenAI-compatible endpoint, using a distinct GROQ_API_KEY."""
    from openai import OpenAI

    client = OpenAI(
        api_key=GROQ_API_KEY,
        base_url="https://api.groq.com/openai/v1",
        timeout=float(AI_PROVIDER_TIMEOUT_SECONDS),
        max_retries=0,
    )
    response = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": instructions},
            {"role": "user", "content": json.dumps(input_data, ensure_ascii=False)},
        ],
        response_format={"type": "json_object"},
        temperature=0.3,
        max_completion_tokens=AI_MAX_OUTPUT_TOKENS,
    )
    if not response.choices:
        raise ValueError("Groq trả về 0 choices")
    content = response.choices[0].message.content or ""
    if not content.strip():
        reason = getattr(response.choices[0], "finish_reason", None) or "unknown"
        raise ValueError(f"Groq trả nội dung rỗng (finish_reason={reason})")
    return content


def _call_openrouter(instructions, input_data):
    from openai import OpenAI

    client = OpenAI(
        api_key=OPENROUTER_API_KEY,
        base_url="https://openrouter.ai/api/v1",
        timeout=float(AI_PROVIDER_TIMEOUT_SECONDS),
        max_retries=0,
        default_headers={
            "HTTP-Referer": OPENROUTER_SITE_URL,
            "X-Title": OPENROUTER_APP_NAME,
        },
    )
    response = client.chat.completions.create(
        model=OPENROUTER_MODEL,
        messages=[
            {"role": "system", "content": instructions},
            {"role": "user", "content": json.dumps(input_data, ensure_ascii=False)},
        ],
        temperature=0.4,
        max_tokens=AI_MAX_OUTPUT_TOKENS,
    )
    if not response.choices:
        raise ValueError("OpenRouter trả về 0 choices")
    choice = response.choices[0]
    message = choice.message
    content = message.content or ""
    # Some compatible/free model routes can return an empty content field even
    # with HTTP 200. Include finish reason so fallback logs explain the failure.
    if isinstance(content, list):
        content = "".join(
            str(part.get("text", "")) if isinstance(part, dict) else str(getattr(part, "text", ""))
            for part in content
        )
    content = str(content or "").strip()
    if not content:
        finish_reason = getattr(choice, "finish_reason", None) or "unknown"
        refusal = clean_text(getattr(message, "refusal", "") or "")[:120]
        raise ValueError(
            f"OpenRouter trả nội dung rỗng (finish_reason={finish_reason}, max_tokens={AI_MAX_OUTPUT_TOKENS}"
            + (f", refusal={refusal}" if refusal else "")
            + "). Đầu ra có thể đã bị cắt; tăng AI_MAX_OUTPUT_TOKENS hoặc đổi sang model ổn định hơn."
        )
    return content


def _configured_ai_providers(instructions, input_data):
    """Order: Gemini -> real OpenAI key (if configured) -> Groq -> OpenRouter."""
    providers = []
    if GEMINI_API_KEY:
        providers.append(("Gemini", lambda: _call_gemini(instructions, input_data)))
    if OPENAI_API_KEY:
        providers.append(("OpenAI", lambda: _call_openai(instructions, input_data)))
    if GROQ_API_KEY:
        providers.append(("Groq", lambda: _call_groq(instructions, input_data)))
    if OPENROUTER_API_KEY:
        providers.append(("OpenRouter", lambda: _call_openrouter(instructions, input_data)))
    return providers


def _call_json_with_fallback(stage_name, instructions, input_data, validator):
    providers = _configured_ai_providers(instructions, input_data)
    if not providers:
        raise RuntimeError(
            "Chưa cấu hình AI. Cần GEMINI_API_KEY, OPENAI_API_KEY, GROQ_API_KEY hoặc OPENROUTER_API_KEY."
        )
    errors = []
    for provider_name, request_fn in providers:
        started = time.monotonic()
        if provider_name == "Gemini":
            log.info(
                "AI stage=%s provider=%s starting (thinking=%s, timeout=%.0fs, retries=%s)",
                stage_name, provider_name, GEMINI_THINKING_LEVEL,
                GEMINI_TIMEOUT_MS / 1000.0, GEMINI_RETRY_ATTEMPTS,
            )
        else:
            log.info("AI stage=%s provider=%s starting", stage_name, provider_name)
        try:
            raw = request_fn()
            result = validator(raw, provider_name)
            elapsed = time.monotonic() - started
            log.info("AI stage=%s provider=%s elapsed=%.1fs", stage_name, provider_name, elapsed)
            fallback_reason = ""
            if errors:
                failed_names = ", ".join(x.split(":", 1)[0] for x in errors)
                fallback_reason = f"{failed_names} gặp lỗi/quota; chuyển sang {provider_name} ở bước {stage_name}."
                log.warning("AI fallback stage=%s: %s", stage_name, fallback_reason)
            return result, provider_name, fallback_reason
        except Exception as exc:
            elapsed = time.monotonic() - started
            message = clean_text(str(exc))[:200]
            errors.append(f"{provider_name}: {type(exc).__name__}: {message}")
            log.warning(
                "AI stage=%s provider=%s failed elapsed=%.1fs error=%s: %s",
                stage_name, provider_name, elapsed, type(exc).__name__, message,
            )
    raise RuntimeError(f"Tất cả AI provider thất bại ở bước {stage_name}: " + " | ".join(errors))


def _image_list_from_article(article):
    images = article.get("source_images") or []
    if not images and article.get("source_images_json"):
        try:
            images = json.loads(article["source_images_json"])
        except (TypeError, json.JSONDecodeError):
            images = []
    normalized = []
    for index, image in enumerate(images, start=1):
        if not isinstance(image, dict) or not image.get("url"):
            continue
        item = dict(image)
        item.setdefault("image_id", f"IMG_{index:02d}")
        item.setdefault("position_ratio", (index - 1) / max(1, len(images) - 1))
        item.setdefault("rights_status", "unverified")
        normalized.append(item)
    return normalized


def _render_inline_image_html(image):
    """Render an inline image only when operator has confirmed reuse rights.

    Without confirmation, keep a positioned editorial placeholder containing the
    image details. Missing photo credit does not mean the image is public domain.
    """
    image_id = clean_text(image.get("image_id", "IMG"))
    caption = clean_text(image.get("caption", ""))
    credit = clean_text(image.get("credit", ""))
    source_url = clean_text(image.get("url", ""))
    source_page = clean_text(image.get("source_page_url", ""))
    alt = clean_text(image.get("alt", "")) or caption or "Ảnh minh họa"

    if SOURCE_IMAGE_REUSE_AUTHORIZED:
        if not source_url.startswith(("https://", "http://")):
            return f"<figure><figcaption>[{html_escape(image_id)} — URL ảnh không hợp lệ, cần kiểm tra]</figcaption></figure>"
        caption_parts = []
        if caption:
            caption_parts.append(html_escape(caption))
        if credit:
            caption_parts.append("Ảnh: " + html_escape(credit))
        else:
            source_name = clean_text(image.get("source_name") or "nguồn tham khảo")
            caption_parts.append("Nguồn ảnh: " + html_escape(source_name) + "; chưa xác định người chụp")
        if source_page:
            caption_parts.append(f'<a href="{html_escape(source_page, quote=True)}" rel="nofollow">Nguồn</a>')
        figcaption = "<figcaption>" + " · ".join(caption_parts) + "</figcaption>" if caption_parts else ""
        return (
            '<figure class="article-inline-image">'
            f'<img src="{html_escape(source_url, quote=True)}" alt="{html_escape(alt, quote=True)}" loading="lazy" />'
            f'{figcaption}</figure>'
        )

    # Safe by default: retain the inline slot, credit and URL for editorial review,
    # but don't make an unlicensed remote image ready to publish as if permission existed.
    detail = [f"Vị trí ảnh {image_id}: chờ xác nhận quyền sử dụng"]
    if caption:
        detail.append("Caption: " + caption)
    if credit:
        detail.append("Credit ảnh: " + credit)
    else:
        detail.append("Credit ảnh: chưa xác định")
    if source_url:
        detail.append("URL tham khảo: " + source_url)
    return '<figure class="image-rights-review"><figcaption>[' + html_escape(" · ".join(detail)) + ']</figcaption></figure>'


def _insert_inline_images(article, draft):
    """Replace model image markers with inline HTML; fallback to source-relative positions.

    This only prepares article HTML. Actual source images are embedded only when
    SOURCE_IMAGE_REUSE_AUTHORIZED=true is explicitly set by the operator.
    """
    images = _image_list_from_article(article)
    content = draft.get("seo_content", "") or ""
    if not images or not content:
        return draft
    source_display_name = article.get("source_name") or article.get("source_publisher") or article.get("source_domain") or "nguồn tham khảo"
    for image in images:
        image.setdefault("source_name", source_display_name)

    soup = BeautifulSoup(content, "html.parser")
    placed_ids = set()
    by_id = {image["image_id"]: image for image in images}

    # Markers should occupy their own paragraph, to avoid invalid nested figure/p tags.
    for paragraph in list(soup.find_all("p")):
        text = clean_text(paragraph.get_text(" ", strip=True))
        match = re.fullmatch(r"\[\[IMAGE:(IMG_\d{2})\]\]", text)
        if not match:
            continue
        image_id = match.group(1)
        image = by_id.get(image_id)
        if not image or image_id in placed_ids:
            paragraph.decompose()
            continue
        replacement = BeautifulSoup(_render_inline_image_html(image), "html.parser")
        paragraph.replace_with(replacement)
        placed_ids.add(image_id)

    # Remove stray/malformed markers (for example if the model placed a marker inside prose);
    # the fallback below will still place each image exactly once.
    for text_node in list(soup.find_all(string=re.compile(r"\[\[IMAGE:IMG_\d{2}\]\]"))):
        cleaned = re.sub(r"\[\[IMAGE:IMG_\d{2}\]\]", "", str(text_node))
        if cleaned:
            text_node.replace_with(cleaned)
        else:
            parent = text_node.parent
            if parent and parent.name == "p" and not clean_text(parent.get_text(" ", strip=True)):
                parent.decompose()
            else:
                text_node.extract()

    # If the model omitted markers, insert those images based on their position in source.
    # That keeps ordering/layout without forcing all images to the beginning.
    missing = [item for item in images if item["image_id"] not in placed_ids]
    for image in missing:
        blocks = soup.find_all(["p", "h2", "h3", "ul", "ol", "blockquote"])
        if blocks:
            ratio = float(image.get("position_ratio", 0.5) or 0.0)
            target_index = min(len(blocks) - 1, max(0, round(ratio * (len(blocks) - 1))))
            target = blocks[target_index]
            target.insert_after(BeautifulSoup(_render_inline_image_html(image), "html.parser"))
        else:
            soup.append(BeautifulSoup(_render_inline_image_html(image), "html.parser"))
        placed_ids.add(image["image_id"])

    draft["seo_content"] = "".join(str(child) for child in soup.contents)
    draft["inline_images"] = json.dumps(
        [{
            "image_id": item["image_id"],
            "position_ratio": item.get("position_ratio", 0),
            "nearby_heading": item.get("nearby_heading", ""),
            "credit": item.get("credit"),
            "credit_source": item.get("credit_source"),
            "rights_status": "confirmed_by_operator" if SOURCE_IMAGE_REUSE_AUTHORIZED else "unverified_placeholder",
            "url": item.get("url"),
        } for item in images], ensure_ascii=False
    )
    log.info(
        "Inline images prepared: %s | embedding_authorized=%s",
        len(placed_ids), SOURCE_IMAGE_REUSE_AUTHORIZED,
    )
    return draft



def _build_metadata_fact_sheet(article):
    """Build a lightweight, deterministic fact sheet without another AI call.

    This does not claim to have read/verified the source body. It preserves only
    page metadata and image-caption clues so the writer can create a concise draft.
    """
    facts = []

    def add_fact(text, category="other", attribution="metadata trang nguồn", certainty="reported"):
        text = clean_text(text)
        if not text:
            return
        # Limit each fact so a long description/caption doesn't become a body-text archive.
        facts.append({
            "id": f"M{len(facts) + 1}",
            "fact": text[:500],
            "category": category,
            "attribution": attribution[:180],
            "certainty": certainty,
        })

    title = clean_text(article.get("source_title", ""))
    summary = clean_text(article.get("source_summary", ""))
    published = clean_text(article.get("published_at", ""))
    section = clean_text(article.get("source_section", ""))
    keywords = clean_text(article.get("source_meta_keywords", ""))

    if title:
        add_fact(f"Tiêu đề metadata của nguồn nêu chủ đề: {title}", "other", "Tiêu đề metadata của nguồn")
    if summary:
        add_fact(f"Mô tả metadata của nguồn: {summary}", "claim", "Meta description/RSS summary của nguồn", "attributed")
    if published:
        add_fact(f"Ngày đăng được metadata ghi nhận: {published}", "date", "Metadata của trang nguồn")
    if section:
        add_fact(f"Chuyên mục nguồn: {section}", "other", "Metadata/breadcrumb của trang nguồn")

    images = article.get("source_images") or []
    if not images and article.get("source_images_json"):
        try:
            decoded = json.loads(article["source_images_json"])
            images = decoded if isinstance(decoded, list) else []
        except (TypeError, json.JSONDecodeError):
            images = []
    for image in images[:8]:
        if not isinstance(image, dict):
            continue
        image_id = clean_text(image.get("image_id", "ảnh"))
        caption = clean_text(image.get("caption", ""))
        alt = clean_text(image.get("alt", ""))
        nearby_heading = clean_text(image.get("nearby_heading", ""))
        if caption:
            add_fact(f"Caption {image_id}: {caption}", "other", "Caption ảnh nguồn; cần kiểm chứng nếu nêu thành sự kiện", "unclear")
        elif alt:
            add_fact(f"Alt text {image_id}: {alt}", "other", "Alt text ảnh nguồn; chỉ dùng làm gợi ý", "unclear")
        if nearby_heading:
            add_fact(f"Heading gần ảnh {image_id}: {nearby_heading}", "other", "Heading DOM gần ảnh; không phải xác minh độc lập", "unclear")

    # Keywords are SEO hints, never treated as factual evidence.
    unknowns = [
        "Chế độ metadata-only: thân bài nguồn không được trích xuất. Các chi tiết, diễn biến, lời dẫn, số liệu và cảnh báo chưa có trong metadata phải được kiểm chứng độc lập.",
    ]
    if not summary:
        unknowns.append("Nguồn không cung cấp meta description/RSS summary hữu ích; chỉ có thể viết nội dung ngắn dựa trên tiêu đề và dữ liệu ảnh.")
    return {
        "facts": facts[:16],
        "unknowns": unknowns[:12],
        "brief": summary[:400] or title[:400],
        "metadata_only": True,
        "metadata_keywords_hint": keywords[:1000],
    }


def create_ai_draft(article):
    """Generate an original Vietnamese draft in one AI call using in-memory source context.

    Existing metadata-only fact sheets are reused for provenance, but they do not block
    refreshed body extraction. Source article text is temporary and excluded from bundle/DB
    by default; a writer failure can retry by fetching the URL again.
    """
    facts = article.get("source_fact_sheet")
    if not isinstance(facts, dict) and article.get("source_fact_sheet_json"):
        try:
            loaded_facts = json.loads(article["source_fact_sheet_json"])
            if isinstance(loaded_facts, dict):
                facts = loaded_facts
                article["source_fact_sheet"] = loaded_facts
        except (TypeError, json.JSONDecodeError):
            facts = None

    source_body = (article.get("source_body") or "").strip()
    body_available = SOURCE_CONTEXT_MODE == "smart" and len(source_body) >= 300
    fact_fallback = clean_text(article.get("source_fact_fallback_reason", ""))

    # If we now have the article content but only an old metadata-only sheet, rebuild the
    # lightweight metadata sheet and remove the stale warning that incorrectly said there was no body.
    if body_available:
        if not isinstance(facts, dict) or facts.get("metadata_only") is True:
            facts = _build_metadata_fact_sheet(article)
        facts["metadata_only"] = False
        facts["source_body_available"] = True
        facts["source_body_chars"] = len(source_body)
        facts["unknowns"] = [
            "Cần biên tập viên kiểm tra các dữ kiện thay đổi theo thời gian (giá, giờ mở cửa, quy định nhập cảnh, tình hình an ninh) trước khi xuất bản."
        ]
        fact_provider = "source-body-reference (không gọi AI trích dữ kiện riêng)"
        article["source_fact_sheet"] = facts
        article["source_fact_sheet_json"] = json.dumps(facts, ensure_ascii=False)
        article["source_fact_provider"] = fact_provider
        log.info(
            "AI stage=fact-extraction skipped: body context available (%s chars); single writer call will use article reference",
            len(source_body),
        )
        # Checkpoint contains metadata/facts/images only; raw source body is excluded.
        paths = save_output_bundle(article, None, stage="source_context_ready")
        article.update(paths)
    else:
        reusable_facts = (
            isinstance(facts, dict)
            and isinstance(facts.get("facts"), list)
            and (len(facts.get("facts", [])) >= 3 or facts.get("metadata_only") is True)
        )
        if reusable_facts:
            log.info(
                "AI stage=fact-extraction skipped: no source body available; reusing fact sheet (%d facts; metadata_only=%s)",
                len(facts.get("facts", [])), bool(facts.get("metadata_only")),
            )
        else:
            facts = _build_metadata_fact_sheet(article)
            article["source_fact_sheet"] = facts
            article["source_fact_sheet_json"] = json.dumps(facts, ensure_ascii=False)
            log.info("AI stage=fact-extraction skipped: no source body available; falling back to metadata-only context")
        fact_provider = "metadata-only (không có thân bài khả dụng; không gọi AI trích dữ kiện riêng)"
        article["source_fact_sheet"] = facts
        article["source_fact_sheet_json"] = json.dumps(facts, ensure_ascii=False)
        article["source_fact_provider"] = fact_provider
        if not article.get("output_json_path"):
            paths = save_output_bundle(article, None, stage="metadata_ready")
            article.update(paths)

    instructions, input_data = _ai_instructions_and_input(article)
    draft, writer_provider, writer_fallback = _call_json_with_fallback(
        "article-writing", instructions, input_data,
        lambda raw, provider: _parse_and_validate_ai_draft(raw, provider),
    )
    draft = _insert_inline_images(article, draft)
    facts_used = [item["fact"] for item in (facts.get("facts", []) if isinstance(facts, dict) else [])[:12] if isinstance(item, dict) and item.get("fact")]
    draft["source_facts_used"] = json.dumps(facts_used, ensure_ascii=False)

    if body_available:
        providers_used = f"{writer_provider} (viết bài từ source context; 1 lượt AI, không trích dữ kiện riêng)"
    else:
        providers_used = f"{writer_provider} (viết bài từ metadata/fact sheet; thân bài nguồn không truy cập được)"
    draft["ai_provider"] = providers_used
    fallback_notes = [x for x in (fact_fallback, writer_fallback) if x]
    if fallback_notes:
        draft["ai_fallback_reason"] = " ".join(fallback_notes)[:1000]
    unknowns = facts.get("unknowns", []) if isinstance(facts, dict) else []
    if unknowns:
        unknown_note = "Cần xác minh thêm: " + "; ".join(clean_text(x) for x in unknowns[:6] if clean_text(x))
        current_note = clean_text(draft.get("fact_check_notes", ""))
        draft["fact_check_notes"] = (current_note + " " + unknown_note).strip()[:1800]
    log.info(
        "AI hoàn tất: %s; metadata_facts=%d; source_context_chars=%d",
        providers_used, len(facts.get("facts", [])) if isinstance(facts, dict) else 0, len(source_body),
    )
    return draft

def save(article, status, error_message=None):
    """Lưu bài đã xử lý và đánh dấu URL để các lần sau không gửi lại."""
    timestamp = now_iso()
    source_url = normalize_url(article["source_url"]) or article["source_url"]
    key = article.get("title_key") or title_key(article.get("source_title", ""))
    day = article.get("published_day") or normalize_published_day(article.get("published_at"))

    with sqlite3.connect(DATABASE_PATH, timeout=30) as conn:
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.execute("""
            INSERT INTO articles (
                source_url, source_title, source_summary, published_at, source_modified_at,
                source_image_url, image_credit, image_credit_url,
                source_author, source_publisher, source_section, source_meta_keywords, source_images_json,
                source_fact_sheet_json, source_body_chars, content_extraction_status, source_content,
                seo_title, seo_description, seo_content, primary_keyword,
                secondary_keywords, editorial_angle, fact_check_notes,
                source_facts_used, ai_provider, status, error_message, title_key,
                published_day, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_url) DO UPDATE SET
                source_title=excluded.source_title,
                source_summary=excluded.source_summary,
                published_at=excluded.published_at,
                source_modified_at=excluded.source_modified_at,
                source_image_url=excluded.source_image_url,
                image_credit=excluded.image_credit,
                image_credit_url=excluded.image_credit_url,
                source_author=excluded.source_author,
                source_publisher=excluded.source_publisher,
                source_section=excluded.source_section,
                source_meta_keywords=excluded.source_meta_keywords,
                source_images_json=excluded.source_images_json,
                source_fact_sheet_json=excluded.source_fact_sheet_json,
                source_body_chars=excluded.source_body_chars,
                content_extraction_status=excluded.content_extraction_status,
                source_content=COALESCE(excluded.source_content, articles.source_content),
                seo_title=excluded.seo_title,
                seo_description=excluded.seo_description,
                seo_content=excluded.seo_content,
                primary_keyword=excluded.primary_keyword,
                secondary_keywords=excluded.secondary_keywords,
                editorial_angle=excluded.editorial_angle,
                fact_check_notes=excluded.fact_check_notes,
                source_facts_used=excluded.source_facts_used,
                ai_provider=excluded.ai_provider,
                status=excluded.status,
                error_message=excluded.error_message,
                title_key=excluded.title_key,
                published_day=excluded.published_day,
                updated_at=excluded.updated_at
        """, (
            source_url, article["source_title"], article["source_summary"],
            article.get("published_at"), article.get("source_modified_at"), article.get("source_image_url"),
            article.get("image_credit"), article.get("image_credit_url"),
            article.get("source_author"), article.get("source_publisher"), article.get("source_section"),
            article.get("source_meta_keywords"),
            article.get("source_images_json") or json.dumps(article.get("source_images", []), ensure_ascii=False),
            article.get("source_fact_sheet_json"), article.get("source_body_chars"),
            article.get("content_extraction_status"),
            article.get("source_body") if (ALLOW_FULL_TEXT_STORAGE and SOURCE_CONTEXT_MODE == "smart") else None,
            article.get("seo_title"), article.get("seo_description"),
            article.get("seo_content"), article.get("primary_keyword"),
            article.get("secondary_keywords"), article.get("editorial_angle"),
            article.get("fact_check_notes"), article.get("source_facts_used"),
            article.get("ai_provider"), status, (error_message or "")[:1000] or None, key, day or None,
            timestamp, timestamp,
        ))
        conn.execute(
            """INSERT OR IGNORE INTO seen_sources
               (source_url,title_key,published_day,status,first_seen_at)
               VALUES(?,?,?,?,?)""",
            (source_url, key, day or None, status, timestamp),
        )
        discovered_url = normalize_url(article.get("discovered_url", ""))
        if discovered_url and discovered_url != source_url:
            conn.execute(
                """INSERT OR IGNORE INTO seen_sources
                   (source_url,title_key,published_day,status,duplicate_of,first_seen_at)
                   VALUES(?,?,?,?,?,?)""",
                (discovered_url, key, day or None, "canonical_alias", source_url, timestamp),
            )
        # Separate taxonomy index: retains source/country/topic classifications without changing legacy articles table shape.
        conn.execute("""
            INSERT INTO article_taxonomy (
                source_url, source_id, source_name, source_domain, source_language, source_feed_url,
                destination_country, destination_city, destination_countries_json, destination_status,
                primary_category, categories_json, taxonomy_path, topic_confidence, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_url) DO UPDATE SET
                source_id=excluded.source_id, source_name=excluded.source_name,
                source_domain=excluded.source_domain, source_language=excluded.source_language,
                source_feed_url=excluded.source_feed_url, destination_country=excluded.destination_country,
                destination_city=excluded.destination_city, destination_countries_json=excluded.destination_countries_json,
                destination_status=excluded.destination_status, primary_category=excluded.primary_category,
                categories_json=excluded.categories_json, taxonomy_path=excluded.taxonomy_path,
                topic_confidence=excluded.topic_confidence, updated_at=excluded.updated_at
        """, (
            source_url, article.get("source_id"), article.get("source_name"), article.get("source_domain"),
            article.get("source_language", "en"), article.get("source_feed_url"), article.get("destination_country"),
            article.get("destination_city"), json.dumps(article.get("destination_countries", []), ensure_ascii=False),
            article.get("destination_status"), article.get("primary_category"),
            json.dumps(article.get("topic_categories", []), ensure_ascii=False), article.get("taxonomy_path"),
            article.get("topic_confidence"), timestamp,
        ))
        conn.commit()



def _output_stem(source_url):
    canonical = normalize_url(source_url) or clean_text(source_url)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:20]
    return f"article_{digest}"


def output_paths_for_url(source_url):
    os.makedirs(DRAFT_OUTPUT_DIR, exist_ok=True)
    stem = _output_stem(source_url)
    return {
        "output_json_path": os.path.join(DRAFT_OUTPUT_DIR, stem + ".json"),
        "output_md_path": os.path.join(DRAFT_OUTPUT_DIR, stem + ".md"),
    }


def _article_payload_for_output(article):
    # Raw source text/HTML is excluded. Output is a reusable editorial artifact,
    # not an archive of the publisher's full article.
    excluded = {"source_body", "source_html", "source_content", "raw_html", "html_document"}
    payload = {key: value for key, value in article.items() if key not in excluded}
    return payload


def render_output_markdown(article, draft=None, stage="draft_ready", error=None):
    draft = draft or {}
    body = html_to_text(draft.get("seo_content", "")) if draft.get("seo_content") else ""
    try:
        secondary = json.loads(draft.get("secondary_keywords") or "[]")
    except (TypeError, json.JSONDecodeError):
        secondary = []
    try:
        facts = json.loads(draft.get("source_facts_used") or "[]")
    except (TypeError, json.JSONDecodeError):
        facts = []
    if not facts:
        sheet = article.get("source_fact_sheet") or {}
        facts = [item.get("fact", "") for item in sheet.get("facts", []) if isinstance(item, dict)]
    image_list = article.get("source_images") or []
    if not image_list and article.get("source_images_json"):
        try:
            image_list = json.loads(article.get("source_images_json") or "[]")
        except (TypeError, json.JSONDecodeError):
            image_list = []
    lines = [
        "# " + (draft.get("seo_title") or article.get("source_title") or "Bản nháp chưa hoàn tất"),
        "",
        f"- Trạng thái artifact: `{stage}`",
        f"- URL nguồn: {article.get('source_url', '')}",
        f"- Nguồn: {article.get('source_name') or article.get('source_publisher') or 'Không xác định'}",
        f"- Ngày nguồn: {article.get('published_at') or 'Không xác định'}",
        f"- Điểm đến: {article.get('destination_country') or 'World / Chưa phân loại'}" + (f" — {article.get('destination_city')}" if article.get('destination_city') else ""),
        f"- Chuyên mục site: {article.get('top_level_section') or 'Cẩm nang'} / {article.get('primary_category') or 'travel-guide'}",
        f"- Taxonomy path: {article.get('taxonomy_path') or 'cam-nang/travel-guide'}",
        f"- AI: {draft.get('ai_provider') or 'Chưa hoàn tất'}",
        "",
        "## Meta description",
        draft.get("seo_description", "") or "Chưa tạo",
        "",
        "## Từ khóa chính",
        draft.get("primary_keyword", "") or "Chưa tạo",
        "",
        "## Từ khóa phụ",
        ", ".join(secondary) if secondary else "Chưa tạo",
        "",
        "## Góc biên tập",
        draft.get("editorial_angle", "") or "Chưa tạo",
        "",
        "## Nội dung bài",
        body or "Chưa có bài viết hoàn chỉnh. Nếu phần hồ sơ dữ kiện đã lưu, có thể tiếp tục bước biên tập mà không trích xuất lại.",
        "",
        "## Dữ kiện tham chiếu",
    ]
    lines.extend(["- " + clean_text(x) for x in facts if clean_text(x)] or ["- Chưa có hồ sơ dữ kiện."])
    lines += ["", "## Ghi chú kiểm chứng", draft.get("fact_check_notes", "") or "Chưa có"]
    lines += ["", "## Ảnh / credit nguồn"]
    if image_list:
        for item in image_list[:10]:
            if not isinstance(item, dict):
                continue
            info = "- " + (item.get("image_id") or "Ảnh") + " — " + (item.get("url") or "")
            info += f" — vị trí nguồn: {item.get('position_ratio', 0)}"
            if item.get("nearby_heading"):
                info += " — heading gần nhất: " + clean_text(item["nearby_heading"])
            if item.get("caption"):
                info += " — caption: " + clean_text(item["caption"])
            if item.get("credit"):
                info += " — credit ảnh: " + clean_text(item["credit"]) + f" (từ {item.get('credit_source') or 'metadata'})"
            else:
                info += " — CHƯA RÕ CREDIT/QUYỀN SỬ DỤNG"
            lines.append(info)
    elif article.get("source_image_url"):
        lines.append("- " + article["source_image_url"] + " — " + (article.get("image_credit") or "chưa rõ credit/giấy phép"))
    else:
        lines.append("- Không có ảnh được nhận diện.")
    lines += ["", "## Lỗi / ghi chú", clean_text(error or "Không có")]
    return "\n".join(lines).strip() + "\n"


def save_output_bundle(article, draft=None, stage="draft_ready", error=None):
    """Ghi artifact bền vững theo URL, có thể dùng lại khi lỗi/retry; không lưu nguyên văn nguồn."""
    paths = output_paths_for_url(article.get("source_url", ""))
    os.makedirs(DRAFT_OUTPUT_DIR, exist_ok=True)
    bundle = {
        "schema_version": 1,
        "source_url": normalize_url(article.get("source_url", "")) or article.get("source_url", ""),
        "stage": stage,
        "error": clean_text(error or ""),
        "saved_at": now_iso(),
        "article": _article_payload_for_output(article),
        "draft": draft or None,
        "paths": paths,
    }
    json_tmp = paths["output_json_path"] + ".tmp"
    md_tmp = paths["output_md_path"] + ".tmp"
    with open(json_tmp, "w", encoding="utf-8") as handle:
        json.dump(bundle, handle, ensure_ascii=False, indent=2)
    with open(md_tmp, "w", encoding="utf-8") as handle:
        handle.write(render_output_markdown(article, draft, stage, error))
    os.replace(json_tmp, paths["output_json_path"])
    os.replace(md_tmp, paths["output_md_path"])
    log.info("Đã lưu artifact có thể tái sử dụng: %s", paths["output_md_path"])
    return paths


def load_output_bundle(source_url):
    """Đọc artifact đã lưu theo URL nguồn; không gọi crawler hay AI."""
    paths = output_paths_for_url(source_url)
    path = paths["output_json_path"]
    if not os.path.isfile(path):
        # Fallback đường dẫn trong DB (hỗ trợ khi cấu trúc thư mục được thay đổi).
        with sqlite3.connect(DATABASE_PATH, timeout=30) as conn:
            row = conn.execute(
                "SELECT output_json_path FROM articles WHERE source_url=?",
                (normalize_url(source_url) or source_url,),
            ).fetchone()
        if row and row[0] and os.path.isfile(row[0]):
            path = row[0]
        else:
            return None
    with open(path, "r", encoding="utf-8") as handle:
        bundle = json.load(handle)
    if not isinstance(bundle, dict) or not isinstance(bundle.get("article"), dict):
        raise ValueError(f"Artifact không đúng cấu trúc: {path}")
    bundle["paths"] = bundle.get("paths") or paths
    return bundle


def register_output_paths(source_url, paths):
    canonical = normalize_url(source_url) or source_url
    with sqlite3.connect(DATABASE_PATH, timeout=30) as conn:
        conn.execute(
            "UPDATE articles SET output_json_path=?, output_md_path=?, updated_at=? WHERE source_url=?",
            (paths.get("output_json_path"), paths.get("output_md_path"), now_iso(), canonical),
        )
        conn.commit()


def _safe_output_path(path):
    if not path:
        return None
    root = os.path.realpath(OUTPUT_DIR)
    candidate = os.path.realpath(path)
    try:
        if os.path.commonpath([root, candidate]) != root:
            log.warning("Từ chối xóa file ngoài OUTPUT_DIR: %s", candidate)
            return None
    except ValueError:
        return None
    return candidate


def cleanup_output_files(paths):
    """Xóa đúng artifact của một bài, chỉ bên trong OUTPUT_DIR."""
    all_deleted = True
    for key in ("output_json_path", "output_md_path"):
        candidate = _safe_output_path(paths.get(key))
        if not candidate:
            if paths.get(key):
                all_deleted = False
            continue
        try:
            if os.path.exists(candidate):
                os.remove(candidate)
        except OSError as exc:
            all_deleted = False
            log.error("Không xóa được artifact %s (%s)", candidate, type(exc).__name__)
    return all_deleted


def cleanup_published_artifacts():
    """Retry cleanup nếu lần dọn sau publish trước đó bị lỗi file lock/permission."""
    with sqlite3.connect(DATABASE_PATH, timeout=30) as conn:
        rows = conn.execute(
            "SELECT source_url, output_json_path, output_md_path FROM articles "
            "WHERE status='published' AND (output_json_path IS NOT NULL OR output_md_path IS NOT NULL)"
        ).fetchall()
    for source_url, json_path, md_path in rows:
        if cleanup_output_files({"output_json_path": json_path, "output_md_path": md_path}):
            with sqlite3.connect(DATABASE_PATH, timeout=30) as conn:
                conn.execute(
                    "UPDATE articles SET output_json_path=NULL, output_md_path=NULL, publish_error=NULL, updated_at=? WHERE source_url=?",
                    (now_iso(), source_url),
                )
                conn.commit()
        else:
            log.warning("Bài đã đăng nhưng còn artifact chưa xóa được; sẽ thử lại lần sau: %s", source_url)


def mark_published(source_url, published_url, cms_post_id=None):
    """Call ONLY after the CMS confirms successful publication. Saves minimal history then cleans output."""
    canonical = normalize_url(source_url) or source_url
    publish_url = clean_text(published_url)
    if not publish_url.startswith(("https://", "http://")):
        raise ValueError("published_url phải là URL HTTP(S) của bài đã xuất bản.")

    with sqlite3.connect(DATABASE_PATH, timeout=30) as conn:
        row = conn.execute(
            "SELECT output_json_path, output_md_path FROM articles WHERE source_url=?",
            (canonical,),
        ).fetchone()
        if not row:
            raise LookupError(f"Không thấy bài trong database: {canonical}")
        conn.execute("""
            UPDATE articles SET
                status='published', publish_url=?, cms_post_id=?, site_published_at=?,
                source_summary=NULL, source_modified_at=NULL, source_author=NULL,
                source_meta_keywords=NULL, source_fact_sheet_json=NULL, source_body_chars=NULL,
                content_extraction_status='cleaned_after_publish', source_content=NULL,
                seo_description=NULL, seo_content=NULL, primary_keyword=NULL,
                secondary_keywords=NULL, editorial_angle=NULL, fact_check_notes=NULL,
                source_facts_used=NULL, error_message=NULL, publish_error=NULL, updated_at=?
            WHERE source_url=?
        """, (publish_url, str(cms_post_id) if cms_post_id is not None else None, now_iso(), now_iso(), canonical))
        conn.commit()
        paths = {"output_json_path": row[0], "output_md_path": row[1]}

    deleted = cleanup_output_files(paths)
    with sqlite3.connect(DATABASE_PATH, timeout=30) as conn:
        if deleted:
            conn.execute(
                "UPDATE articles SET output_json_path=NULL, output_md_path=NULL, updated_at=? WHERE source_url=?",
                (now_iso(), canonical),
            )
            log.info("Đã dọn output sau khi website xác nhận xuất bản: %s", canonical)
        else:
            conn.execute(
                "UPDATE articles SET publish_error=?, updated_at=? WHERE source_url=?",
                ("Bài đã đăng thành công nhưng chưa xóa hết output; hệ thống sẽ thử dọn lại ở lần chạy sau.", now_iso(), canonical),
            )
        conn.commit()
    return {"source_url": canonical, "publish_url": publish_url, "cleanup_complete": deleted}


def list_reusable_output_files():
    """List pending JSON artifacts useful for retries/review; published artifacts are cleaned."""
    if not os.path.isdir(DRAFT_OUTPUT_DIR):
        return []
    result = []
    for path in sorted(Path(DRAFT_OUTPUT_DIR).glob("article_*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            with open(path, "r", encoding="utf-8") as handle:
                bundle = json.load(handle)
            if bundle.get("source_url") and bundle.get("stage") != "published":
                result.append({"source_url": bundle["source_url"], "stage": bundle.get("stage", "unknown"), "json_path": str(path), "md_path": bundle.get("paths", {}).get("output_md_path")})
        except (OSError, json.JSONDecodeError):
            continue
    return result

def html_to_text(fragment):
    """Chuyển HTML đơn giản thành văn bản, giữ ranh giới giữa các đoạn."""
    soup = BeautifulSoup(fragment or "", "html.parser")
    parts = []
    for node in soup.find_all(["h2", "h3", "p", "li", "blockquote", "figcaption"]):
        # Tránh lặp text nếu có thẻ block nằm bên trong một block khác.
        if node.find_parent(["p", "li", "h2", "h3", "blockquote", "figcaption"]):
            continue
        text = clean_text(node.get_text(" ", strip=True))
        if not text:
            continue
        if node.name in {"h2", "h3"}:
            parts.append(text.upper())
        elif node.name == "li":
            parts.append("• " + text)
        else:
            parts.append(text)
    if not parts:
        fallback = clean_text(soup.get_text(" ", strip=True))
        return fallback
    return "\n\n".join(parts)


def telegram_send(text):
    """Gửi một tin nhắn Telegram và trả về message_id.

    Không ghi URL request hoặc token vào log, vì token nằm trong đường dẫn Bot API.
    Người gọi cần chia nội dung dài thành các đoạn dưới giới hạn 4096 ký tự.
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise RuntimeError(
            "Thiếu TELEGRAM_BOT_TOKEN hoặc TELEGRAM_CHAT_ID trong file .env."
        )

    message = str(text or "").strip()
    if not message:
        raise ValueError("Không thể gửi tin nhắn Telegram rỗng.")
    if len(message) > 4096:
        raise ValueError(
            f"Tin nhắn Telegram dài {len(message)} ký tự; "
            "hãy chia nhỏ trước khi gọi telegram_send()."
        )

    api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "disable_web_page_preview": True,
    }

    try:
        response = requests.post(api_url, json=payload, timeout=25)
    except requests.RequestException as exc:
        # Không đưa str(exc) vào log vì nó có thể chứa URL gồm bot token.
        raise RuntimeError(
            f"Không kết nối được Telegram API ({type(exc).__name__})."
        ) from None

    try:
        data = response.json()
    except ValueError:
        data = {}

    if not response.ok or not data.get("ok"):
        description = clean_text(data.get("description", ""))
        if not description:
            description = "Telegram không trả về mô tả lỗi."
        raise RuntimeError(
            f"Telegram sendMessage thất bại (HTTP {response.status_code}): "
            f"{description[:500]}"
        )

    result = data.get("result") or {}
    message_id = result.get("message_id")
    if message_id is None:
        raise RuntimeError("Telegram trả về thành công nhưng thiếu message_id.")
    return message_id


def split_telegram_text(text, limit=3300):
    """Tách tin nhắn dài, ưu tiên ngắt tại đoạn văn để không mất nội dung."""
    text = (text or "").strip()
    if not text:
        return []
    chunks, current = [], ""
    paragraphs = text.split("\n\n")
    for paragraph in paragraphs:
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        candidate = paragraph if not current else current + "\n\n" + paragraph
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            chunks.append(current)
            current = ""
        while len(paragraph) > limit:
            chunks.append(paragraph[:limit])
            paragraph = paragraph[limit:]
        current = paragraph
    if current:
        chunks.append(current)
    return chunks


def send_telegram_article(article, draft=None, test_mode=False):
    """Gửi metadata và toàn bộ nội dung bài qua một hoặc nhiều Telegram messages."""
    if not draft:
        lines = [
            "🧭 BẢN GHI NGUỒN — CHỜ AI/BIÊN TẬP",
            "",
            article.get("source_title", "(Không có tiêu đề)"),
            article.get("source_summary", ""),
            "",
            f"🗓 Ngày nguồn: {article.get('published_at') or 'Không xác định'}",
            f"🔗 Bài nguồn: {article.get('source_url', '')}",
        ]
        if article.get("source_image_url"):
            lines.append(f"🖼 URL ảnh nguồn: {article['source_image_url']}")
            if article.get("image_credit"):
                lines.append(f"📷 Credit ảnh: {article['image_credit']}")
            else:
                lines.append("⚠️ Không xác định được credit ảnh; đừng sử dụng ảnh khi đăng.")
        else:
            lines.append("🖼 Không có URL ảnh metadata; bỏ ảnh.")
        lines.append("ℹ️ Chưa có bản nháp AI. Bài chưa được xuất bản.")
        return telegram_send("\n".join(lines))

    prefix = "🧪 KIỂM TRA AI — dùng bài đã lưu, không crawl lại\n\n" if test_mode else "🧠 BẢN NHÁP SEO DO AI BIÊN TẬP — CHỜ DUYỆT\n\n"
    meta_lines = [
        prefix.rstrip(),
        f"Tiêu đề nguồn: {article.get('source_title', '')}",
        f"AI sử dụng: {draft.get('ai_provider', 'Không xác định')}",
        (f"Thân bài đã trích xuất: {article.get('source_body_chars', 0)} ký tự ({article.get('content_extraction_status', 'không rõ')})" if article.get("content_extraction_status") != "metadata_only_no_body_extracted" else "Thân bài nguồn: Không thu thập (chế độ metadata-only; viết bài từ metadata và ảnh)"),
        f"Nhà xuất bản/website: {article.get('source_name') or article.get('source_publisher') or 'Không xác định'}",
        f"Domain nguồn: {article.get('source_domain') or 'Không xác định'}",
        f"Chuyên mục nguồn: {article.get('source_section') or 'Không xác định'}",
        f"Điểm đến: {article.get('destination_country') or 'World / Chưa phân loại'}" + (f" — {article.get('destination_city')}" if article.get('destination_city') else ""),
        f"Chuyên mục site đề xuất: {article.get('top_level_section') or 'Cẩm nang'} / {article.get('primary_category') or 'travel-guide'}",
        f"Taxonomy path: {article.get('taxonomy_path') or 'cam-nang/travel-guide'}",
        f"Lưu ý quyền nguồn: {article.get('permission_status') or 'review_terms_before_commercial_reuse'}",
        f"Từ khóa metadata nguồn: {article.get('source_meta_keywords') or 'Không có'}",
        f"Tiêu đề SEO: {draft.get('seo_title', '')}",
        f"Meta description: {draft.get('seo_description', '')}",
        f"Từ khóa chính: {draft.get('primary_keyword', '') or 'Chưa có'}",
    ]
    try:
        secondary = json.loads(draft.get("secondary_keywords") or "[]")
    except (TypeError, json.JSONDecodeError):
        secondary = []
    if secondary:
        meta_lines.append("Từ khóa phụ: " + ", ".join(secondary))
    if draft.get("editorial_angle"):
        meta_lines.append("Góc biên tập: " + draft["editorial_angle"])
    if draft.get("ai_fallback_reason"):
        meta_lines.append("🔁 Dự phòng AI: " + draft["ai_fallback_reason"])
    meta_lines += [
        "",
        f"🗓 Ngày đăng nguồn: {article.get('published_at') or 'Không xác định'}",
        f"🛠 Ngày cập nhật nguồn: {article.get('source_modified_at') or 'Không có metadata'}",
        f"🔗 Nguồn tham khảo: {article.get('source_url', '')}",
    ]
    image_list = article.get("source_images") or []
    if not image_list and article.get("source_images_json"):
        try:
            image_list = json.loads(article["source_images_json"])
        except (TypeError, json.JSONDecodeError):
            image_list = []
    if image_list:
        meta_lines.append("🖼 Ảnh tìm thấy trong bài nguồn:")
        for idx, image_item in enumerate(image_list[:5], start=1):
            meta_lines.append(f"  {idx}. {image_item.get('url', '')}")
            if image_item.get("caption"):
                meta_lines.append(f"     Caption: {image_item['caption'][:240]}")
            image_id = image_item.get("image_id") or f"IMG_{idx:02d}"
            meta_lines.append(f"     Vị trí: inline trong bài ({image_id}; sau heading: {image_item.get('nearby_heading') or 'không xác định'})")
            if image_item.get("credit"):
                meta_lines.append(f"     Credit ảnh: {image_item['credit']} (nguồn nhận diện: {image_item.get('credit_source') or 'metadata'})")
            else:
                meta_lines.append("     Credit ảnh: chưa xác định; ảnh vẫn được nhận diện nhưng cần kiểm tra quyền sử dụng.")
    elif article.get("source_image_url"):
        meta_lines.append(f"🖼 URL ảnh nguồn: {article['source_image_url']}")
        if article.get("image_credit"):
            meta_lines.append(f"📷 Credit trong caption nguồn: {article['image_credit']}")
        else:
            meta_lines.append("⚠️ Chưa xác định được credit ảnh; không dùng ảnh khi đăng.")
    else:
        meta_lines.append("🖼 Không tìm thấy URL ảnh; bỏ ảnh.")
    meta_lines += [
        "",
        "🔎 Ghi chú kiểm chứng: " + (draft.get("fact_check_notes") or "Cần biên tập viên xác minh dữ kiện."),
        "🖼 Ảnh được đặt inline theo vị trí liên quan trong thân bài. Mặc định HTML chứa placeholder cho ảnh chưa xác minh quyền sử dụng.",
        "⚠️ Đây là bản nháp, chưa xuất bản. Credit không thay thế quyền sử dụng ảnh.",
    ]
    first_message_id = None
    meta_chunks = split_telegram_text("\n\n".join(meta_lines), limit=3300)
    for chunk in meta_chunks:
        message_id = telegram_send(chunk)
        if first_message_id is None:
            first_message_id = message_id
        time.sleep(0.3)

    article_text = html_to_text(draft.get("seo_content", ""))
    chunks = split_telegram_text(article_text, limit=3200)
    total = len(chunks)
    for index, chunk in enumerate(chunks, start=1):
        heading = f"📝 NỘI DUNG BÀI ({index}/{total})\n\n"
        telegram_send(heading + chunk)
        time.sleep(0.4)
    return first_message_id


def parse_main_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Crawl nguồn du lịch đa nguồn và xuất bản tối đa N bài mới lên website."
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Giới hạn số URL bài mới thực sự thử xử lý trong lượt này (ví dụ --limit 3). Mặc định dùng MAX_ARTICLES trong .env.",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_main_args(argv)
    run_limit = MAX_ARTICLES if args.limit is None else max(1, min(int(args.limit), 10))
    max_attempts = min(50, run_limit * 3)
    log.info(
        "Mục tiêu xuất bản %s bài mới; cho phép thử tối đa %s URL mới để bù bài lỗi AI/không hợp lệ.",
        run_limit, max_attempts,
    )
    init_db()
    cleanup_published_artifacts()
    _reconcile_site_publications()
    candidates = discover_from_sources()

    processed = 0
    published_count = 0
    attempted = 0
    duplicates = 0
    failed = 0
    ai_quota_stop = False

    if not candidates:
        log.warning("Không tìm thấy ứng viên từ các RSS nguồn đang bật. Kiểm tra sources.json, kết nối mạng và feed_url; không quay lại VnExpress.")

    # --limit là mục tiêu số bài xuất bản, không phải số URL cần thử. Duplicates đã
    # biết được bỏ qua; URL mới được tính vào max_attempts kể cả khi AI lỗi.
    for item in candidates:
        if published_count >= run_limit or attempted >= max_attempts:
            break

        discovered_url = normalize_url(item.get("source_url", ""))
        if not discovered_url:
            continue
        if already_seen(discovered_url):
            log.info("Bỏ qua URL đã xử lý: %s", discovered_url)
            duplicates += 1
            continue

        attempted += 1
        log.info("Bài thử %s/%s: %s", attempted, run_limit, discovered_url)
        try:
            article = extract_article_metadata(item)
            canonical_url = article["source_url"]

            # Canonical URL có thể khác URL trong RSS.
            if already_seen(canonical_url):
                remember_source(
                    discovered_url,
                    article["title_key"],
                    article["published_day"],
                    status="canonical_alias",
                    duplicate_of=canonical_url,
                )
                log.info("Bỏ URL canonical đã có trong database: %s", canonical_url)
                duplicates += 1
                continue

            duplicate = find_duplicate_by_title(
                article["source_title"], article.get("published_at"),
                exclude_source_url=canonical_url,
            )
            if duplicate:
                # Đánh dấu URL mới này là bản trùng để ngày mai không crawl/gửi lại.
                remember_source(
                    discovered_url,
                    article["title_key"],
                    article["published_day"],
                    status="duplicate",
                    duplicate_of=duplicate["source_url"],
                )
                if canonical_url != discovered_url:
                    remember_source(
                        canonical_url,
                        article["title_key"],
                        article["published_day"],
                        status="duplicate",
                        duplicate_of=duplicate["source_url"],
                    )
                log.info(
                    "Bỏ bài trùng tiêu đề/ngày: '%s' (bản gốc %s)",
                    article["source_title"], duplicate["source_url"],
                )
                duplicates += 1
                continue

            draft = None
            output_paths = None
            status = "discovered"
            error_message = None
            if GEMINI_API_KEY or OPENAI_API_KEY or GROQ_API_KEY or OPENROUTER_API_KEY:
                try:
                    draft = create_ai_draft(article)
                    if draft:
                        article.update(draft)
                        status = "drafted_fallback" if draft.get("ai_fallback_reason") else "drafted"
                        if draft.get("ai_fallback_reason"):
                            error_message = draft["ai_fallback_reason"]
                except Exception as exc:
                    error_message = f"AI providers failed: {type(exc).__name__}: {clean_text(str(exc))[:700]}"
                    status = "ai_failed_metadata_only"
                    log.exception("AI provider lỗi; giữ artifact để có thể tiếp tục: %s", canonical_url)
                    ai_quota_stop = _is_ai_capacity_error(error_message)
                    if ai_quota_stop:
                        log.warning("AI provider đã chạm quota/rate limit hoặc lỗi xác thực; dừng lượt hôm nay để tránh gọi lặp.")

            # Write a stable per-source artifact before syncing so API failures do not force AI regeneration.
            try:
                output_paths = save_output_bundle(
                    article, draft, stage=("draft_ready" if draft else "ai_failed_or_metadata_only"),
                    error=error_message,
                )
                article.update(output_paths)
            except Exception as output_exc:
                log.exception("Không lưu được artifact đầu ra: %s", canonical_url)
                if not error_message:
                    error_message = f"Output save error: {type(output_exc).__name__}"

            # Persist article history before attempting to publish; keep output files for recovery.
            save(article, status, error_message)
            if output_paths:
                register_output_paths(canonical_url, output_paths)
            if draft:
                site_result = _sync_draft_to_site_if_enabled(article, draft)
                if site_result and site_result.get("ok") and site_result.get("status") == "published":
                    if not site_result.get("skipped"):
                        published_count += 1
                    log.info("ĐÃ XUẤT BẢN lên website: slug=%s url=%s", site_result.get("slug"), site_result.get("site_url"))
                elif site_result and site_result.get("ok") and site_result.get("skipped"):
                    log.info("Bỏ qua bài website đã xử lý: status=%s slug=%s", site_result.get("status"), site_result.get("slug"))
                elif site_result and not site_result.get("ok"):
                    failed += 1
                    log.error("Chưa xuất bản được bài lên website: %s", site_result.get("error", "lỗi không rõ"))
                    # A connection/auth/config error affects every subsequent post; stop
                    # before spending more AI calls while the publishing endpoint is down.
                    break
            else:
                failed += 1
                log.error("Không có bản AI hoàn chỉnh; bài chưa được xuất bản: %s", canonical_url)
            processed += 1
            time.sleep(2)
            if ai_quota_stop:
                log.warning("Đã lưu bài chưa hoàn chỉnh; URL này sẽ được thử lại ở lần chạy hằng ngày tiếp theo.")
                break

        except Exception as exc:
            failed += 1
            log.exception("Không xử lý được %s", discovered_url)

    summary = (
        "Travel Content Bot hoàn tất\n"
        f"URL mới đã thử: {attempted}/{max_attempts}\n"
        f"Bài đã xử lý: {processed}\n"
        f"Bài mới đã xuất bản: {published_count}/{run_limit}\n"
        f"Bài trùng đã bỏ qua: {duplicates}\n"
        f"Bài lỗi/chưa xuất bản: {failed}\n"
        + ("AI quota/rate limit đã chạm; đã dừng sớm và giữ URL lỗi để thử lại ngày sau." if ai_quota_stop
           else "Có thể xuất bản ít hơn mục tiêu nếu nguồn mới hoặc AI/API không đáp ứng.")
    )
    log.info(summary)
    return {
        "published_count": published_count,
        "failed": failed,
        "ai_quota_stop": ai_quota_stop,
        "attempted": attempted,
    }


if __name__ == "__main__":
    result = main()
    if result and result.get("failed") and not result.get("ai_quota_stop"):
        raise SystemExit(1)
