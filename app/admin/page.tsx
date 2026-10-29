import { redirect } from "next/navigation";
import { AdminPanel } from "@/components/AdminPanel";
import { getAdminSession } from "@/lib/auth";
import type { Metadata } from "next";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Quản trị nội dung", robots: { index: false, follow: false } };
export default async function AdminPage() {
  const session = await getAdminSession();
  if (!session) redirect("/dang-nhap");
  return <AdminPanel />;
}
