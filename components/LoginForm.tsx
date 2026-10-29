"use client";

import { useState } from "react";
import { ArrowRight, Compass, Eye, EyeOff, LockKeyhole } from "lucide-react";

const siteName = process.env.NEXT_PUBLIC_SITE_NAME || "Đi Đây Đó";

export function LoginForm() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError("");
    try {
      const response = await fetch("/api/admin/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email, password }) });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Không thể đăng nhập.");
      window.location.href = "/admin";
    } catch (e) { setError(e instanceof Error ? e.message : "Có lỗi xảy ra."); }
    finally { setBusy(false); }
  }

  return <main className="login-page"><div className="login-art"><div className="login-art-overlay"/><div className="login-art-content"><a href="/" className="brand login-brand"><span className="brand-mark"><Compass size={28}/></span><span className="brand-copy"><strong>{siteName}</strong><small>TẠP CHÍ DU LỊCH & ĐỜI SỐNG</small></span></a><div><span className="eyebrow">THE WORLD IS A STORY</span><h1>Mỗi hành trình<br/>bắt đầu từ một<br/><em>câu chuyện.</em></h1><p>Không gian biên tập dành cho những người kể chuyện về thế giới.</p></div><small className="login-caption">EDITORIAL WORKSPACE · EST. 2026</small></div></div><div className="login-form-side"><div className="login-form-wrap"><span className="login-icon"><LockKeyhole size={22}/></span><span className="eyebrow">DÀNH CHO BIÊN TẬP VIÊN</span><h2>Chào mừng trở lại.</h2><p>Đăng nhập để quản lý nội dung website.</p>{error && <div className="admin-alert is-error">{error}</div>}<form onSubmit={submit} className="login-form"><label>Email quản trị<input type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="admin@example.com" required/></label><label>Mật khẩu<span className="password-input"><input type={showPassword ? "text" : "password"} autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="Nhập mật khẩu" required/><button type="button" onClick={() => setShowPassword(!showPassword)} aria-label={showPassword ? "Ẩn mật khẩu" : "Hiện mật khẩu"}>{showPassword ? <EyeOff size={17}/> : <Eye size={17}/>}</button></span></label><button className="button-primary login-submit" type="submit" disabled={busy}>{busy ? "Đang đăng nhập..." : "Đăng nhập hệ thống"}<ArrowRight size={17}/></button></form><p className="login-back"><a href="/">← Trở về website</a></p></div></div></main>;
}
