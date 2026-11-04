"""Compact start/progress/final email notifications for the daily travel crawler."""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import smtplib
import ssl
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

REPORT_PATH = Path(__file__).resolve().parent / "logs" / "daily-report.json"
_PROGRESS_NOTIFICATION_SENT = False
VIETNAM_TZ = ZoneInfo("Asia/Ho_Chi_Minh")

STATUS_LABELS = {
    "completed": "ĐÃ HOÀN THÀNH",
    "warning": "ĐÃ ĐĂNG BÀI · CÓ LỖI",
    "below_minimum": "CHƯA ĐẠT MỤC TIÊU",
    "quota_limited": "DỪNG DO GIỚI HẠN AI",
    "ai_provider_unavailable": "AI TẠM THỜI KHÔNG KHẢ DỤNG",
    "source_error": "LỖI NGUỒN RSS",
    "no_new_articles": "KHÔNG CÓ BÀI MỚI",
    "no_relevant_articles": "KHÔNG CÓ BÀI PHÙ HỢP",
    "no_posts": "CHƯA ĐĂNG ĐƯỢC BÀI",
    "fatal_error": "LỖI KHI XUẤT BẢN",
    "report_missing": "KHÔNG TẠO ĐƯỢC BÁO CÁO",
    "running": "ĐANG CHẠY",
}


def _now() -> datetime:
    return datetime.now(VIETNAM_TZ)


def _load_report() -> dict:
    try:
        value = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _esc(value) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _short_error(value, limit: int = 112) -> str:
    """Turn provider/HTTP trace fragments into short, readable Vietnamese labels."""
    message = re.sub(r"\s+", " ", str(value or "")).strip()
    if not message:
        return "Không có mô tả lỗi."

    lower = message.casefold()
    if ("429" in lower or "rate limit" in lower or "tpm" in lower) and "groq" in lower:
        return "Groq vượt giới hạn tốc độ (429/TPM)."
    if "gemini" in lower and ("quota" in lower or "resource_exhausted" in lower):
        return "Gemini đã hết hạn mức sử dụng."
    if "quota" in lower or "resource_exhausted" in lower:
        return "AI đã hết hạn mức sử dụng."
    if "invalid json" in lower or "json validation" in lower or "json không hợp lệ" in lower:
        return "AI trả về dữ liệu sai định dạng."
    if "max token" in lower or "truncat" in lower or "empty output" in lower or "nội dung rỗng" in lower:
        return "AI trả về nội dung rỗng hoặc bị cắt."
    if "timeout" in lower or "timed out" in lower or "hết thời gian" in lower:
        return "Dịch vụ phản hồi quá thời gian chờ."
    if "không tìm được ảnh" in lower or "không có ảnh hợp lệ" in lower or "cover image" in lower:
        return "Không tìm được ảnh bìa phù hợp và đủ quyền sử dụng."
    if "neon" in lower and ("connect" in lower or "database" in lower):
        return "Không kết nối được cơ sở dữ liệu."
    if "401" in lower or "unauthorized" in lower or "403" in lower:
        return "API từ chối truy cập (kiểm tra khóa hoặc quyền)."
    if "500" in lower or "502" in lower or "503" in lower or "504" in lower:
        return "Dịch vụ bên ngoài đang gặp sự cố."
    if len(message) <= limit:
        return message
    return message[: max(1, limit - 3)].rstrip(" ,;:.-") + "..."


def _run_url() -> str:
    explicit = os.getenv("GITHUB_RUN_URL", "").strip()
    if explicit.startswith(("https://", "http://")):
        return explicit
    server = os.getenv("GITHUB_SERVER_URL", "https://github.com").rstrip("/")
    repository = os.getenv("GITHUB_REPOSITORY", "").strip()
    run_id = os.getenv("GITHUB_RUN_ID", "").strip()
    if repository and run_id:
        return f"{server}/{repository}/actions/runs/{run_id}"
    return ""


def _recipients() -> list[str]:
    value = os.getenv("REPORT_EMAIL_TO", "").strip()
    return [item.strip() for item in value.replace(";", ",").split(",") if item.strip()]


def _status_label(report: dict, job_status: str, stage: str = "final") -> str:
    if stage == "started":
        return "ĐANG CHẠY"
    if stage == "progress":
        return "ĐÃ CÓ BÀI MỚI"
    if str(job_status).lower() not in {"success", "unknown"}:
        return "WORKFLOW THẤT BẠI"
    return STATUS_LABELS.get(str(report.get("status") or "report_missing"), "CẦN KIỂM TRA")


def _subject(report: dict, job_status: str, stage: str) -> str:
    date = str(report.get("date") or _now().strftime("%Y-%m-%d"))
    if stage == "started":
        return f"[Đi Đây Đó] BẮT ĐẦU CRAWL · {date}"
    if stage == "progress":
        count = int(report.get("published_count") or 1)
        return f"[Đi Đây Đó] ĐÃ ĐĂNG {count} BÀI · {date}"
    count = int(report.get("published_count") or 0)
    label = _status_label(report, job_status, stage)
    return f"[Đi Đây Đó] {label} · {date} · {count} bài"


def _duration(value) -> str:
    try:
        seconds = max(0, int(float(value or 0)))
    except (TypeError, ValueError):
        seconds = 0
    minutes, secs = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours} giờ {minutes} phút"
    if minutes:
        return f"{minutes} phút"
    return f"{secs} giây"


def _article_list(articles: list[dict]) -> str:
    rows = []
    for item in articles[:10]:
        if not isinstance(item, dict):
            continue
        title = _esc(item.get("title") or "Bài viết mới")
        url = str(item.get("url") or "").strip()
        if url.startswith(("https://", "http://")):
            rows.append(
                f"<li style='margin:0 0 8px'><a href='{_esc(url)}' "
                f"style='color:#176b50;text-decoration:none'>{title}</a></li>"
            )
        else:
            rows.append(f"<li style='margin:0 0 8px'>{title}</li>")
    return "<ol style='padding-left:22px;margin:8px 0'>" + "".join(rows) + "</ol>" if rows else (
        "<p style='margin:8px 0;color:#667085'>Chưa có bài nào được xác nhận xuất bản.</p>"
    )


def _failure_list(report: dict) -> str:
    failures = report.get("failures")
    failures = failures if isinstance(failures, list) else []
    entries = []
    for item in failures[:8]:
        if not isinstance(item, dict):
            continue
        title = _esc(item.get("title") or "Bài chưa rõ tiêu đề")
        stage = str(item.get("stage") or "")
        stage_label = {
            "ai": "AI",
            "publish": "Đăng bài",
            "extract_or_process": "Đọc nguồn",
        }.get(stage, "Xử lý")
        reason = _esc(_short_error(item.get("reason")))
        entries.append(
            "<tr>"
            f"<td style='padding:8px 6px;border-top:1px solid #eaecf0;font-size:13px'>{title}"
            f"<div style='color:#98a2b3;font-size:11px'>{stage_label}</div></td>"
            "<td style='padding:8px 6px;border-top:1px solid #eaecf0;font-size:13px;"
            "max-width:260px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis'>"
            f"<span title='{reason}'>{reason}</span></td>"
            "</tr>"
        )

    if not entries and report.get("fatal_error_reason"):
        reason = _esc(_short_error(report.get("fatal_error_reason")))
        entries.append(
            "<tr><td colspan='2' style='padding:8px 6px;border-top:1px solid #eaecf0;"
            "font-size:13px;max-width:260px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis'>"
            f"<span title='{reason}'>{reason}</span></td></tr>"
        )

    if not entries:
        return ""

    extra = len(failures) - min(len(failures), 8)
    more = f"<p style='margin:6px 0;color:#667085;font-size:12px'>Còn {extra} lỗi khác trong log.</p>" if extra > 0 else ""
    return (
        "<h2 style='font-size:15px;margin:22px 0 6px'>Lỗi cần chú ý</h2>"
        "<table role='presentation' width='100%' cellspacing='0' cellpadding='0' "
        "style='border-collapse:collapse;table-layout:fixed'>"
        "<tr><th align='left' style='padding:6px;font-size:11px;color:#667085'>Bài / công đoạn</th>"
        "<th align='left' style='padding:6px;font-size:11px;color:#667085'>Nguyên nhân</th></tr>"
        + "".join(entries) + "</table>" + more
    )


def _build_html(
    report: dict,
    job_status: str,
    run_url: str,
    stage: str = "final",
    article_title: str = "",
    article_url: str = "",
) -> str:
    date = _esc(report.get("date") or _now().strftime("%Y-%m-%d"))
    count = int(report.get("published_count") or 0)
    minimum = int(report.get("minimum") or 3)
    preferred = int(report.get("preferred") or 5)
    maximum = int(report.get("maximum") or 10)
    failures_count = int(report.get("failed_count") or 0)
    failed_feeds = int(report.get("failed_feed_count") or 0)
    successful_feeds = int(report.get("successful_feed_count") or 0)
    label = _status_label(report, job_status, stage)
    palette = {
        "ĐANG CHẠY": ("#eff6ff", "#1d4ed8"),
        "ĐÃ CÓ BÀI MỚI": ("#ecfdf3", "#067647"),
        "ĐÃ HOÀN THÀNH": ("#ecfdf3", "#067647"),
        "ĐÃ ĐĂNG BÀI · CÓ LỖI": ("#fffaeb", "#b54708"),
        "WORKFLOW THẤT BẠI": ("#fef3f2", "#b42318"),
    }
    bg, fg = palette.get(label, ("#fffaeb", "#b54708"))

    if stage == "started":
        heading = "Crawler đã bắt đầu"
        intro = "Hệ thống đang thu thập nguồn và xử lý bài. Email tiếp theo sẽ báo khi có bài được đăng hoặc khi lượt chạy kết thúc."
        details = (
            "<div style='margin-top:18px;padding:14px;background:#f8fafc;border-radius:8px'>"
            "<strong>Trạng thái hiện tại:</strong> Đang chạy · Chưa có bài được xác nhận xuất bản."
            "</div>"
        )
    elif stage == "progress":
        heading = "Đã có bài mới trên website"
        safe_title = _esc(article_title or "Bài viết mới")
        safe_url = str(article_url or "").strip()
        title_markup = (
            f"<a href='{_esc(safe_url)}' style='color:#176b50;text-decoration:none'>{safe_title}</a>"
            if safe_url.startswith(("https://", "http://")) else safe_title
        )
        details = (
            "<div style='margin-top:18px;padding:14px;background:#ecfdf3;border-radius:8px'>"
            f"<strong>Bài vừa đăng:</strong><div style='margin-top:6px'>{title_markup}</div>"
            "</div>"
        )
        intro = "Crawler vẫn đang tiếp tục. Email tổng kết sẽ gửi khi hoàn tất hoặc dừng do lỗi."
    else:
        heading = "Kết quả lượt crawler"
        intro = (
            "Workflow đã kết thúc thành công."
            if str(job_status).lower() == "success"
            else "Workflow gặp lỗi hoặc bị dừng. Dưới đây là kết quả ghi nhận được trước thời điểm dừng."
        )
        articles = report.get("articles") if isinstance(report.get("articles"), list) else []
        details = (
            "<h2 style='font-size:15px;margin:22px 0 6px'>Bài đã xuất bản</h2>"
            + _article_list(articles)
            + _failure_list(report)
        )
        if not articles and not report.get("failures") and report.get("fatal_error_reason"):
            details += (
                "<p style='margin:10px 0;color:#b42318;font-size:13px'>"
                f"{_esc(_short_error(report.get('fatal_error_reason')))}</p>"
            )

    run_link = (
        f"<a href='{_esc(run_url)}' style='color:#176b50;text-decoration:none'>Mở chi tiết lượt chạy trên GitHub</a>"
        if run_url else ""
    )
    site_url = str(report.get("site_url") or os.getenv("SITE_URL") or "").strip().rstrip("/")
    site_link = (
        f"<a href='{_esc(site_url)}' style='color:#176b50;text-decoration:none'>Mở website</a>"
        if site_url.startswith(("https://", "http://")) else ""
    )
    links = " &nbsp;·&nbsp; ".join(item for item in (run_link, site_link) if item)

    metrics = (
        "<table role='presentation' width='100%' cellspacing='0' cellpadding='0' "
        "style='margin-top:18px;border-collapse:separate;border-spacing:6px 0;text-align:center'>"
        "<tr>"
        f"<td style='width:33%;padding:12px 6px;background:#f8fafc;border-radius:8px'>"
        f"<div style='font-size:25px;font-weight:700;color:#176b50'>{count}</div>"
        "<div style='font-size:11px;color:#667085'>Bài đã đăng</div></td>"
        f"<td style='width:33%;padding:12px 6px;background:#f8fafc;border-radius:8px'>"
        f"<div style='font-size:25px;font-weight:700'>{minimum}</div>"
        "<div style='font-size:11px;color:#667085'>Tối thiểu</div></td>"
        f"<td style='width:33%;padding:12px 6px;background:#f8fafc;border-radius:8px'>"
        f"<div style='font-size:25px;font-weight:700'>{failures_count}</div>"
        "<div style='font-size:11px;color:#667085'>Bài lỗi</div></td>"
        "</tr></table>"
    )

    extra_stats = ""
    if stage == "final":
        extra_stats = (
            f"<p style='margin:12px 0 0;color:#667085;font-size:12px'>"
            f"RSS: {successful_feeds} feed đọc được · {failed_feeds} feed lỗi"
            f" &nbsp;|&nbsp; Mục tiêu: {minimum} tối thiểu / {preferred} mong muốn / {maximum} tối đa"
            f" &nbsp;|&nbsp; Thời gian: {_esc(_duration(report.get('duration_seconds')))}"
            "</p>"
        )

    return f"""<!doctype html>
<html lang="vi"><body style="margin:0;padding:20px;background:#f5f7f6;font-family:Arial,Helvetica,sans-serif;color:#202124;line-height:1.5">
<div style="max-width:600px;margin:0 auto;background:#fff;border:1px solid #e4e7ec;border-radius:12px;overflow:hidden">
  <div style="padding:20px 22px;border-bottom:1px solid #eaecf0">
    <div style="font-size:11px;font-weight:700;letter-spacing:1px;color:#667085">ĐI ĐÂY ĐÓ · CRAWLER</div>
    <h1 style="font-size:21px;line-height:1.3;margin:8px 0 6px">{heading}</h1>
    <span style="display:inline-block;padding:4px 9px;border-radius:20px;background:{bg};color:{fg};font-size:11px;font-weight:700">{_esc(label)}</span>
    <p style="margin:10px 0 0;color:#667085;font-size:12px">Ngày {date}</p>
  </div>
  <div style="padding:18px 22px">
    <p style="margin:0;font-size:14px">{intro}</p>
    {metrics if stage != "started" else ""}
    {extra_stats}
    {details}
    <div style="margin-top:22px;padding-top:14px;border-top:1px solid #eaecf0;font-size:12px">{links}</div>
  </div>
</div></body></html>"""


def _build_text(
    report: dict,
    job_status: str,
    run_url: str,
    stage: str = "final",
    article_title: str = "",
    article_url: str = "",
) -> str:
    date = report.get("date") or _now().strftime("%Y-%m-%d")
    count = int(report.get("published_count") or 0)
    lines = [
        f"ĐI ĐÂY ĐÓ - {date}",
        _status_label(report, job_status, stage),
    ]
    if stage == "started":
        lines.append("Crawler đã bắt đầu. Hệ thống đang thu thập nguồn và xử lý bài.")
    elif stage == "progress":
        lines.extend([
            f"Đã xuất bản: {count} bài.",
            f"Bài vừa đăng: {article_title or 'Bài viết mới'}",
            article_url or "",
            "Crawler vẫn đang tiếp tục; sẽ có email tổng kết khi kết thúc hoặc dừng do lỗi.",
        ])
    else:
        lines.extend([
            f"Đã xuất bản: {count} bài.",
            f"Bài lỗi: {report.get('failed_count', 0)}.",
            f"RSS: {report.get('successful_feed_count', 0)} feed đọc được / {report.get('failed_feed_count', 0)} feed lỗi.",
            "",
            "BÀI ĐÃ XUẤT BẢN:",
        ])
        articles = report.get("articles") if isinstance(report.get("articles"), list) else []
        lines.extend(
            f"- {item.get('title') or 'Bài mới'}: {item.get('url') or ''}"
            for item in articles if isinstance(item, dict)
        )
        failures = report.get("failures") if isinstance(report.get("failures"), list) else []
        if failures:
            lines += ["", "LỖI CẦN CHÚ Ý:"]
            lines.extend(
                f"- {item.get('title') or 'Bài viết'}: {_short_error(item.get('reason'))}"
                for item in failures[:8] if isinstance(item, dict)
            )
        if report.get("fatal_error_reason") and not failures:
            lines.append(_short_error(report.get("fatal_error_reason")))
    if run_url:
        lines.extend(["", f"Chi tiết workflow: {run_url}"])
    return "\n".join(line for line in lines if line is not None)


def _send_email(
    report: dict,
    job_status: str,
    recipients: list[str],
    run_url: str,
    stage: str = "final",
    article_title: str = "",
    article_url: str = "",
) -> bool:
    subject = _subject(report, job_status, stage)
    text_body = _build_text(report, job_status, run_url, stage, article_title, article_url)
    html_body = _build_html(report, job_status, run_url, stage, article_title, article_url)

    username = os.getenv("GMAIL_USERNAME", "").strip()
    app_password = os.getenv("GMAIL_APP_PASSWORD", "").replace(" ", "").strip()
    if username and app_password:
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = os.getenv("REPORT_EMAIL_FROM", "").strip() or username
        message["To"] = ", ".join(recipients)
        message.set_content(text_body)
        message.add_alternative(html_body, subtype="html")
        context = ssl.create_default_context()
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as smtp:
            smtp.ehlo()
            smtp.starttls(context=context)
            smtp.ehlo()
            smtp.login(username, app_password)
            smtp.send_message(message)
        print(f"Đã gửi email ({stage}) qua Gmail tới {len(recipients)} địa chỉ.")
        return True

    api_key = os.getenv("RESEND_API_KEY", "").strip()
    sender = os.getenv("REPORT_EMAIL_FROM", "").strip()
    if api_key and sender:
        payload = {
            "from": sender,
            "to": recipients,
            "subject": subject,
            "html": html_body,
            "text": text_body,
        }
        request = Request(
            "https://api.resend.com/emails",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        with urlopen(request, timeout=25) as response:
            response.read()
            print(f"Đã gửi email ({stage}) qua Resend. HTTP {response.status}.")
        return True

    print("Email chưa được gửi: thiếu cấu hình Gmail SMTP hoặc Resend.")
    return False


def send_progress_notification(title: str, url: str = "", published_count: int = 1) -> bool:
    """Send one progress email on the first confirmed publication in this run."""
    global _PROGRESS_NOTIFICATION_SENT
    if _PROGRESS_NOTIFICATION_SENT:
        return False
    _PROGRESS_NOTIFICATION_SENT = True

    now = _now()
    report = _load_report()
    report.update({
        "date": report.get("date") or now.strftime("%Y-%m-%d"),
        "status": "running",
        "published_count": max(1, int(published_count or 1)),
        "minimum": int(os.getenv("MIN_DAILY_ARTICLES", "3")),
        "preferred": int(os.getenv("PREFERRED_DAILY_ARTICLES", "5")),
        "maximum": int(os.getenv("MAX_ARTICLES", "10")),
        "site_url": report.get("site_url") or os.getenv("SITE_URL", ""),
        "failed_count": int(report.get("failed_count") or 0),
    })
    try:
        recipients = _recipients()
        if not recipients:
            print("Bỏ qua email tiến độ: chưa cấu hình REPORT_EMAIL_TO.")
            return False
        return _send_email(report, "in_progress", recipients, _run_url(), "progress", title, url)
    except (smtplib.SMTPException, OSError, TimeoutError, HTTPError, URLError) as exc:
        print(f"Không gửi được email tiến độ ({type(exc).__name__}); crawler vẫn tiếp tục.")
        return False


def _write_summary(report: dict, job_status: str, run_url: str) -> None:
    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    date = report.get("date") or "không rõ ngày"
    articles = report.get("articles") if isinstance(report.get("articles"), list) else []
    lines = [
        f"## Báo cáo crawler Đi Đây Đó - {date}",
        f"- Kết luận: **{_status_label(report, job_status)}**",
        f"- Đã xuất bản: **{report.get('published_count', 0)} bài**",
        f"- Bài lỗi: **{report.get('failed_count', 0)}**",
        f"- RSS: {report.get('successful_feed_count', 0)} feed đọc được / {report.get('failed_feed_count', 0)} feed lỗi",
        f"- Thời gian: {_duration(report.get('duration_seconds'))}",
    ]
    for item in articles:
        if isinstance(item, dict):
            title = str(item.get("title") or "Bài viết mới")
            url = str(item.get("url") or "")
            lines.append(f"- [{title}]({url})" if url.startswith(("https://", "http://")) else f"- {title}")
    if run_url:
        lines.append(f"- [Mở workflow log]({run_url})")
    try:
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
    except OSError:
        pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=("started", "final"), default="final")
    parser.add_argument("--job-status", default=os.getenv("JOB_STATUS", "unknown"))
    args = parser.parse_args()

    stage = args.stage
    job_status = str(args.job_status or "unknown")
    report = _load_report()

    if stage == "started":
        report = {
            "date": _now().strftime("%Y-%m-%d"),
            "status": "running",
            "published_count": 0,
            "failed_count": 0,
            "minimum": int(os.getenv("MIN_DAILY_ARTICLES", "3")),
            "preferred": int(os.getenv("PREFERRED_DAILY_ARTICLES", "5")),
            "maximum": int(os.getenv("MAX_ARTICLES", "10")),
            "site_url": os.getenv("SITE_URL", ""),
            "articles": [],
            "failures": [],
        }
    elif not report:
        report = {
            "date": _now().strftime("%Y-%m-%d"),
            "status": "report_missing",
            "published_count": 0,
            "failed_count": 0,
            "minimum": 3,
            "preferred": 5,
            "maximum": 10,
            "articles": [],
            "failures": [],
            "fatal_error_reason": "Crawler dừng trước khi ghi được báo cáo; mở log workflow để xem bước lỗi.",
        }

    run_url = _run_url()
    if stage == "final":
        _write_summary(report, job_status, run_url)

    recipients = _recipients()
    if not recipients:
        print("Email chưa được gửi: hãy cấu hình REPORT_EMAIL_TO trong GitHub Secrets.")
        return 0

    try:
        sent = _send_email(report, job_status, recipients, run_url, stage)
        return 0 if sent else 0
    except (smtplib.SMTPException, OSError, TimeoutError, HTTPError, URLError) as exc:
        print(f"Gửi email thất bại ({stage}): {type(exc).__name__}.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
