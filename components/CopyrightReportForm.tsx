"use client";

import { useState } from "react";
import { Send, ShieldCheck } from "lucide-react";

const initialState = {
  claimantName: "",
  claimantEmail: "",
  relationship: "owner",
  workTitle: "",
  originalWorkUrl: "",
  reportedUrl: "",
  details: "",
  declaration: false,
  website: "",
};

export function CopyrightReportForm() {
  const [form, setForm] = useState(initialState);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  function update<K extends keyof typeof initialState>(key: K, value: (typeof initialState)[K]) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const response = await fetch("/api/copyright/report", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(form),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Chưa gửi được báo cáo.");
      setForm(initialState);
      setMessage("Đã tiếp nhận thông tin. Ban biên tập sẽ kiểm tra và liên hệ qua email bạn cung cấp khi cần làm rõ.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Có lỗi xảy ra. Vui lòng thử lại.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="copyright-report-form" onSubmit={submit}>
      <div className="copyright-form-grid">
        <label>Họ và tên / tổ chức *
          <input value={form.claimantName} onChange={(e) => update("claimantName", e.target.value)} required minLength={2} maxLength={120} autoComplete="name" />
        </label>
        <label>Email liên hệ *
          <input type="email" value={form.claimantEmail} onChange={(e) => update("claimantEmail", e.target.value)} required maxLength={254} autoComplete="email" />
        </label>
        <label className="copyright-form-full">Bạn gửi báo cáo với tư cách *
          <select value={form.relationship} onChange={(e) => update("relationship", e.target.value)}>
            <option value="owner">Chủ sở hữu quyền</option>
            <option value="authorized_agent">Người đại diện được ủy quyền</option>
            <option value="other">Tư cách khác (vui lòng giải thích bên dưới)</option>
          </select>
        </label>
        <label className="copyright-form-full">Tên tác phẩm gốc
          <input value={form.workTitle} onChange={(e) => update("workTitle", e.target.value)} maxLength={180} placeholder="Tên bài viết, bộ ảnh, tác phẩm..." />
        </label>
        <label className="copyright-form-full">URL tác phẩm gốc / nơi chứng minh quyền sở hữu
          <input type="url" value={form.originalWorkUrl} onChange={(e) => update("originalWorkUrl", e.target.value)} maxLength={2000} placeholder="https://..." />
        </label>
        <label className="copyright-form-full">URL nội dung trên Đi Đây Đó bị cho là vi phạm *
          <input type="url" value={form.reportedUrl} onChange={(e) => update("reportedUrl", e.target.value)} required maxLength={2000} placeholder="https://didaydo.vercel.app/bai-viet/..." />
        </label>
        <label className="copyright-form-full">Mô tả quyền của bạn và phần nội dung bị ảnh hưởng *
          <textarea value={form.details} onChange={(e) => update("details", e.target.value)} required minLength={30} maxLength={5000} rows={5} placeholder="Nêu rõ nội dung cụ thể, vị trí xuất hiện, căn cứ bạn sở hữu/được ủy quyền và tài liên hệ..." />
        </label>
      </div>
      <label className="copyright-honeypot" aria-hidden="true">Để trống trường này
        <input tabIndex={-1} autoComplete="off" value={form.website} onChange={(e) => update("website", e.target.value)} />
      </label>
      <label className="copyright-declaration">
        <input type="checkbox" checked={form.declaration} onChange={(e) => update("declaration", e.target.checked)} required />
        <span>Tôi xác nhận thông tin gửi là chính xác, tôi là chủ sở hữu quyền hoặc người được ủy quyền hợp pháp, và đồng ý Đi Đây Đó sử dụng thông tin này nhằm xác minh, xử lý báo cáo.</span>
      </label>
      {(error || message) && <p className={error ? "copyright-form-error" : "copyright-form-success"} role="status">{error || message}</p>}
      <button className="button-primary" type="submit" disabled={busy || !form.declaration}><Send size={15}/>{busy ? "Đang gửi..." : "Gửi báo cáo bản quyền"}</button>
      <p className="copyright-form-note"><ShieldCheck size={14}/> Báo cáo được xem xét thủ công. Việc gửi báo cáo không tự động khiến nội dung bị gỡ bỏ.</p>
    </form>
  );
}
