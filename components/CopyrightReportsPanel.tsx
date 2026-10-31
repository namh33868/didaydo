"use client";

import { useCallback, useEffect, useState } from "react";
import { ExternalLink, RefreshCw, ShieldAlert } from "lucide-react";

type Report = {
  id: string;
  claimantName: string;
  claimantEmail: string;
  relationship: string;
  workTitle: string;
  originalWorkUrl: string;
  reportedUrl: string;
  details: string;
  status: "new" | "reviewing" | "resolved" | "rejected";
  reviewNote: string;
  createdAt: string;
};

const labels: Record<Report["status"], string> = {
  new: "Mới tiếp nhận",
  reviewing: "Đang xem xét",
  resolved: "Đã xử lý",
  rejected: "Không đủ căn cứ",
};

export function CopyrightReportsPanel() {
  const [reports, setReports] = useState<Report[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const load = useCallback(async () => {
    setBusy(true);
    setError("");
    try {
      const response = await fetch("/api/admin/copyright-reports", { cache: "no-store" });
      if (response.status === 401) {
        window.location.href = "/dang-nhap";
        return;
      }
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Không tải được báo cáo.");
      setReports(data.reports || []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Có lỗi khi tải báo cáo.");
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  function updateNote(id: string, note: string) {
    setReports((current) => current.map((item) => item.id === id ? { ...item, reviewNote: note } : item));
  }

  async function save(report: Report) {
    setError("");
    setMessage("");
    try {
      const response = await fetch("/api/admin/copyright-reports", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: report.id, status: report.status, reviewNote: report.reviewNote }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Không cập nhật được báo cáo.");
      setMessage("Đã lưu trạng thái và ghi chú xử lý.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Có lỗi khi cập nhật.");
    }
  }

  function setStatus(id: string, status: Report["status"]) {
    setReports((current) => current.map((item) => item.id === id ? { ...item, status } : item));
  }

  const openCount = reports.filter((item) => item.status === "new" || item.status === "reviewing").length;

  return (
    <main className="admin-main copyright-admin-main">
      <div className="admin-topbar">
        <div>
          <span className="eyebrow">WORKSPACE / TRUST & SAFETY</span>
          <h1>Yêu cầu gỡ nội dung</h1>
          <p className="admin-page-subtitle">Tiếp nhận, xác minh và ghi nhận kết quả xử lý khiếu nại.</p>
        </div>
        <button className="button-secondary" onClick={() => void load()} disabled={busy}>
          <RefreshCw size={15}/> {busy ? "Đang tải..." : "Tải lại"}
        </button>
      </div>
      <div className="admin-stats copyright-report-stats">
        <div><span>Tổng thông báo</span><strong>{reports.length}</strong><small>Tối đa 200 báo cáo gần nhất</small></div>
        <div><span>Chưa đóng</span><strong>{openCount}</strong><small>Cần kiểm tra tiếp</small></div>
        <div><span>Mới tiếp nhận</span><strong>{reports.filter((item) => item.status === "new").length}</strong><small>Chưa phân loại</small></div>
        <div><span>Đã xử lý / từ chối</span><strong>{reports.filter((item) => item.status === "resolved" || item.status === "rejected").length}</strong><small>Đã có kết luận</small></div>
      </div>
      {(error || message) && <div className={"admin-alert " + (error ? "is-error" : "is-success")}>{error || message}</div>}
      {reports.length === 0 && !busy && (
        <div className="admin-table-card copyright-empty">
          <ShieldAlert size={25}/>
          <b>Chưa có thông báo vi phạm</b>
          <span>Các thông báo mới gửi sẽ xuất hiện tại đây.</span>
        </div>
      )}
      <div className="copyright-admin-list">
        {reports.map((report) => (
          <article className="admin-table-card copyright-report-card" key={report.id}>
            <header className="copyright-report-head">
              <div>
                <span className="eyebrow">GỬI NGÀY {new Date(report.createdAt).toLocaleString("vi-VN")}</span>
                <h2>{report.workTitle || "Thông báo về tác phẩm"}</h2>
                <p>{report.claimantName} · <a href={"mailto:" + report.claimantEmail}>{report.claimantEmail}</a> · {report.relationship}</p>
              </div>
              <span className="status-pill status-draft">{labels[report.status]}</span>
            </header>
            <div className="copyright-report-links">
              <p><b>Nội dung bị báo cáo</b><a href={report.reportedUrl} target="_blank" rel="noopener noreferrer nofollow">{report.reportedUrl} <ExternalLink size={13}/></a></p>
              {report.originalWorkUrl && <p><b>Tác phẩm gốc / bằng chứng</b><a href={report.originalWorkUrl} target="_blank" rel="noopener noreferrer nofollow">{report.originalWorkUrl} <ExternalLink size={13}/></a></p>}
            </div>
            <p className="copyright-report-details">{report.details}</p>
            <label className="copyright-review-note">Ghi chú nội bộ
              <textarea rows={3} value={report.reviewNote} onChange={(event) => updateNote(report.id, event.target.value)} maxLength={2000} placeholder="Bằng chứng đã kiểm tra, trao đổi với các bên và quyết định xử lý..."/>
            </label>
            <footer className="copyright-report-actions">
              <select value={report.status} onChange={(event) => setStatus(report.id, event.target.value as Report["status"])}>
                <option value="new">Mới tiếp nhận</option>
                <option value="reviewing">Đang xem xét</option>
                <option value="resolved">Đã xử lý</option>
                <option value="rejected">Không đủ căn cứ</option>
              </select>
              <button className="button-primary" onClick={() => void save(report)}>Lưu xử lý</button>
              <span>Mã: {report.id}</span>
            </footer>
          </article>
        ))}
      </div>
    </main>
  );
}
