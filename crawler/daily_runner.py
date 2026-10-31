"""Daily crawl/publish orchestration for GitHub Actions (no Telegram)."""
from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import main as bot
import site_publisher
import sync_to_site

log = logging.getLogger("travel-content-bot.daily")


def _env_int(name: str, default: int, minimum: int = 1, maximum: int = 10) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


MIN_DAILY_ARTICLES = _env_int("MIN_DAILY_ARTICLES", 3)
PREFERRED_DAILY_ARTICLES = _env_int("PREFERRED_DAILY_ARTICLES", 5)
MAX_DAILY_ARTICLES = _env_int("MAX_ARTICLES", 10)


def _complete(draft) -> bool:
    return bool(
        isinstance(draft, dict)
        and str(draft.get("seo_title") or "").strip()
        and str(draft.get("seo_content") or "").strip()
    )


def parse_args():
    parser = argparse.ArgumentParser(
        description="Publish 3-10 complete travel articles per day when sources and AI capacity allow."
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=MAX_DAILY_ARTICLES,
        help="Daily publication ceiling (1-10); defaults to MAX_ARTICLES or 10.",
    )
    return parser.parse_args()


def _log_daily_tier(total: int) -> None:
    if total >= MAX_DAILY_ARTICLES:
        log.info("Đã đạt trần ngày: %s/%s bài.", total, MAX_DAILY_ARTICLES)
    elif total >= PREFERRED_DAILY_ARTICLES:
        log.info("Đã đạt mục tiêu tốt: %s bài (mốc ưu tiên %s; trần %s).",
                 total, PREFERRED_DAILY_ARTICLES, MAX_DAILY_ARTICLES)
    elif total >= MIN_DAILY_ARTICLES:
        log.info("Đã đạt mức tối thiểu: %s bài (mục tiêu tiếp theo %s; trần %s).",
                 total, PREFERRED_DAILY_ARTICLES, MAX_DAILY_ARTICLES)
    else:
        log.warning(
            "Hôm nay mới xuất bản %s/%s bài tối thiểu; nguồn mới hoặc quota/AI/API chưa đủ. "
            "Các bài chưa hoàn chỉnh được giữ trong SQLite để thử lại ở lần chạy sau.",
            total, MIN_DAILY_ARTICLES,
        )


def main():
    args = parse_args()
    maximum = max(1, min(int(args.limit), MAX_DAILY_ARTICLES))
    minimum = min(MIN_DAILY_ARTICLES, maximum)
    preferred = min(PREFERRED_DAILY_ARTICLES, maximum)

    log.info(
        "Kế hoạch hôm nay: tối thiểu %s bài, mục tiêu ưu tiên %s bài, tối đa %s bài.",
        minimum, preferred, maximum,
    )

    db_path = bot.DATABASE_PATH
    bot.init_db()
    site_publisher.ensure_table(db_path)

    if not site_publisher.SITE_SYNC_ENABLED or not site_publisher.SITE_URL or not site_publisher.SITE_INGEST_API_KEY:
        raise SystemExit("Thiếu SITE_SYNC_ENABLED=true, SITE_URL hoặc SITE_INGEST_API_KEY trong môi trường chạy.")

    # Fail before spending AI calls if production deployment is misconfigured.
    site_publisher._check_api_ready()

    image_backfill_limit = _env_int("IMAGE_BACKFILL_PER_RUN", 5, minimum=1, maximum=25)
    image_backfill = site_publisher.backfill_missing_cover_images(db_path, limit=image_backfill_limit)
    log.info(
        "Bù ảnh bài cũ: đã kiểm tra %(checked)s, cập nhật %(updated)s, chưa tìm được %(unmatched)s, lỗi %(failed)s.",
        image_backfill,
    )

    recovered_published = 0
    published_articles = []
    pending_rows = site_publisher.list_pending_drafts(db_path, limit=maximum)
    for row in pending_rows:
        if recovered_published >= maximum:
            break
        article, draft = sync_to_site._article_and_draft(row)
        if not _complete(draft):
            log.warning("Bỏ qua artifact chưa hoàn chỉnh, chờ lần crawl sau: %s", row.get("source_url"))
            continue
        try:
            result = site_publisher.sync_draft_to_site(article, draft, db_path)
        except Exception as exc:
            message = str(exc).casefold()
            if any(marker in message for marker in ("cover image", "ảnh đại diện", "giấy phép sử dụng")):
                log.warning(
                    "Bài chờ chưa có ảnh đại diện đạt điều kiện; giữ lại để thử ở lần chạy sau: %s",
                    row.get("source_url"),
                )
                continue
            log.exception("Không thể khôi phục bài đang chờ xuất bản: %s", row.get("source_url"))
            raise SystemExit(1) from exc
        if not result.get("ok") and not result.get("skipped"):
            log.error("Bài chờ chưa xuất bản: %s", result.get("error", "lỗi không rõ"))
            raise SystemExit(1)
        if result.get("status") == "published" and not result.get("skipped"):
            recovered_published += 1
            published_articles.append({
                "title": str(row.get("seo_title") or row.get("source_title") or "Bài viết mới"),
                "url": result.get("site_url") or "",
            })
            log.info("Đã xuất bản lại bài đang chờ: %s", result.get("site_url"))

    remaining = maximum - recovered_published
    log.info(
        "Đã khôi phục %s bài; hôm nay còn chỗ cho tối đa %s bài mới.",
        recovered_published, remaining,
    )

    new_published = 0
    ai_quota_stop = False
    failed = 0
    crawler_result = {}
    if remaining > 0:
        # The crawler targets the daily ceiling, not a fixed quota. It stops early
        # only when all configured AI providers have hit a capacity/auth failure.
        crawler_result = bot.main(["--limit", str(remaining)]) or {}
        new_published = int(crawler_result.get("published_count", 0) or 0)
        failed = int(crawler_result.get("failed", 0) or 0)
        ai_quota_stop = bool(crawler_result.get("ai_quota_stop"))
        published_articles.extend(crawler_result.get("published_articles") or [])
    else:
        bot._reconcile_site_publications()
        bot.cleanup_published_artifacts()
        log.info("Đã đủ trần %s bài trong ngày; không crawl thêm.", maximum)

    total_published = recovered_published + new_published
    _log_daily_tier(total_published)

    discovery = crawler_result.get("discovery") if isinstance(crawler_result.get("discovery"), dict) else {}
    feed_errors = discovery.get("feed_errors") if isinstance(discovery.get("feed_errors"), list) else []
    feed_stats = discovery.get("feed_stats") if isinstance(discovery.get("feed_stats"), list) else []
    failure_items = crawler_result.get("failure_items") if isinstance(crawler_result.get("failure_items"), list) else []
    candidate_url_count = int(crawler_result.get("candidate_url_count", discovery.get("candidate_urls", 0)) or 0)
    attempted_urls = int(crawler_result.get("attempted", 0) or 0)
    processed_articles = int(crawler_result.get("processed_articles", 0) or 0)
    duplicate_skipped_count = int(crawler_result.get("duplicate_skipped_count", 0) or 0)
    irrelevant_skipped_count = int(crawler_result.get("irrelevant_skipped_count", 0) or 0)
    duration_seconds = float(crawler_result.get("duration_seconds", 0) or 0)

    if ai_quota_stop:
        report_status = "quota_limited"
    elif total_published == 0 and int(discovery.get("failed_feeds", 0) or 0) > 0 and candidate_url_count == 0:
        report_status = "source_error"
    elif total_published == 0 and irrelevant_skipped_count > 0 and processed_articles == 0 and failed == 0:
        report_status = "no_relevant_articles"
    elif total_published == 0 and attempted_urls == 0:
        report_status = "no_new_articles"
    elif total_published == 0:
        report_status = "no_posts"
    elif total_published < minimum:
        report_status = "below_minimum"
    elif failed or feed_errors:
        report_status = "warning"
    else:
        report_status = "completed"

    report = {
        "date": datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).strftime("%Y-%m-%d"),
        "generated_at": datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).isoformat(),
        "status": report_status,
        "minimum": minimum,
        "preferred": preferred,
        "maximum": maximum,
        "published_count": total_published,
        "failed_count": failed,
        "recovered_count": recovered_published,
        "new_published_count": new_published,
        "enabled_source_count": int(discovery.get("enabled_sources", 0) or 0),
        "successful_feed_count": int(discovery.get("successful_feeds", 0) or 0),
        "failed_feed_count": int(discovery.get("failed_feeds", 0) or 0),
        "feeds_with_items_count": int(discovery.get("feeds_with_items", 0) or 0),
        "candidate_url_count": candidate_url_count,
        "attempted_url_count": attempted_urls,
        "processed_article_count": processed_articles,
        "duplicate_skipped_count": duplicate_skipped_count,
        "irrelevant_skipped_count": irrelevant_skipped_count,
        "retry_candidate_count": int(discovery.get("retry_candidates", 0) or 0),
        "image_backfill_checked": int(image_backfill.get("checked", 0) or 0),
        "image_backfill_updated": int(image_backfill.get("updated", 0) or 0),
        "image_backfill_unmatched": int(image_backfill.get("unmatched", 0) or 0),
        "image_backfill_failed": int(image_backfill.get("failed", 0) or 0),
        "duration_seconds": duration_seconds,
        "ai_quota_stop": ai_quota_stop,
        "site_url": site_publisher.SITE_URL,
        "articles": published_articles,
        "feed_stats": feed_stats[:30],
        "feed_errors": feed_errors[:20],
        "failures": failure_items[:20],
    }
    report_dir = Path(bot.PROJECT_DIR) / "logs"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "daily-report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("Đã tạo báo cáo xuất bản: %s", report_path)

    if failed and not ai_quota_stop:
        raise SystemExit(1)

    if ai_quota_stop:
        log.warning(
            "Run kết thúc sớm vì AI quota/rate limit; không tiếp tục tiêu token trong hôm nay. "
            "URL chưa có bản AI hoàn chỉnh sẽ được thử lại vào lịch ngày mai."
        )


if __name__ == "__main__":
    main()
