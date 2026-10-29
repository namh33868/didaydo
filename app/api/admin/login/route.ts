import { timingSafeEqual } from "node:crypto";
import { NextResponse } from "next/server";
import { createAdminSession, isAdminRole } from "@/lib/auth";
import { db } from "@/lib/db";
import { verifyPassword } from "@/lib/password";

export const runtime = "nodejs";

function safeEqual(a: string, b: string) {
  const left = Buffer.from(a);
  const right = Buffer.from(b);
  return left.length === right.length && timingSafeEqual(left, right);
}

export async function POST(request: Request) {
  const origin = request.headers.get("origin");
  if (origin) {
    try { if (new URL(origin).origin !== new URL(request.url).origin) return NextResponse.json({ error: "Origin không hợp lệ." }, { status: 403 }); }
    catch { return NextResponse.json({ error: "Origin không hợp lệ." }, { status: 403 }); }
  }
  const configuredEmail = (process.env.ADMIN_EMAIL || "").trim().toLowerCase();
  const configuredPassword = process.env.ADMIN_PASSWORD || "";
  if (!process.env.SESSION_SECRET || process.env.SESSION_SECRET.length < 32) {
    return NextResponse.json({ error: "Thiếu cấu hình SESSION_SECRET hợp lệ trong .env." }, { status: 503 });
  }
  let body: { email?: unknown; password?: unknown };
  try { body = await request.json(); } catch { return NextResponse.json({ error: "Dữ liệu đăng nhập không hợp lệ." }, { status: 400 }); }
  const email = typeof body.email === "string" ? body.email.trim().toLowerCase() : "";
  const password = typeof body.password === "string" ? body.password : "";
  if (!email || !password) return NextResponse.json({ error: "Vui lòng nhập email và mật khẩu." }, { status: 400 });

  // Root administrator remains available through .env, even before additional CMS users exist.
  if (configuredEmail && email === configuredEmail) {
    if (!configuredPassword || !safeEqual(password, configuredPassword)) {
      return NextResponse.json({ error: "Email hoặc mật khẩu chưa chính xác." }, { status: 401 });
    }
    try {
      await createAdminSession(email, "admin", null, "Quản trị viên gốc");
      return NextResponse.json({ success: true, role: "admin" });
    } catch (error) {
      console.error("Could not create root admin session", error);
      return NextResponse.json({ error: "Không thể tạo phiên đăng nhập. Kiểm tra SESSION_SECRET." }, { status: 500 });
    }
  }

  try {
    const users = await db<{ id: string; email: string; full_name: string; password_hash: string; role: string; active: boolean }[]>`
      SELECT id, email, full_name, password_hash, role, active FROM admin_users WHERE lower(email) = ${email} LIMIT 1
    `;
    const user = users[0];
    if (!user || !user.active || !isAdminRole(user.role) || !(await verifyPassword(password, user.password_hash))) {
      return NextResponse.json({ error: "Email hoặc mật khẩu chưa chính xác." }, { status: 401 });
    }
    await db`UPDATE admin_users SET last_login_at = NOW(), updated_at = NOW() WHERE id = ${user.id}`;
    await createAdminSession(user.email, user.role, user.id, user.full_name);
    return NextResponse.json({ success: true, role: user.role });
  } catch (error) {
    console.error("Database account login failed", error);
    return NextResponse.json({ error: "Không thể kiểm tra tài khoản nhân sự. Hãy kiểm tra database và chạy npm run db:setup." }, { status: 503 });
  }
}
