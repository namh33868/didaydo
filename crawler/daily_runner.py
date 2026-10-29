"""Run the daily publish quota: retry pending AI articles, then crawl new ones.

This script is used by GitHub Actions. It has no Telegram dependency.
"""
from __future__ import annotations

import argparse
import logging
import os

import main as bot
import site_publisher
import sync_to_site

log = logging.getLogger("travel-content-bot.daily")


def _complete(draft) -> bool:
    return bool(
        isinstance(draft, dict)
        and str(draft.get("seo_title") or "").strip()
        and str(draft.get("seo_content") or "").strip()
    )


def parse_args():
    parser = argparse.ArgumentParser(
        description="Retry pending articles, then publish up to N new travel articles without Telegram."
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=int(os.getenv("MAX_ARTICLES", "10")),
        help="Total number of newly published articles to target (default: MAX_ARTICLES or 10).",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    target = max(1, min(int(args.limit), 10))
    db_path = bot.DATABASE_PATH
    bot.init_db()
    site_publisher.ensure_table(db_path)

    if not site_publisher.SITE_SYNC_ENABLED or not site_publisher.SITE_URL or not site_publisher.SITE_INGEST_API_KEY:
        raise SystemExit("Thiếu SITE_SYNC_ENABLED=true, SITE_URL hoặc SITE_INGEST_API_KEY trong môi trường chạy.")

    # Fail before spending AI calls if production deployment is misconfigured.
    site_publisher._check_api_ready()

    recovered_published = 0
    pending_rows = site_publisher.list_pending_drafts(db_path, limit=target)
    for row in pending_rows:
        if recovered_published >= target:
            break
        article, draft = sync_to_site._article_and_draft(row)
        if not _complete(draft):
            log.warning("Bỏ qua artifact chưa hoàn chỉnh, chưa gọi AI lại: %s", row.get("source_url"))
            continue
        try:
            result = site_publisher.sync_draft_to_site(article, draft, db_path)
        except Exception as exc:
            log.exception("Không thể khôi phục bài đang chờ xuất bản: %s", row.get("source_url"))
            raise SystemExit(1) from exc
        if not result.get("ok") and not result.get("skipped"):
            log.error("Bài chờ chưa xuất bản: %s", result.get("error", "lỗi không rõ"))
            raise SystemExit(1)
        if result.get("status") == "published" and not result.get("skipped"):
            recovered_published += 1
            log.info("Đã xuất bản lại bài đang chờ: %s", result.get("site_url"))

    remaining = target - recovered_published
    log.info("Quota ngày=%s; khôi phục được %s bài; sẽ crawl tối đa %s bài mới.", target, recovered_published, remaining)
    if remaining > 0:
        # main.py already handles duplicate detection, AI generation, output checkpoints,
        # and direct website publishing. Its Telegram sending calls are no longer used.
        bot.main(["--limit", str(remaining)])
    else:
        bot._reconcile_site_publications()
        bot.cleanup_published_artifacts()
        log.info("Đã đủ quota %s bài; không crawl thêm để tránh vượt hạn mức ngày.", target)


if __name__ == "__main__":
    main()
