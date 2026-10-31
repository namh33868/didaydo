"""Send a readable daily crawler operations report through Gmail SMTP or Resend."""
from __future__ import annotations

import argparse
import html
import json
import os
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

REPORT_PATH = Path(__file__).resolve().parent / "logs" / "daily-report.json"

STATUS_LABELS = {
    "completed": ("ĐẠT MỤC TIÊU", "#18794e"),
    "warning": ("ĐÃ CHẠY - CÓ CẢNH BÁO", "#9a6700"),
    "below_minimum": ("CHƯA ĐẠT MỨC TỐI THIỂU", "#9a6700"),
    "quota_limited": ("DỪNG DO GIỚI HẠN AI", "#9a6700"),
    "source_error": ("LỖI ĐỌC NGUỒN RSS", "#b42318"),
    "no_new_articles": ("KHÔNG CÓ BÀI MỚI ĐỂ XỬ LÝ", "#9a6700"),
    "no_relevant_articles": ("KHÔNG CÓ BÀI PHÙ HỢP DANH MỤC", "#9a6700"),
    "no_posts": ("CHƯA XUẤT BẢN ĐƯỢC BÀI", "#b42318"),
    "report_missing": ("KHÔNG TẠO ĐƯỢC BÁO CÁO CRAWLER", "#b42318"),
}


def _load_report() -> dict:
    try:
        value = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _esc(value) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


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
        return f"{minutes} phút {secs} giây"
    return f"{secs} giây"


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


def _status(report: dict, job_status: str) -> tuple[str, str]:
    key = str(report.get("status") or "report_missing")
    label, color = STATUS_LABELS.get(key, (key.upper(), "#57606a"))
    if str(job_status).lower() != "success":
        return ("WORKFLOW THẤT BẠI", "#b42318")
    return label, color


def _next_step(report: dict, job_status: str) -> str:
    if str(job_status).lower() != "success":
        if report.get("status") == "report_missing":
            return "Crawler dừng trước khi tạo báo cáo. Mở link GitHub Actions để xem bước cấu hình/API nào bị lỗi."
        return "Mở log GitHub Actions để xem bước thất bại. Báo cáo nội dung bên dưới chỉ phản ánh phần đã chạy được."
    status = report.get("status")
    if status == "completed":
        return "Đã đạt mục tiêu tối thiểu. Kiểm tra các đường dẫn bài viết bên dưới và tiếp tục theo dõi traffic trong GA4."
    if status == "warning":
        return "Crawler có xuất bản bài nhưng một số nguồn hoặc URL gặp lỗi. Xem danh sách nguồn lỗi để biết nguồn nào cần xử lý."
    if status == "below_minimum":
        return "Đã có bài xuất bản nhưng chưa đạt 3 bài tối thiểu. Kiểm tra lỗi AI, lỗi URL và nguồn RSS; các bài AI chưa hoàn chỉnh được giữ để thử lại."
    if status == "quota_limited":
        return "AI đã chạm quota hoặc rate limit. Crawler dừng gọi AI để tránh tiêu token tiếp; bài chưa hoàn chỉnh sẽ được thử lại ở lịch sau."
    if status == "source_error":
        return "Không đọc được các nguồn RSS. Kiểm tra parser XML, feed URL và các lỗi 403/503/SSL ở bảng nguồn lỗi."
    if status == "no_relevant_articles":
        return "Có URL mới nhưng không bài nào khớp các danh mục biên tập hiện tại. Kiểm tra nguồn RSS hoặc bổ sung từ khóa phân loại nếu nguồn có nội dung du lịch phù hợp."
    if status == "no_new_articles":
        return "Các feed đã đọc được nhưng không có URL mới đủ điều kiện. Kiểm tra lại vào lượt chạy kế tiếp."
    if status == "no_posts":
        return "Có URL được xử lý nhưng chưa xuất bản được bài nào. Kiểm tra lỗi xử lý bài, AI hoặc API xuất bản bên dưới."
    return "Mở log GitHub Actions để kiểm tra chi tiết lượt chạy."


def _table_rows(rows: list[dict], *, source_rows: bool = False) -> str:
    rendered = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        if source_rows:
            name = _esc(item.get("name") or "Nguồn không rõ")
            status = "Lỗi" if item.get("status") == "failed" else "Đọc được"
            entries = _esc(item.get("entries", 0))
            reason = _esc(item.get("error") or "—")
            rendered.append(
                f"<tr><td>{name}</td><td>{status}</td><td style='text-align:right'>{entries}</td><td>{reason}</td></tr>"
            )
        else:
            title = _esc(item.get("title") or "Bài viết chưa rõ tiêu đề")
            source = _esc(item.get("source") or "Không rõ nguồn")
            stage_key = str(item.get("stage") or "processing")
            stage = _esc({
                "ai": "Tạo nội dung AI",
                "publish": "Đăng lên website",
                "extract_or_process": "Đọc/trích xuất bài nguồn",
            }.get(stage_key, stage_key))
            reason = _esc(item.get("reason") or "Không có mô tả lỗi")
            rendered.append(
                f"<tr><td>{title}</td><td>{source}</td><td>{stage}</td><td>{reason}</td></tr>"
            )
    return "".join(rendered)


def _build_html(report: dict, job_status: str, run_url: str) -> str:
    articles = report.get("articles") if isinstance(report.get("articles"), list) else []
    feed_errors = report.get("feed_errors") if isinstance(report.get("feed_errors"), list) else []
    failures = report.get("failures") if isinstance(report.get("failures"), list) else []
    feed_stats = report.get("feed_stats") if isinstance(report.get("feed_stats"), list) else []
    date = _esc(report.get("date") or "Không có dữ liệu ngày chạy")
    count = int(report.get("published_count") or 0)
    minimum = int(report.get("minimum") or 3)
    preferred = int(report.get("preferred") or 5)
    maximum = int(report.get("maximum") or 10)
    label, color = _status(report, job_status)

    enabled = int(report.get("enabled_source_count") or 0)
    ok_feeds = int(report.get("successful_feed_count") or 0)
    failed_feeds = int(report.get("failed_feed_count") or 0)
    feeds_with_items = int(report.get("feeds_with_items_count") or 0)
    candidates = int(report.get("candidate_url_count") or 0)
    attempted = int(report.get("attempted_url_count") or 0)
    processed = int(report.get("processed_article_count") or 0)
    duplicate_count = int(report.get("duplicate_skipped_count") or 0)
    irrelevant_count = int(report.get("irrelevant_skipped_count") or 0)
    retry_count = int(report.get("retry_candidate_count") or 0)
    failed_articles = int(report.get("failed_count") or 0)
    duration = _duration(report.get("duration_seconds"))
    recovered = int(report.get("recovered_count") or 0)
    new_count = int(report.get("new_published_count") or max(0, count - recovered))

    if articles:
        article_rows = []
        for item in articles:
            if not isinstance(item, dict):
                continue
            title = _esc(item.get("title") or "Bài viết mới")
            url = str(item.get("url") or "").strip()
            if url.startswith(("https://", "http://")):
                article_rows.append(f"<li><a href='{_esc(url)}'>{title}</a></li>")
            else:
                article_rows.append(f"<li>{title} <em>(không có URL)</em></li>")
        articles_html = "<ol>" + "".join(article_rows) + "</ol>"
    else:
        articles_html = "<p style='margin:0;color:#6b7280'>Không có bài nào được xác nhận publish trong lượt chạy này.</p>"

    source_table = ""
    if feed_errors:
        source_table = f"""
        <h3 style="margin:24px 0 8px">Nguồn RSS gặp lỗi ({len(feed_errors)})</h3>
        <table width="100%" cellpadding="8" cellspacing="0" style="border-collapse:collapse;font-size:13px">
          <thead><tr style="background:#f3f4f6"><th align="left">Nguồn</th><th align="left">Kết quả</th><th align="right">Bài trong feed</th><th align="left">Lý do</th></tr></thead>
          <tbody>{_table_rows(feed_errors[:15], source_rows=True)}</tbody>
        </table>
        {"<p style='font-size:12px;color:#6b7280'>Chỉ hiển thị tối đa 15 nguồn lỗi đầu tiên.</p>" if len(feed_errors)>15 else ""}
        """

    failure_table = ""
    if failures:
        failure_table = f"""
        <h3 style="margin:24px 0 8px">Bài/URL xử lý chưa thành công ({len(failures)})</h3>
        <table width="100%" cellpadding="8" cellspacing="0" style="border-collapse:collapse;font-size:13px">
          <thead><tr style="background:#f3f4f6"><th align="left">Bài</th><th align="left">Nguồn</th><th align="left">Công đoạn</th><th align="left">Lý do</th></tr></thead>
          <tbody>{_table_rows(failures[:12])}</tbody>
        </table>
        {"<p style='font-size:12px;color:#6b7280'>Chỉ hiển thị tối đa 12 lỗi đầu tiên.</p>" if len(failures)>12 else ""}
        """

    links = []
    if run_url:
        links.append(f"<a href='{_esc(run_url)}'>Mở log và chi tiết lượt chạy trên GitHub Actions</a>")
    site_url = str(report.get("site_url") or "").strip().rstrip("/")
    if site_url.startswith(("https://", "http://")):
        links.append(f"<a href='{_esc(site_url)}'>Mở website Đi Đây Đó</a>")

    workflow_line = "Thành công" if str(job_status).lower() == "success" else "Thất bại"
    return f"""
    <div style="font-family:Arial,Helvetica,sans-serif;line-height:1.6;color:#202124;max-width:760px;margin:0 auto">
      <div style="padding:22px 24px;background:#f5f6f4;border:1px solid #e1e5df;border-radius:12px 12px 0 0">
        <div style="font-size:12px;letter-spacing:1px;color:#657064">ĐI ĐÂY ĐÓ · BÁO CÁO VẬN HÀNH</div>
        <h1 style="font-size:23px;margin:6px 0">Kết quả crawler ngày {date}</h1>
        <div style="display:inline-block;padding:5px 10px;border-radius:5px;background:{color};color:#fff;font-size:12px;font-weight:bold">{_esc(label)}</div>
        <p style="margin:10px 0 0;font-size:13px;color:#525a52">Workflow GitHub Actions: <strong>{workflow_line}</strong> · Thời gian chạy crawler: <strong>{duration}</strong></p>
      </div>
      <div style="padding:20px 24px;border:1px solid #e1e5df;border-top:0">
        <h2 style="font-size:17px;margin:0 0 10px">1. Kết quả xuất bản</h2>
        <table width="100%" cellpadding="10" cellspacing="0" style="border-collapse:collapse;text-align:center">
          <tr>
            <td style="background:#eef6ef;border-radius:8px"><div style="font-size:28px;font-weight:bold;color:#18794e">{count}</div><div style="font-size:12px">Bài đã publish</div></td>
            <td width="8"></td>
            <td style="background:#f5f6f4;border-radius:8px"><div style="font-size:28px;font-weight:bold">{minimum}</div><div style="font-size:12px">Mục tiêu tối thiểu</div></td>
            <td width="8"></td>
            <td style="background:#f5f6f4;border-radius:8px"><div style="font-size:28px;font-weight:bold">{preferred}</div><div style="font-size:12px">Mục tiêu mong muốn</div></td>
            <td width="8"></td>
            <td style="background:#f5f6f4;border-radius:8px"><div style="font-size:28px;font-weight:bold">{maximum}</div><div style="font-size:12px">Giới hạn tối đa</div></td>
          </tr>
        </table>
        <p style="font-size:13px;color:#525a52">Trong đó: {new_count} bài mới · {recovered} bài khôi phục từ hàng đợi cũ. Bài lỗi/chưa xuất bản: <strong>{failed_articles}</strong>.</p>

        <h3 style="font-size:15px;margin:22px 0 8px">Bài đã xuất bản và đường dẫn</h3>
        {articles_html}

        <h2 style="font-size:17px;margin:26px 0 10px">2. Tình hình nguồn RSS</h2>
        <table width="100%" cellpadding="8" cellspacing="0" style="border-collapse:collapse;font-size:13px">
          <tr><td>Nguồn đang bật</td><td align="right"><strong>{enabled}</strong></td></tr>
          <tr><td>Feed đọc được</td><td align="right"><strong>{ok_feeds}</strong></td></tr>
          <tr><td>Feed có bài mới</td><td align="right"><strong>{feeds_with_items}</strong></td></tr>
          <tr><td>Feed bị lỗi</td><td align="right"><strong>{failed_feeds}</strong></td></tr>
          <tr><td>URL ứng viên thu thập được</td><td align="right"><strong>{candidates}</strong></td></tr>
        </table>
        {source_table}

        <h2 style="font-size:17px;margin:26px 0 10px">3. Quá trình xử lý bài</h2>
        <table width="100%" cellpadding="8" cellspacing="0" style="border-collapse:collapse;font-size:13px">
          <tr><td>URL mới đã thử</td><td align="right"><strong>{attempted}</strong></td></tr>
          <tr><td>Bài đã xử lý xong bước crawl/AI</td><td align="right"><strong>{processed}</strong></td></tr>
          <tr><td>URL trùng/đã biết được bỏ qua</td><td align="right"><strong>{duplicate_count}</strong></td></tr>
          <tr><td>Bài ngoài danh mục biên tập được bỏ qua</td><td align="right"><strong>{irrelevant_count}</strong></td></tr>
          <tr><td>Bài cũ được đưa vào hàng đợi thử lại</td><td align="right"><strong>{retry_count}</strong></td></tr>
          <tr><td>Bài lỗi/chưa publish</td><td align="right"><strong>{failed_articles}</strong></td></tr>
        </table>
        {failure_table}

        <div style="margin-top:24px;padding:14px 16px;background:#fff8e6;border-left:4px solid #d99b20">
          <strong>4. Việc cần làm tiếp theo</strong>
          <p style="margin:6px 0 0;font-size:13px">{_esc(_next_step(report, job_status))}</p>
        </div>
        <div style="margin-top:22px;font-size:13px">{"<p>" + " · ".join(links) + "</p>" if links else ""}
        <p style="color:#6b7280;font-size:11px;margin-top:18px">Đây là báo cáo số liệu crawler, không phải thống kê người truy cập website. Lượt xem, phiên truy cập và người dùng quay lại được theo dõi riêng trong Google Analytics 4.</p>
        </div>
      </div>
    </div>
    """


def _build_text(report: dict, job_status: str, run_url: str) -> str:
    articles = report.get("articles") if isinstance(report.get("articles"), list) else []
    feed_errors = report.get("feed_errors") if isinstance(report.get("feed_errors"), list) else []
    failures = report.get("failures") if isinstance(report.get("failures"), list) else []
    date = report.get("date") or "Không có ngày chạy"
    label, _ = _status(report, job_status)
    lines = [
        f"BÁO CÁO CRAWLER ĐI ĐÂY ĐÓ - {date}",
        f"KẾT LUẬN: {label}",
        f"Trạng thái GitHub Actions: {job_status}",
        f"Đã publish: {report.get('published_count', 0)} bài",
        f"Mục tiêu: {report.get('minimum', 3)} tối thiểu / {report.get('preferred', 5)} mong muốn / {report.get('maximum', 10)} tối đa",
        f"Nguồn RSS: {report.get('successful_feed_count', 0)} đọc được; {report.get('failed_feed_count', 0)} lỗi; {report.get('candidate_url_count', 0)} URL ứng viên",
        f"Xử lý: {report.get('attempted_url_count', 0)} URL đã thử; {report.get('processed_article_count', 0)} bài đã xử lý; {report.get('duplicate_skipped_count', 0)} URL trùng; {report.get('irrelevant_skipped_count', 0)} bài ngoài danh mục; {report.get('failed_count', 0)} bài lỗi",
        f"Thời gian crawler: {_duration(report.get('duration_seconds'))}",
        "",
        "BÀI ĐÃ PUBLISH:",
    ]
    if articles:
        lines.extend(f"- {item.get('title') or 'Bài mới'}: {item.get('url') or 'Không có URL'}" for item in articles if isinstance(item, dict))
    else:
        lines.append("- Không có bài nào được xác nhận publish.")
    if feed_errors:
        lines += ["", "NGUỒN RSS LỖI:"]
        lines.extend(f"- {item.get('name')}: {item.get('error')}" for item in feed_errors if isinstance(item, dict))
    if failures:
        lines += ["", "BÀI/URL LỖI:"]
        lines.extend(f"- {item.get('title')}: {item.get('reason')}" for item in failures if isinstance(item, dict))
    lines += ["", "VIỆC TIẾP THEO:", _next_step(report, job_status)]
    if run_url:
        lines += ["", f"Chi tiết workflow: {run_url}"]
    return "\n".join(lines)


def _send_with_gmail(report: dict, job_status: str, recipients: list[str], run_url: str) -> bool:
    username = os.getenv("GMAIL_USERNAME", "").strip()
    app_password = os.getenv("GMAIL_APP_PASSWORD", "").replace(" ", "").strip()
    if not (username and app_password):
        return False

    sender_header = os.getenv("REPORT_EMAIL_FROM", "").strip() or username
    date = str(report.get("date") or "chưa có ngày")
    count = int(report.get("published_count") or 0)
    label, _ = _status(report, job_status)
    subject = f"[Đi Đây Đó] {label} · {date} · {count} bài publish"
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender_header
    message["To"] = ", ".join(recipients)
    message.set_content(_build_text(report, job_status, run_url))
    message.add_alternative(_build_html(report, job_status, run_url), subtype="html")

    context = ssl.create_default_context()
    with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as smtp:
        smtp.ehlo()
        smtp.starttls(context=context)
        smtp.ehlo()
        smtp.login(username, app_password)
        smtp.send_message(message)

    print(f"Đã gửi email báo cáo chi tiết qua Gmail SMTP tới {len(recipients)} địa chỉ.")
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-status", default=os.getenv("JOB_STATUS", "unknown"))
    args = parser.parse_args()

    report = _load_report()
    report_missing = not bool(report)
    if report_missing:
        report = {
            "date": "Không tạo được báo cáo",
            "status": "report_missing",
            "published_count": 0,
            "minimum": 3,
            "preferred": 5,
            "maximum": 10,
            "articles": [],
            "feed_errors": [],
            "failures": [],
        }

    articles = report.get("articles") if isinstance(report.get("articles"), list) else []
    count = int(report.get("published_count") or len(articles))
    date = str(report.get("date") or "chưa có ngày")
    job_status = str(args.job_status or "unknown")
    run_url = _run_url()

    # The GitHub run summary mirrors the key figures from the email.
    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_path:
        summary = [
            f"## Báo cáo crawler Đi Đây Đó - {date}",
            f"- Kết luận: **{_status(report, job_status)[0]}**",
            f"- Đã publish: **{count} bài** (mục tiêu {report.get('minimum', 3)}/{report.get('preferred', 5)}/{report.get('maximum', 10)})",
            f"- RSS: {report.get('successful_feed_count', 0)} feed đọc được / {report.get('failed_feed_count', 0)} feed lỗi / {report.get('candidate_url_count', 0)} URL ứng viên",
            f"- Xử lý: {report.get('attempted_url_count', 0)} URL đã thử / {report.get('processed_article_count', 0)} bài đã xử lý / {report.get('irrelevant_skipped_count', 0)} bài ngoài danh mục / {report.get('failed_count', 0)} bài lỗi",
            f"- Thời gian: {_duration(report.get('duration_seconds'))}",
        ]
        for item in articles:
            if isinstance(item, dict):
                title = str(item.get("title") or "Bài viết mới")
                url = str(item.get("url") or "")
                summary.append(f"- [{title}]({url})" if url.startswith(("https://", "http://")) else f"- {title}")
        if run_url:
            summary.append(f"- [Mở workflow log]({run_url})")
        try:
            with open(summary_path, "a", encoding="utf-8") as handle:
                handle.write("\n".join(summary) + "\n")
        except OSError:
            pass

    recipient = os.getenv("REPORT_EMAIL_TO", "").strip()
    recipients = [x.strip() for x in recipient.replace(";", ",").split(",") if x.strip()]
    if not recipients:
        print("Email chưa được gửi: hãy cấu hình REPORT_EMAIL_TO trong GitHub Secrets.")
        print(f"Báo cáo vẫn có trong GitHub Actions Summary; job_status={job_status}, published={count}.")
        return 0

    if os.getenv("GMAIL_USERNAME", "").strip() and os.getenv("GMAIL_APP_PASSWORD", "").strip():
        try:
            _send_with_gmail(report, job_status, recipients, run_url)
            return 0
        except smtplib.SMTPException as exc:
            print(f"Gửi email qua Gmail SMTP thất bại: {type(exc).__name__}. Kiểm tra App Password và quyền tài khoản.")
            return 1
        except (OSError, TimeoutError) as exc:
            print(f"Gửi email qua Gmail SMTP thất bại do kết nối: {type(exc).__name__}.")
            return 1

    api_key = os.getenv("RESEND_API_KEY", "").strip()
    sender = os.getenv("REPORT_EMAIL_FROM", "").strip()
    if not (api_key and sender):
        print("Email chưa được gửi: cần GMAIL_USERNAME + GMAIL_APP_PASSWORD hoặc RESEND_API_KEY + REPORT_EMAIL_FROM.")
        print(f"Báo cáo vẫn có trong GitHub Actions Summary; job_status={job_status}, published={count}.")
        return 0

    payload = {
        "from": sender,
        "to": recipients,
        "subject": f"[Đi Đây Đó] {_status(report, job_status)[0]} · {date} · {count} bài publish",
        "html": _build_html(report, job_status, run_url),
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
    try:
        with urlopen(request, timeout=25) as response:
            response.read()
            print(f"Đã gửi email báo cáo chi tiết qua Resend. HTTP {response.status}.")
            return 0
    except HTTPError as exc:
        print(f"Gửi email thất bại. Resend HTTP {exc.code}; kiểm tra API key, sender domain và recipient.")
        return 1
    except (URLError, TimeoutError) as exc:
        print(f"Gửi email thất bại do kết nối: {type(exc).__name__}.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
