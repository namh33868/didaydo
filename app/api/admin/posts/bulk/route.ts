import { NextResponse } from "next/server";
import { db } from "@/lib/db";
import { getAdminSession, hasPermission } from "@/lib/auth";

export const runtime = "nodejs";

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
type BulkStatus = "draft" | "published" | "archived";

function sameOrigin(request: Request) {
  const origin = request.headers.get("origin");
  if (!origin) return true;
  try {
    return new URL(origin).origin === new URL(request.url).origin;
  } catch {
    return false;
  }
}

export async function PATCH(request: Request) {
  const session = await getAdminSession();
  if (!session) return NextResponse.json({ error: "Cần đăng nhập." }, { status: 401 });
  if (!hasPermission(session.role, "posts:edit:any") || !hasPermission(session.role, "posts:publish")) {
    return NextResponse.json({ error: "Chỉ quản trị viên và biên tập viên được thay đổi trạng thái hàng loạt." }, { status: 403 });
  }
  if (!sameOrigin(request)) return NextResponse.json({ error: "Origin không hợp lệ." }, { status: 403 });

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Dữ liệu gửi lên không phải JSON hợp lệ." }, { status: 400 });
  }

  if (!body || typeof body !== "object") {
    return NextResponse.json({ error: "Dữ liệu không hợp lệ." }, { status: 400 });
  }

  const payload = body as { ids?: unknown; status?: unknown };
  if (!Array.isArray(payload.ids) || payload.ids.length < 1 || payload.ids.length > 1000) {
    return NextResponse.json({ error: "Hãy chọn từ 1 đến 1.000 bài viết mỗi lần." }, { status: 400 });
  }
  if (!payload.ids.every((id): id is string => typeof id === "string" && UUID_PATTERN.test(id))) {
    return NextResponse.json({ error: "Danh sách có ID bài viết không hợp lệ." }, { status: 400 });
  }
  if (payload.status !== "draft" && payload.status !== "published" && payload.status !== "archived") {
    return NextResponse.json({ error: "Trạng thái đích không hợp lệ." }, { status: 400 });
  }

  const ids = [...new Set(payload.ids as string[])];
  const status: BulkStatus = payload.status;
  // PostgreSQL built-in OID for uuid; postgres.js expects a numeric type OID here.
  const UUID_ARRAY_OID = 2950;

  try {
    const updated = await db<{ id: string }[]>`
      UPDATE posts
      SET status = ${status},
          published_at = CASE
            WHEN ${status} = 'published' THEN COALESCE(published_at, NOW())
            ELSE NULL
          END,
          updated_by = ${session.userId},
          updated_at = NOW()
      WHERE id = ANY(${db.array(ids, UUID_ARRAY_OID)})
      RETURNING id
    `;

    return NextResponse.json({
      success: true,
      status,
      requestedCount: ids.length,
      updatedCount: updated.length,
      missingCount: ids.length - updated.length,
    });
  } catch (error) {
    console.error("admin bulk post status update failed", error);
    return NextResponse.json({ error: "Không thể cập nhật trạng thái hàng loạt. Hãy thử lại." }, { status: 500 });
  }
}
