import { NextResponse } from "next/server";
import { getAdminSession, isAdminRole } from "@/lib/auth";
import { db } from "@/lib/db";
import { hashPassword } from "@/lib/password";

export const runtime = "nodejs";

type UserRecord = {
  id: string;
  email: string;
  full_name: string;
  role: string;
  active: boolean;
  last_login_at: Date | null;
  created_at: Date;
  updated_at: Date;
};

function sameOrigin(request: Request) {
  const origin = request.headers.get("origin");
  if (!origin) return true;
  try { return new URL(origin).origin === new URL(request.url).origin; } catch { return false; }
}

function publicUser(user: UserRecord) {
  return {
    id: user.id,
    email: user.email,
    fullName: user.full_name,
    role: user.role,
    active: user.active,
    lastLoginAt: user.last_login_at?.toISOString() || null,
    createdAt: user.created_at.toISOString(),
    updatedAt: user.updated_at.toISOString(),
  };
}

async function requireUserManager() {
  const session = await getAdminSession();
  if (!session) return { session: null, response: NextResponse.json({ error: "Cần đăng nhập." }, { status: 401 }) };
  if (session.role !== "admin") return { session: null, response: NextResponse.json({ error: "Chỉ quản trị viên mới được quản lý tài khoản và phân quyền." }, { status: 403 }) };
  return { session, response: null };
}

export async function GET() {
  const auth = await requireUserManager();
  if (auth.response) return auth.response;
  try {
    const users = await db<UserRecord[]>`
      SELECT id, email, full_name, role, active, last_login_at, created_at, updated_at
      FROM admin_users ORDER BY created_at DESC
    `;
    return NextResponse.json({ users: users.map(publicUser) });
  } catch (error) {
    console.error("admin users GET failed", error);
    return NextResponse.json({ error: "Không tải được danh sách tài khoản. Hãy chạy npm run db:setup." }, { status: 500 });
  }
}

export async function POST(request: Request) {
  const auth = await requireUserManager();
  if (auth.response) return auth.response;
  if (!sameOrigin(request)) return NextResponse.json({ error: "Origin không hợp lệ." }, { status: 403 });
  let body: Record<string, unknown>;
  try { body = await request.json(); } catch { return NextResponse.json({ error: "Dữ liệu không hợp lệ." }, { status: 400 }); }

  const email = typeof body.email === "string" ? body.email.trim().toLowerCase() : "";
  const fullName = typeof body.fullName === "string" ? body.fullName.trim() : "";
  const password = typeof body.password === "string" ? body.password : "";
  const role = body.role;
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) return NextResponse.json({ error: "Email không hợp lệ." }, { status: 400 });
  if (!fullName || fullName.length > 100) return NextResponse.json({ error: "Tên hiển thị cần có từ 1 đến 100 ký tự." }, { status: 400 });
  if (password.length < 10 || password.length > 200) return NextResponse.json({ error: "Mật khẩu ban đầu cần dài từ 10 đến 200 ký tự." }, { status: 400 });
  if (!isAdminRole(role)) return NextResponse.json({ error: "Vai trò không hợp lệ." }, { status: 400 });
  const rootEmail = (process.env.ADMIN_EMAIL || "").trim().toLowerCase();
  if (email === rootEmail) return NextResponse.json({ error: "Email này đang là tài khoản quản trị gốc trong file .env." }, { status: 409 });

  try {
    const passwordHash = await hashPassword(password);
    const rows = await db<UserRecord[]>`
      INSERT INTO admin_users (email, full_name, password_hash, role, active)
      VALUES (${email}, ${fullName}, ${passwordHash}, ${role}, TRUE)
      RETURNING id, email, full_name, role, active, last_login_at, created_at, updated_at
    `;
    return NextResponse.json({ user: publicUser(rows[0]) }, { status: 201 });
  } catch (error) {
    const code = typeof error === "object" && error !== null && "code" in error ? String((error as { code: unknown }).code) : "";
    if (code === "23505") return NextResponse.json({ error: "Email này đã được dùng cho một tài khoản khác." }, { status: 409 });
    console.error("admin users POST failed", error);
    return NextResponse.json({ error: "Không tạo được tài khoản. Kiểm tra kết nối database." }, { status: 500 });
  }
}

export async function PATCH(request: Request) {
  const auth = await requireUserManager();
  if (auth.response) return auth.response;
  if (!sameOrigin(request)) return NextResponse.json({ error: "Origin không hợp lệ." }, { status: 403 });
  let body: Record<string, unknown>;
  try { body = await request.json(); } catch { return NextResponse.json({ error: "Dữ liệu không hợp lệ." }, { status: 400 }); }

  const id = typeof body.id === "string" ? body.id : "";
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(id)) {
    return NextResponse.json({ error: "ID tài khoản không hợp lệ." }, { status: 400 });
  }
  if (body.role !== undefined && !isAdminRole(body.role)) return NextResponse.json({ error: "Vai trò không hợp lệ." }, { status: 400 });
  if (body.active !== undefined && typeof body.active !== "boolean") return NextResponse.json({ error: "Trạng thái tài khoản không hợp lệ." }, { status: 400 });
  if (body.fullName !== undefined && (typeof body.fullName !== "string" || !body.fullName.trim() || body.fullName.trim().length > 100)) {
    return NextResponse.json({ error: "Tên hiển thị cần có từ 1 đến 100 ký tự." }, { status: 400 });
  }
  const newPassword = body.newPassword;
  if (newPassword !== undefined && (typeof newPassword !== "string" || newPassword.length < 10 || newPassword.length > 200)) {
    return NextResponse.json({ error: "Mật khẩu mới cần dài từ 10 đến 200 ký tự." }, { status: 400 });
  }

  try {
    const target = (await db<UserRecord[]>`
      SELECT id, email, full_name, role, active, last_login_at, created_at, updated_at FROM admin_users WHERE id = ${id} LIMIT 1
    `)[0];
    if (!target) return NextResponse.json({ error: "Không tìm thấy tài khoản." }, { status: 404 });

    if (auth.session?.userId === target.id && ((body.role !== undefined && body.role !== target.role) || body.active === false)) {
      return NextResponse.json({ error: "Để tránh tự khóa quyền truy cập, không thể tự đổi vai trò hoặc vô hiệu hóa tài khoản đang đăng nhập." }, { status: 400 });
    }

    const nextRole = body.role === undefined ? target.role : body.role as string;
    const nextActive = body.active === undefined ? target.active : body.active as boolean;
    if (target.role === "admin" && target.active && (nextRole !== "admin" || !nextActive)) {
      const otherActiveAdmins = await db<{ count: number }[]>`
        SELECT COUNT(*)::int AS count FROM admin_users WHERE role = 'admin' AND active = TRUE AND id <> ${target.id}
      `;
      if ((otherActiveAdmins[0]?.count || 0) < 1) return NextResponse.json({ error: "Không thể gỡ quyền quản trị cuối cùng. Hãy giữ ít nhất một admin đang hoạt động." }, { status: 409 });
    }

    const fullName = body.fullName === undefined ? target.full_name : (body.fullName as string).trim();
    const passwordHash = typeof newPassword === "string" ? await hashPassword(newPassword) : null;
    const rows = await db<UserRecord[]>`
      UPDATE admin_users SET full_name = ${fullName}, role = ${nextRole}, active = ${nextActive},
        password_hash = COALESCE(${passwordHash}, password_hash), updated_at = NOW()
      WHERE id = ${id}
      RETURNING id, email, full_name, role, active, last_login_at, created_at, updated_at
    `;
    return NextResponse.json({ user: publicUser(rows[0]) });
  } catch (error) {
    console.error("admin users PATCH failed", error);
    return NextResponse.json({ error: "Không cập nhật được tài khoản." }, { status: 500 });
  }
}
