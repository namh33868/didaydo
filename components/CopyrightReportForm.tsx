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
        <label className="copyright-form-full">Bạn gửi thông báo với tư cách *
          <select value={form.relationship} onChange={(e) => update("relationship", e.target.value)}>
            <option value="owner">Chủ sở hữu quyền</option>
            <option value="authorized_agent">Người đại diện được ủy quyền</option>
            <option value="other">Tư cách khác (vui lòng giải thích bên dưới)</option>
          </select>
        </label>
        <label className="copyright-form-full">Tên tác phẩm / tài sản bị ảnh hưởng
          <input value={form.workTitle} onChange={(e) => update("workTitle", e.target.value)} maxLength={180} placeholder="Tên bài viết, bộ ảnh, tác phẩm..." />
        </label>
        <label className="copyright-form-full">URL bản gốc / tài liệu giúp xác minh quyền
          <input type="url" value={form.originalWorkUrl} onChange={(e) => update("originalWorkUrl", e.target.value)} maxLength={2000} placeholder="https://..." />
        </label>
        <label className="copyright-form-full">URL nội dung trên Đi Đây Đó bị phản ánh *
          <input type="url" value={form.reportedUrl} onChange={(e) => update("reportedUrl", e.target.value)} required maxLength={2000} placeholder="https://didaydo.vercel.app/bai-viet/..." />
        </label>
        <label className="copyright-form-full">Mô tả nội dung bị phản ánh và căn cứ gửi thông báo *
          <textarea value={form.details} onChange={(e) => update("details", e.target.value)} required minLength={30} maxLength={5000} rows={5} placeholder="Nêu rõ vị trí nội dung, căn cứ quyền hoặc ủy quyền và thông tin giúp chúng tôi xác minh..." />
        </label>
      </div>
      <label className="copyright-honeypot" aria-hidden="true">Để trống trường này
        <input tabIndex={-1} autoComplete="off" value={form.website} onChange={(e) => update("website", e.target.value)} />
      </label>
      <label className="copyright-declaration">
        <input type="checkbox" checked={form.declaration} onChange={(e) => update("declaration", e.target.checked)} required />
        <span>Tôi xác nhận thông tin gửi là chính xác và dựa trên thiện chí; tôi là chủ sở hữu quyền, người được ủy quyền hoặc có căn cứ hợp pháp để gửi thông báo này. Tôi đồng ý Đi Đây Đó sử dụng thông tin nhằm xác minh và xử lý yêu cầu.</span>
      </label>
      {(error || message) && <p className={error ? "copyright-form-error" : "copyright-form-success"} role="status">{error || message}</p>}
      <button className="button-primary" type="submit" disabled={busy || !form.declaration}><Send size={15}/>{busy ? "Đang gửi..." : "Gửi thông báo"}</button>
      <p className="copyright-form-note"><ShieldCheck size={14}/> Mỗi thông báo được xem xét thủ công. Việc gửi thông báo không tự động khiến nội dung bị gỡ bỏ.</p>
    </form>
  );
}
