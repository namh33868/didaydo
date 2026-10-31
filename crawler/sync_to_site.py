"""Push an already-generated AI draft to the website as a DRAFT (no AI calls).

Examples:
  python sync_to_site.py --source-url "https://source.example/article"
  python sync_to_site.py --limit 3 --dry-run
  python sync_to_site.py --check-status
"""
import argparse
import json
import sqlite3
import sys

import main as bot
import site_publisher


def parse_args():
    parser = argparse.ArgumentParser(description="Đồng bộ bài AI đã có lên website ở trạng thái bản nháp.")
    parser.add_argument("--source-url", help="Chỉ đồng bộ một bài theo URL nguồn đã có trong SQLite")
    parser.add_argument("--limit", type=int, default=3, help="Số bản nháp tối đa khi không truyền --source-url (mặc định 3, tối đa 10)")
    parser.add_argument("--dry-run", action="store_true", help="Chỉ hiển thị payload tóm tắt, không gọi website API")
    parser.add_argument("--force", action="store_true", help="Gửi cập nhật lại dù bài đã được đồng bộ trước đó (vẫn là draft nếu website status đang draft)")
    parser.add_argument("--check-status", action="store_true", help="Kiểm tra website có bài nào đã được xuất bản để cập nhật lịch sử/dọn output")
    return parser.parse_args()


def _draft_complete(draft):
    if not isinstance(draft, dict):
        return False
    return bool(str(draft.get("seo_title") or "").strip() and str(draft.get("seo_content") or "").strip())


def _article_and_draft(row):
    source_url = row.get("source_url") or ""
    article = {
        "source_url": source_url,
        "source_title": row.get("source_title") or "",
        "source_summary": row.get("source_summary") or "",
        "published_at": row.get("published_at"),
        "source_image_url": row.get("source_image_url") or "",
        "image_credit": row.get("image_credit") or "",
        "image_credit_url": row.get("image_credit_url") or "",
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
    try:
        with sqlite3.connect(bot.DATABASE_PATH, timeout=30) as conn:
            conn.row_factory = sqlite3.Row
            tax = conn.execute(
                "SELECT * FROM article_taxonomy WHERE source_url=?",
                (bot.normalize_url(source_url) or source_url,),
            ).fetchone()
            if tax:
                tax = dict(tax)
                for key in ("source_id", "source_name", "source_domain", "source_language", "source_feed_url", "destination_country", "destination_city", "destination_status", "primary_category", "taxonomy_path", "topic_confidence"):
                    if tax.get(key) not in (None, ""):
                        article[key] = tax[key]
                for source_key, target_key in (("destination_countries_json", "destination_countries"), ("categories_json", "topic_categories")):
                    try:
                        article[target_key] = json.loads(tax.get(source_key) or "[]")
                    except (TypeError, json.JSONDecodeError):
                        article[target_key] = []
    except sqlite3.Error:
        pass

    try:
        bundle = bot.load_output_bundle(source_url)
    except (OSError, ValueError, json.JSONDecodeError):
        bundle = None
    draft = None
    if isinstance(bundle, dict):
        saved_article = bundle.get("article")
        if isinstance(saved_article, dict):
            # Artifact is richer than SQLite for taxonomy and per-image captions.
            article.update({k: v for k, v in saved_article.items() if v not in (None, "", [], {})})
        candidate = bundle.get("draft")
        if _draft_complete(candidate):
            draft = candidate
    if not draft:
        candidate = {
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
        if _draft_complete(candidate):
            draft = candidate
    article["source_url"] = source_url
    return article, draft


def _select_rows(args):
    if args.source_url:
        canonical = bot.normalize_url(args.source_url) or args.source_url
        with sqlite3.connect(bot.DATABASE_PATH, timeout=30) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM articles WHERE source_url=?", (canonical,)).fetchone()
            return [dict(row)] if row else []
    return site_publisher.list_pending_drafts(bot.DATABASE_PATH, args.limit)


def main():
    args = parse_args()
    bot.init_db()
    site_publisher.ensure_table(bot.DATABASE_PATH)

    if args.check_status:
        results = site_publisher.reconcile_published_posts(bot.DATABASE_PATH, bot.mark_published)
        print(f"Đã kiểm tra trạng thái website; số bài website xác nhận published: {len(results)}")
        for item in results:
            print("-", item.get("source_url"), "=>", item.get("publish_url"), "cleanup=", item.get("cleanup_complete"))
        return 0

    if not site_publisher.SITE_SYNC_ENABLED:
        print("Website sync đang tắt. Thêm SITE_SYNC_ENABLED=true vào .env của crawler rồi chạy lại.")
        return 2
    if not site_publisher.SITE_URL or not site_publisher.SITE_INGEST_API_KEY:
        print("Thiếu SITE_URL hoặc SITE_INGEST_API_KEY trong .env của crawler. Không có key nào được in ra.")
        return 2

    rows = _select_rows(args)
    if not rows:
        print("Không tìm thấy bài trong SQLite. Chạy python main.py để crawl, hoặc truyền --source-url đúng URL đã lưu.")
        return 1

    ok, skipped, failed = 0, 0, 0
    for row in rows:
        article, draft = _article_and_draft(row)
        source_url = article.get("source_url") or ""
        if not _draft_complete(draft):
            print(f"Bỏ qua vì chưa có bài AI hoàn chỉnh: {source_url}")
            failed += 1
            continue
        if args.dry_run:
            try:
                if not site_publisher.SOURCE_IMAGE_REUSE_AUTHORIZED:
                    selected_cover = site_publisher._ensure_editorial_cover_image(article, bot.DATABASE_PATH)
                    if not selected_cover:
                        raise RuntimeError("Không tìm được ảnh đại diện phù hợp có giấy phép sử dụng.")
                payload = site_publisher.build_site_payload(article, draft)
                print("\nDRY RUN — chưa gửi website")
                print("Nguồn:", source_url)
                print("Tiêu đề:", payload["title"])
                print("Danh mục:", payload["category"])
                print("Tags:", ", ".join(payload["tags"]))
                print("Ảnh đại diện:", payload["coverImage"])
                print("HTML:", len(payload["contentHtml"]), "ký tự")
                print("Trạng thái đích: draft")
                ok += 1
            except Exception as exc:
                print(f"DRY RUN không đạt: {type(exc).__name__}: {str(exc)[:300]}")
                failed += 1
            continue
        try:
            result = site_publisher.sync_draft_to_site(article, draft, bot.DATABASE_PATH, force=args.force)
            if result.get("skipped"):
                print(f"Đã đồng bộ trước đó — bỏ qua: {source_url} ({result.get('status')})")
                skipped += 1
            elif result.get("ok"):
                print(f"Đã gửi bản nháp lên website: {result.get('status')} | {result.get('slug')} | {result.get('site_url')}")
                ok += 1
        except Exception as exc:
            print(f"LỖI đồng bộ {source_url}: {type(exc).__name__}: {str(exc)[:400]}")
            failed += 1

    print(f"\nKết quả: thành công/dry-run={ok} | bỏ qua={skipped} | lỗi={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
