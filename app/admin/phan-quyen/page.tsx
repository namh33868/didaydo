import { redirect } from "next/navigation";
import type { Metadata } from "next";
import { getAdminSession } from "@/lib/auth";
import { AdminUsersPanel } from "@/components/AdminUsersPanel";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Tài khoản & phân quyền", robots: { index: false, follow: false } };

export default async function AdminPermissionsPage() {
  const session = await getAdminSession();
  if (!session) redirect("/dang-nhap");
  if (session.role !== "admin") redirect("/admin");
  return <AdminUsersPanel />;
}
