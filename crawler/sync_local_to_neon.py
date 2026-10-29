"""Backfill complete local crawler articles to the website's Neon database via the authenticated ingest API.

Dry-run is the default. Use --apply to write. The script never calls AI and never deletes local data.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

import requests
import main as bot
import site_publisher as site

LOG = logging.getLogger("sync-local-to-neon")
DUPLICATE_STATES = {"duplicate", "canonical_alias", "duplicate_title"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Đồng bộ bài AI đã có trong SQLite local lên website/Neon qua API; không gọi AI, không xóa dữ liệu local."
    )
    parser.add_argument("--database", help="Đường dẫn SQLite local (mặc định dùng DATABASE_PATH trong .env).")
    parser.add_argument("--limit", type=int, default=10, help="Giới hạn số bài hoàn chỉnh cần xử lý (mặc định 10, tối đa 1000).")
    parser.add_argument("--all", action="store_true", help="Xử lý toàn bộ bài hoàn chỉnh đã lưu trong SQLite.")
    parser.add_argument("--apply", action="store_true", help="Gửi dữ liệu thật lên website/Neon. Nếu không có cờ này, chỉ xem trước.")
    parser.add_argument("--dry-run", action="store_true", help="Chỉ xem trước; đây cũng là chế độ mặc định nếu không có --apply.")
    parser.add_argument("--include-archived-local", action="store_true", help="Bao gồm các bài local có status archived; mặc định bỏ qua.")
    parser.add_argument("--pause", type=float, default=0.3, help="Thời gian nghỉ giữa các bài, giây (0–10, mặc định 0.3).")
    return parser.parse_args()


def _json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if not value:
        return []
    try:
        result = json.loads(value) if isinstance(value, str) else value
        return result if isinstance(result, list) else []
    except (TypeError, json.JSONDecodeError):
        return []


def _complete(draft: Any) -> bool:
    return isinstance(draft, dict) and bool(
        str(draft.get("seo_title") or "").strip()
        and str(draft.get("seo_content") or "").strip()
    )


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1", (table,)
    ).fetchone() is not None


def load_local_records(db_path: str, limit: int | None, include_archived_local: bool = False) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    if not os.path.isfile(db_path):
        raise FileNotFoundError(
            f"Không tìm thấy SQLite local: {db_path}. Dừng để tránh tự tạo database rỗng."
        )

    with sqlite3.connect(db_path, timeout=30) as conn:
        conn.row_factory = sqlite3.Row
        if not _table_exists(conn, "articles"):
            raise RuntimeError(f"Database {db_path} không có bảng articles; kiểm tra DATABASE_PATH trong .env.")
        statuses = ""
        if not include_archived_local:
            statuses = "AND COALESCE(a.status, '') <> 'archived'"
        sql = f"""
            SELECT a.*
            FROM articles a
            WHERE TRIM(COALESCE(a.source_url, '')) <> ''
              AND TRIM(COALESCE(a.seo_title, '')) <> ''
              AND TRIM(COALESCE(a.seo_content, '')) <> ''
              AND COALESCE(a.status, '') NOT IN ('duplicate', 'canonical_alias', 'duplicate_title')
              {statuses}
            ORDER BY a.id ASC
        """
        if limit is not None:
            sql += " LIMIT ?"
            rows = conn.execute(sql, (max(1, min(int(limit), 1000)),)).fetchall()
        else:
            rows = conn.execute(sql).fetchall()

        has_taxonomy = _table_exists(conn, "article_taxonomy")
        records: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for raw_row in rows:
            row = dict(raw_row)
            source_url = str(row.get("source_url") or "").strip()
            article: dict[str, Any] = {
                "source_url": source_url,
                "source_title": row.get("source_title") or "",
                "source_summary": row.get("source_summary") or "",
                "published_at": row.get("published_at"),
                "source_image_url": row.get("source_image_url") or "",
                "image_credit": row.get("image_credit") or "",
                "image_credit_url": row.get("image_credit_url") or "",
                "source_author": row.get("source_author") or "",
                "source_publisher": row.get("source_publisher") or "",
                "source_section": row.get("source_section") or "",
                "source_meta_keywords": row.get("source_meta_keywords") or "",
                "source_images_json": row.get("source_images_json") or "[]",
                "seo_title": row.get("seo_title") or "",
                "seo_description": row.get("seo_description") or "",
                "seo_content": row.get("seo_content") or "",
                "primary_keyword": row.get("primary_keyword") or "",
                "secondary_keywords": row.get("secondary_keywords") or "[]",
                "editorial_angle": row.get("editorial_angle") or "",
                "fact_check_notes": row.get("fact_check_notes") or "",
                "source_facts_used": row.get("source_facts_used") or "[]",
                "ai_provider": row.get("ai_provider") or "",
            }

            if has_taxonomy:
                tax_row = conn.execute(
                    "SELECT * FROM article_taxonomy WHERE source_url=? LIMIT 1", (source_url,)
                ).fetchone()
                if tax_row:
                    tax = dict(tax_row)
                    for key in (
                        "source_id", "source_name", "source_domain", "source_language", "source_feed_url",
                        "destination_country", "destination_city", "destination_status", "primary_category",
                        "taxonomy_path", "topic_confidence",
                    ):
                        if tax.get(key) not in (None, ""):
                            article[key] = tax[key]
                    article["destination_countries"] = _json_list(tax.get("destination_countries_json"))
                    article["topic_categories"] = _json_list(tax.get("categories_json"))

            # Prefer the richer saved artifact for taxonomy/image captions, without requiring any AI call.
            try:
                bundle = bot.load_output_bundle(source_url)
            except (OSError, ValueError, json.JSONDecodeError, sqlite3.Error):
                bundle = None
            draft = None
            if isinstance(bundle, dict):
                saved_article = bundle.get("article")
                if isinstance(saved_article, dict):
                    article.update({k: v for k, v in saved_article.items() if v not in (None, "", [], {})})
                candidate = bundle.get("draft")
                if _complete(candidate):
                    draft = candidate
            if not _complete(draft):
                draft = {
                    "seo_title": row.get("seo_title") or "",
                    "seo_description": row.get("seo_description") or "",
                    "seo_content": row.get("seo_content") or "",
                    "primary_keyword": row.get("primary_keyword") or "",
                    "secondary_keywords": row.get("secondary_keywords") or "[]",
                    "editorial_angle": row.get("editorial_angle") or "",
                    "fact_check_notes": row.get("fact_check_notes") or "",
                    "source_facts_used": row.get("source_facts_used") or "[]",
                    "ai_provider": row.get("ai_provider") or "",
                }
            # Always use the canonical source URL from the database row as the dedupe key.
            article["source_url"] = source_url
            records.append((article, draft))
    return records


def _remote_post(source_url: str) -> dict[str, Any] | None:
    response = requests.get(
        site._endpoint(), params={"sourceUrl": source_url}, headers=site._headers(),
        timeout=(5, site.SITE_API_TIMEOUT),
    )
    response.raise_for_status()
    payload = response.json()
    post = payload.get("post") if payload.get("found") else None
    return post if isinstance(post, dict) else None


def _sync_one(article: dict[str, Any], draft: dict[str, Any], db_path: str) -> dict[str, Any]:
    source_url = site.normalize_source_url(article.get("source_url", ""))
    if not source_url:
        raise ValueError("URL nguồn không hợp lệ.")

    remote = _remote_post(source_url)
    if remote:
        remote_status = site.clean(remote.get("status")).lower()
        remote_slug = site.clean(remote.get("slug"))
        remote_id = remote.get("id")
        remote_url = f"{site.SITE_URL}/bai-viet/{remote_slug}" if remote_slug else None
        if remote_status == "published":
            site._record_sync(db_path, source_url, post_id=remote_id, slug=remote_slug, status="published", site_url=remote_url)
            return {"status": "already_published", "slug": remote_slug, "url": remote_url}
        if remote_status == "archived":
            site._record_sync(db_path, source_url, post_id=remote_id, slug=remote_slug, status="archived", site_url=remote_url)
            return {"status": "skipped_archived", "slug": remote_slug, "url": remote_url}

    payload = site.build_site_payload(article, draft)
    # The published-v2 publisher intentionally sets status=published; API health check
    # requires INGEST_AUTO_PUBLISH=true before this function can run.
    response = requests.post(
        site._endpoint(), headers=site._headers(), json=payload,
        timeout=(8, site.SITE_API_TIMEOUT),
    )
    try:
        data = response.json()
    except ValueError:
        data = {}
    if not response.ok or not data.get("success") or int(data.get("failed", 0) or 0) > 0:
        reason = site.clean(data.get("error") or data.get("results") or response.reason or "API trả lỗi")
        site._record_sync(db_path, source_url, status="failed", error=f"HTTP {response.status_code}: {reason[:700]}")
        raise RuntimeError(f"API website/Neon lỗi HTTP {response.status_code}: {reason[:350]}")

    results = data.get("results") or []
    result = results[0] if results and isinstance(results[0], dict) else {}
    status = site.clean(result.get("status") or "").lower()
    post_id = result.get("id")
    slug = site.clean(result.get("slug"))
    post_url = f"{site.SITE_URL}/bai-viet/{slug}" if slug else None
    site._record_sync(db_path, source_url, post_id=post_id, slug=slug, status=status or "failed", site_url=post_url,
                      error=None if status == "published" else f"API trả về status={status or 'unknown'}")
    if status != "published":
        raise RuntimeError(
            f"API đã phản hồi nhưng status={status or 'unknown'}, chưa xác nhận xuất bản. "
            "Kiểm tra INGEST_AUTO_PUBLISH=true và route.ts trên Vercel."
        )
    return {"status": "published", "action": result.get("action"), "slug": slug, "url": post_url}


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    if args.pause < 0 or args.pause > 10:
        raise SystemExit("--pause phải trong khoảng 0–10 giây.")

    db_path = os.path.abspath(args.database or bot.DATABASE_PATH)
    # Use the selected DB consistently, including bot.load_output_bundle fallback lookup.
    bot.DATABASE_PATH = db_path
    limit = None if args.all else max(1, min(int(args.limit), 1000))
    records = load_local_records(db_path, limit, include_archived_local=args.include_archived_local)
    logging.info("SQLite local: %s", db_path)
    logging.info("Bài có nội dung AI hoàn chỉnh phù hợp để đồng bộ: %s%s", len(records), " (toàn bộ)" if args.all else f" (giới hạn {limit})")
    if not records:
        logging.info("Không có bài hoàn chỉnh để chuyển. Cần có seo_title và seo_content trong bảng articles.")
        return 0

    if not args.apply:
        for article, draft in records:
            logging.info("DRY RUN [%s]: %s | %s", article.get("status", "unknown"), draft.get("seo_title") or article.get("source_title"), article.get("source_url"))
        logging.info("Chưa ghi dữ liệu. Chạy lại với --apply để gửi các bài lên Neon qua Vercel API.")
        return 0

    if not site.SITE_SYNC_ENABLED:
        raise SystemExit("Thiếu SITE_SYNC_ENABLED=true trong .env của crawler.")
    if not site.SITE_URL or not site.SITE_INGEST_API_KEY:
        raise SystemExit("Thiếu SITE_URL hoặc SITE_INGEST_API_KEY trong .env của crawler.")
    # Do not create/update anything until production confirms auth, Neon connection, and publish mode.
    site._HEALTH_CHECKED = False
    site._check_api_ready()
    site.ensure_table(db_path)

    published = 0
    already = 0
    archived = 0
    failed = 0
    for index, (article, draft) in enumerate(records, start=1):
        title = draft.get("seo_title") or article.get("source_title") or article.get("source_url")
        try:
            result = _sync_one(article, draft, db_path)
            if result["status"] == "published":
                published += 1
                logging.info("[%s/%s] ĐÃ XUẤT BẢN: %s -> %s", index, len(records), title, result.get("url"))
            elif result["status"] == "already_published":
                already += 1
                logging.info("[%s/%s] ĐÃ CÓ TRÊN NEON, bỏ qua: %s", index, len(records), title)
            else:
                archived += 1
                logging.info("[%s/%s] BỎ QUA bài archived: %s", index, len(records), title)
        except Exception as exc:
            failed += 1
            logging.exception("[%s/%s] LỖI đồng bộ: %s (%s)", index, len(records), title, type(exc).__name__)
        if args.pause and index < len(records):
            time.sleep(args.pause)

    logging.info("HOÀN TẤT: xuất bản mới/cập nhật=%d | đã xuất bản từ trước=%d | archived bỏ qua=%d | lỗi=%d", published, already, archived, failed)
    logging.info("Dữ liệu SQLite local vẫn được giữ nguyên; không xóa bài hay output.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
