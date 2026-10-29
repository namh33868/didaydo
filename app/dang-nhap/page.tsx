import { redirect } from "next/navigation";
import { LoginForm } from "@/components/LoginForm";
import { getAdminSession } from "@/lib/auth";
import type { Metadata } from "next";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Đăng nhập quản trị", robots: { index: false, follow: false } };
export default async function LoginPage() {
  const session = await getAdminSession();
  if (session) redirect("/admin");
  return <LoginForm />;
}
