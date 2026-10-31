"""Send the daily crawler digest through Resend when repository secrets are configured."""
from __future__ import annotations

import argparse
import html
import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

REPORT_PATH = Path(__file__).resolve().parent / "logs" / "daily-report.json"


def _load_report() -> dict:
    try:
        value = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _build_html(report: dict, job_status: str) -> str:
    articles = report.get("articles") if isinstance(report.get("articles"), list) else []
    rows = []
    for item in articles:
        if not isinstance(item, dict):
            continue
        title = html.escape(str(item.get("title") or "Bài viết mới"))
        url = str(item.get("url") or "").strip()
        if url.startswith(("https://", "http://")):
            rows.append(f'<li><a href="{html.escape(url, quote=True)}">{title}</a></li>')
        else:
            rows.append(f"<li>{title}</li>")

    date = html.escape(str(report.get("date") or "Không có dữ liệu ngày chạy"))
    count = int(report.get("published_count") or len(rows))
    minimum = report.get("minimum", 3)
    preferred = report.get("preferred", 5)
    maximum = report.get("maximum", 10)
    failed = int(report.get("failed_count") or 0)
    quota = bool(report.get("ai_quota_stop"))
    status = html.escape(str(report.get("status") or job_status))
    if not rows:
        rows_html = "<p>Không có bài viết mới được xác nhận xuất bản trong lượt chạy này.</p>"
    else:
        rows_html = "<ol>" + "".join(rows) + "</ol>"

    return f"""
    <div style="font-family:Arial,sans-serif;line-height:1.6;color:#202124;max-width:680px">
      <h2>Báo cáo crawler Đi Đây Đó</h2>
      <p>Ngày chạy: <strong>{date}</strong></p>
      <table cellpadding="8" cellspacing="0" border="1" style="border-collapse:collapse;border-color:#ddd">
        <tr><td>Đã xuất bản</td><td><strong>{count} bài</strong></td></tr>
        <tr><td>Mục tiêu</td><td>{minimum} tối thiểu · {preferred} mong muốn · {maximum} tối đa</td></tr>
        <tr><td>Bài lỗi/chưa xuất bản</td><td>{failed}</td></tr>
        <tr><td>Trạng thái crawler</td><td>{status}</td></tr>
      </table>
      <h3>Bài đã xuất bản trong lượt này</h3>
      {rows_html}
      {"<p><strong>Lưu ý:</strong> AI đã chạm quota/giới hạn; lượt chạy dừng sớm để tránh gọi lặp.</p>" if quota else ""}
      <p style="color:#666;font-size:12px">Báo cáo tự động từ GitHub Actions. Số liệu traffic website được xem riêng trong Google Analytics 4.</p>
    </div>
    """


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-status", default=os.getenv("JOB_STATUS", "unknown"))
    args = parser.parse_args()

    report = _load_report()
    articles = report.get("articles") if isinstance(report.get("articles"), list) else []
    count = int(report.get("published_count") or len(articles))
    date = str(report.get("date") or "chưa có ngày")
    job_status = str(args.job_status or "unknown")

    # Also add a compact digest to the GitHub Actions run summary as a no-email fallback.
    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_path:
        summary = [
            "## Báo cáo crawler Đi Đây Đó",
            f"- Ngày: {date}",
            f"- Đã xuất bản: **{count} bài**",
            f"- Trạng thái workflow: **{job_status}**",
        ]
        for item in articles:
            if isinstance(item, dict):
                title = str(item.get("title") or "Bài viết mới")
                url = str(item.get("url") or "")
                summary.append(f"- [{title}]({url})" if url.startswith(("https://", "http://")) else f"- {title}")
        try:
            with open(summary_path, "a", encoding="utf-8") as handle:
                handle.write("\n".join(summary) + "\n")
        except OSError:
            pass

    api_key = os.getenv("RESEND_API_KEY", "").strip()
    recipient = os.getenv("REPORT_EMAIL_TO", "").strip()
    sender = os.getenv("REPORT_EMAIL_FROM", "").strip()
    if not (api_key and recipient and sender):
        print("Email chưa được gửi: cần cấu hình RESEND_API_KEY, REPORT_EMAIL_TO và REPORT_EMAIL_FROM trong GitHub Secrets.")
        print(f"Báo cáo vẫn được lưu trong GitHub Actions Summary/Artifact; job_status={job_status}, published={count}.")
        return 0

    recipients = [x.strip() for x in recipient.replace(";", ",").split(",") if x.strip()]
    if not recipients:
        print("Email chưa được gửi: REPORT_EMAIL_TO không có địa chỉ hợp lệ.")
        return 0

    subject = f"[Đi Đây Đó] Báo cáo crawler {date}: {count} bài"
    payload = {
        "from": sender,
        "to": recipients,
        "subject": subject,
        "html": _build_html(report, job_status),
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
            body = response.read().decode("utf-8", errors="replace")
            print(f"Đã gửi email báo cáo qua Resend. HTTP {response.status}; response_id_present={bool(body)}")
            return 0
    except HTTPError as exc:
        print(f"Gửi email thất bại. Resend HTTP {exc.code}; kiểm tra API key, sender domain và recipient.")
        return 1
    except (URLError, TimeoutError) as exc:
        print(f"Gửi email thất bại do kết nối: {type(exc).__name__}.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
