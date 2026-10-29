"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import { ArrowLeft, Check, KeyRound, LoaderCircle, LockKeyhole, LogOut, RefreshCw, Save, ShieldCheck, UserPlus, Users, X } from "lucide-react";

type AdminRole = "admin" | "editor" | "author" | "viewer";
type AdminUser = {
  id: string;
  email: string;
  fullName: string;
  role: AdminRole;
  active: boolean;
  lastLoginAt: string | null;
  createdAt: string;
  updatedAt: string;
};
type SessionUser = { email: string; fullName: string; role: AdminRole; userId: string | null };
type NewUser = { fullName: string; email: string; password: string; role: AdminRole };
type UserEdit = { role: AdminRole; active: boolean; newPassword: string };

const siteName = process.env.NEXT_PUBLIC_SITE_NAME || "Đi Đây Đó";
const roleNames: Record<AdminRole, string> = {
  admin: "Quản trị viên",
  editor: "Biên tập viên",
  author: "Tác giả",
  viewer: "Chỉ xem",
};
const roleDescriptions: Record<AdminRole, string> = {
  admin: "Toàn quyền CMS, quản lý tài khoản và phân quyền nhân sự.",
  editor: "Quản lý, chỉnh sửa, xuất bản và xóa mọi bài viết; xem lịch sử Crawl + AI.",
  author: "Tạo bài và sửa bản nháp do chính mình tạo. Không được xuất bản.",
  viewer: "Chỉ xem danh sách nội dung, không thể thay đổi dữ liệu.",
};
const roleOrder: AdminRole[] = ["admin", "editor", "author", "viewer"];
const emptyNewUser: NewUser = { fullName: "", email: "", password: "", role: "author" };

export function AdminUsersPanel() {
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [edits, setEdits] = useState<Record<string, UserEdit>>({});
  const [session, setSession] = useState<SessionUser | null>(null);
  const [newUser, setNewUser] = useState<NewUser>(emptyNewUser);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [usersResponse, sessionResponse] = await Promise.all([
        fetch("/api/admin/users", { cache: "no-store" }),
        fetch("/api/admin/session", { cache: "no-store" }),
      ]);
      if (usersResponse.status === 401 || sessionResponse.status === 401) {
        window.location.href = "/dang-nhap";
        return;
      }
      const usersData = await usersResponse.json();
      const sessionData = await sessionResponse.json();
      if (!usersResponse.ok) throw new Error(usersData.error || "Không tải được danh sách tài khoản.");
      if (!sessionResponse.ok) throw new Error(sessionData.error || "Không tải được phiên đăng nhập.");
      setUsers(usersData.users as AdminUser[]);
      setSession(sessionData as SessionUser);
      setEdits(Object.fromEntries((usersData.users as AdminUser[]).map((user) => [user.id, { role: user.role, active: user.active, newPassword: "" }])));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Có lỗi xảy ra khi tải tài khoản.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  async function logout() {
    await fetch("/api/admin/logout", { method: "POST" });
    window.location.href = "/dang-nhap";
  }

  async function createUser(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true); setError(""); setMessage("");
    try {
      const response = await fetch("/api/admin/users", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(newUser),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Không tạo được tài khoản.");
      setMessage(`Đã tạo tài khoản ${data.user.email}.`);
      setNewUser(emptyNewUser);
      await load();
    } catch (e) { setError(e instanceof Error ? e.message : "Không tạo được tài khoản."); }
    finally { setSaving(false); }
  }

  function updateEdit(id: string, patch: Partial<UserEdit>) {
    setEdits((current) => ({ ...current, [id]: { ...current[id], ...patch } }));
  }

  async function saveUser(user: AdminUser, resetPassword = false) {
    const edit = edits[user.id];
    if (!edit) return;
    if (resetPassword && edit.newPassword.length < 10) {
      setError("Mật khẩu mới cần có ít nhất 10 ký tự.");
      return;
    }
    setSaving(true); setError(""); setMessage("");
    try {
      const body: Record<string, unknown> = { id: user.id, role: edit.role, active: edit.active };
      if (resetPassword) body.newPassword = edit.newPassword;
      const response = await fetch("/api/admin/users", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Không cập nhật được tài khoản.");
      setMessage(resetPassword ? `Đã cập nhật quyền và đặt lại mật khẩu cho ${user.email}.` : `Đã lưu phân quyền cho ${user.email}.`);
      await load();
    } catch (e) { setError(e instanceof Error ? e.message : "Không cập nhật được tài khoản."); }
    finally { setSaving(false); }
  }

  const activeCount = users.filter((user) => user.active).length;
  const adminCount = users.filter((user) => user.active && user.role === "admin").length;

  return <div className="admin-shell">
    <aside className="admin-sidebar">
      <a href="/" className="admin-logo"><span className="brand-mark">ĐĐ</span><span><b>{siteName}</b><small>STUDIO / CMS</small></span></a>
      <div className="admin-side-label">NỘI DUNG</div>
      <a className="admin-side-link" href="/admin"><Users size={17}/> Bài viết</a>
      <a className="admin-side-link active" href="/admin/phan-quyen"><ShieldCheck size={17}/> Tài khoản & phân quyền</a>
      <a className="admin-side-link" href="/" target="_blank" rel="noreferrer"><ArrowLeft size={17}/> Xem website</a>
      <div className="admin-sidebar-bottom"><div className="admin-user-mark">{(session?.fullName || "Q").slice(0, 1).toUpperCase()}</div><div className="admin-user-text"><b>{session?.fullName || "Quản trị viên"}</b><small>{roleNames[session?.role || "admin"]}</small></div><button onClick={logout} title="Đăng xuất" aria-label="Đăng xuất"><LogOut size={17}/></button></div>
    </aside>

    <main className="admin-main admin-permissions-main">
      <div className="admin-topbar">
        <div><span className="eyebrow">WORKSPACE / ACCESS CONTROL</span><h1>Tài khoản & phân quyền</h1><p className="admin-page-subtitle">Quản lý người được vào CMS và giới hạn thao tác của từng vai trò.</p></div>
        <div className="admin-top-actions"><a href="/admin" className="button-secondary"><ArrowLeft size={15}/> Quay lại bài viết</a></div>
      </div>

      {(message || error) && <div className={`admin-alert ${error ? "is-error" : "is-success"}`}>{error ? <X size={16}/> : <Check size={16}/>} {error || message}<button onClick={() => { setError(""); setMessage(""); }} aria-label="Đóng thông báo"><X size={15}/></button></div>}

      <div className="admin-stats permissions-stats">
        <div><span>Tài khoản</span><strong>{users.length}</strong><small>Tổng tài khoản nội bộ</small></div>
        <div><span>Đang hoạt động</span><strong>{activeCount}</strong><small>Có thể đăng nhập</small></div>
        <div><span>Quản trị viên</span><strong>{adminCount + 1}</strong><small>Có tính tài khoản gốc trong .env</small></div>
        <div><span>Bảo mật</span><strong className="admin-live"><i/> RBAC</strong><small>Quyền được kiểm tra ở API</small></div>
      </div>

      <section className="admin-table-card permission-roles-card">
        <div className="admin-table-toolbar"><div><h2>Các vai trò có sẵn</h2><p>Vai trò quyết định những thao tác người dùng được phép thực hiện.</p></div><ShieldCheck size={23}/></div>
        <div className="permission-role-grid">
          {roleOrder.map((role) => <article className={`permission-role-card role-${role}`} key={role}><span className="permission-role-chip">{roleNames[role]}</span><p>{roleDescriptions[role]}</p></article>)}
        </div>
      </section>

      <section className="admin-table-card permission-create-card">
        <div className="admin-table-toolbar"><div><h2>Tạo tài khoản nhân sự</h2><p>Tạo tài khoản đăng nhập riêng, không cần chia sẻ tài khoản quản trị gốc.</p></div><UserPlus size={22}/></div>
        <form className="permission-create-form" onSubmit={createUser}>
          <label><span>Họ tên hiển thị</span><input value={newUser.fullName} onChange={(event) => setNewUser((current) => ({ ...current, fullName: event.target.value }))} maxLength={100} placeholder="Ví dụ: Nguyễn Minh Anh" required/></label>
          <label><span>Email đăng nhập</span><input type="email" autoComplete="off" value={newUser.email} onChange={(event) => setNewUser((current) => ({ ...current, email: event.target.value }))} placeholder="editor@example.com" required/></label>
          <label><span>Vai trò ban đầu</span><select value={newUser.role} onChange={(event) => setNewUser((current) => ({ ...current, role: event.target.value as AdminRole }))}>{roleOrder.map((role) => <option key={role} value={role}>{roleNames[role]}</option>)}</select></label>
          <label><span>Mật khẩu ban đầu</span><input type="password" autoComplete="new-password" value={newUser.password} onChange={(event) => setNewUser((current) => ({ ...current, password: event.target.value }))} minLength={10} maxLength={200} placeholder="Ít nhất 10 ký tự" required/></label>
          <div className="permission-create-submit"><button className="button-primary" type="submit" disabled={saving}>{saving ? <LoaderCircle size={15} className="permission-spinner"/> : <UserPlus size={15}/>} Tạo tài khoản</button></div>
        </form>
      </section>

      <section className="admin-table-card permission-users-card">
        <div className="admin-table-toolbar"><div><h2>Danh sách tài khoản</h2><p>Đổi vai trò, tạm khóa tài khoản hoặc đặt lại mật khẩu.</p></div><button className="icon-button" onClick={() => void load()} disabled={loading} aria-label="Tải lại tài khoản"><RefreshCw size={16}/></button></div>
        <div className="admin-table-scroll"><table className="admin-table permission-users-table"><thead><tr><th>Tài khoản</th><th>Vai trò</th><th>Trạng thái</th><th>Đăng nhập gần nhất</th><th>Thao tác</th></tr></thead><tbody>
          {users.map((user) => {
            const edit = edits[user.id] || { role: user.role, active: user.active, newPassword: "" };
            const isSelf = session?.userId === user.id;
            return <tr key={user.id}>
              <td><div className="permission-person"><span className="permission-avatar">{(user.fullName || user.email).slice(0, 1).toUpperCase()}</span><span><b>{user.fullName}</b><small>{user.email}{isSelf ? " · Tài khoản của mày" : ""}</small></span></div></td>
              <td><select className="permission-role-select" value={edit.role} disabled={isSelf || saving} onChange={(event) => updateEdit(user.id, { role: event.target.value as AdminRole })}>{roleOrder.map((role) => <option key={role} value={role}>{roleNames[role]}</option>)}</select></td>
              <td><label className={`permission-active-toggle ${edit.active ? "is-active" : "is-inactive"}`}><input type="checkbox" checked={edit.active} disabled={isSelf || saving} onChange={(event) => updateEdit(user.id, { active: event.target.checked })}/><span>{edit.active ? "Hoạt động" : "Đã khóa"}</span></label></td>
              <td>{user.lastLoginAt ? new Date(user.lastLoginAt).toLocaleString("vi-VN") : "Chưa đăng nhập"}</td>
              <td><div className="permission-row-actions"><button className="button-secondary permission-save-button" onClick={() => void saveUser(user)} disabled={saving || (edit.role === user.role && edit.active === user.active)}><Save size={14}/> Lưu quyền</button><div className="permission-reset-row"><input type="password" autoComplete="new-password" value={edit.newPassword} onChange={(event) => updateEdit(user.id, { newPassword: event.target.value })} minLength={10} maxLength={200} placeholder="Mật khẩu mới" aria-label={`Mật khẩu mới cho ${user.email}`} disabled={saving}/><button className="icon-button" title="Đặt lại mật khẩu" aria-label={`Đặt lại mật khẩu cho ${user.email}`} onClick={() => void saveUser(user, true)} disabled={saving || edit.newPassword.length < 10}><KeyRound size={15}/></button></div></div></td>
            </tr>;
          })}
          {!users.length && <tr><td colSpan={5} className="admin-empty">{loading ? "Đang tải tài khoản..." : "Chưa có tài khoản nhân sự nào. Tạo tài khoản đầu tiên ở phía trên."}</td></tr>}
        </tbody></table></div>
        <div className="admin-table-foot">Mật khẩu được lưu dưới dạng hash, không thể xem lại. Tạm khóa tài khoản sẽ chặn đăng nhập và vô hiệu hóa phiên đang dùng.</div>
      </section>
      <div className="admin-api-note permission-security-note"><div className="api-note-icon"><LockKeyhole size={19}/></div><div><b>Quyền được kiểm tra tại server</b><p>Ẩn nút trên giao diện chỉ giúp dễ dùng hơn. Các API cũng kiểm tra vai trò; tác giả chỉ được sửa bản nháp của chính mình, còn tài khoản chỉ xem không thể sửa dữ liệu bằng cách gọi API trực tiếp.</p></div></div>
    </main>
  </div>;
}
