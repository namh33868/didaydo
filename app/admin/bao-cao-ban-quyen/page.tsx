import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { CopyrightReportsPanel } from "@/components/CopyrightReportsPanel";
import { getAdminSession, hasPermission } from "@/lib/auth";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Yêu cầu gỡ nội dung", robots: { index: false, follow: false } };

export default async function CopyrightReportsPage() {
  const session = await getAdminSession();
  if (!session) redirect("/dang-nhap");
  if (!hasPermission(session.role, "posts:publish")) redirect("/admin");

  return (
    <div className="admin-shell">
      <aside className="admin-sidebar">
        <a href="/admin" className="admin-logo"><span className="brand-mark">ĐĐ</span><span><b>Đi Đây Đó</b><small>STUDIO / CMS</small></span></a>
        <div className="admin-side-label">QUẢN TRỊ</div>
        <a className="admin-side-link" href="/admin">Bài viết</a>
        <a className="admin-side-link active" href="/admin/bao-cao-ban-quyen">Yêu cầu gỡ nội dung</a>
        <a className="admin-side-link" href="/ban-quyen" target="_blank" rel="noreferrer">Trang tiếp nhận</a>
        <a className="admin-side-link" href="/">Xem website</a>
      </aside>
      <CopyrightReportsPanel />
    </div>
  );
}
