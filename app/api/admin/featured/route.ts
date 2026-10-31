import { NextResponse } from "next/server";
import { z } from "zod";
import { getAdminSession, hasPermission } from "@/lib/auth";
import { db } from "@/lib/db";
import { ensureFeaturedSchedule } from "@/lib/featured";

export const runtime = "nodejs";

const featuredSchema = z.object({ id: z.string().uuid(), featured: z.boolean() });

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
  if (!hasPermission(session.role, "posts:publish")) {
    return NextResponse.json({ error: "Chỉ quản trị viên hoặc biên tập viên được quản lý tin nổi bật." }, { status: 403 });
  }
  if (!sameOrigin(request)) return NextResponse.json({ error: "Origin không hợp lệ." }, { status: 403 });

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Dữ liệu gửi lên không hợp lệ." }, { status: 400 });
  }
  const parsed = featuredSchema.safeParse(body);
  if (!parsed.success) return NextResponse.json({ error: "Thiếu ID bài viết hoặc trạng thái nổi bật không hợp lệ." }, { status: 400 });

  const postId = parsed.data.id;
  const shouldFeature = parsed.data.featured;
  try {
    await ensureFeaturedSchedule();
    const currentRows = await db<{ id: string; status: string; featured: boolean; featured_until: Date | null; published_at: Date | null }[]>`
      SELECT id, status, featured, published_at FROM posts WHERE id = ${postId} LIMIT 1
    `;
    const current = currentRows[0];
    if (!current) return NextResponse.json({ error: "Không tìm thấy bài viết." }, { status: 404 });

    if (shouldFeature && (current.status !== "published" || !current.published_at || current.published_at > new Date())) {
      return NextResponse.json({ error: "Chỉ có thể chọn bài đã xuất bản làm tin nổi bật." }, { status: 400 });
    }

    if (shouldFeature && !current.featured) {
      const countRows = await db<{ total: number }[]>`
        SELECT COUNT(*)::int AS total FROM posts
        WHERE featured = TRUE AND featured_until > NOW() AND status = 'published' AND published_at <= NOW()
      `;
      if (Number(countRows[0]?.total || 0) >= 8) {
        return NextResponse.json({ error: "Đã chọn đủ 8 tin nổi bật. Hãy bỏ chọn một bài trước khi thêm bài khác." }, { status: 409 });
      }
    }

    const updated = await db<{ id: string; featured: boolean }[]>`
      UPDATE posts
      SET featured = ${shouldFeature},
        featured_until = CASE
          WHEN ${shouldFeature} THEN CASE
            WHEN featured = TRUE AND featured_until > NOW() THEN featured_until
            ELSE NOW() + INTERVAL '7 days'
          END
          ELSE NULL
        END,
        updated_by = ${session.userId}, updated_at = NOW()
      WHERE id = ${postId}
      RETURNING id, featured, featured_until
    `;
    return NextResponse.json({ success: true, id: updated[0]?.id, featured: updated[0]?.featured, featuredUntil: updated[0]?.featured_until?.toISOString() || null });
  } catch (error) {
    console.error("admin featured post update failed", error);
    return NextResponse.json({ error: "Không cập nhật được danh sách tin nổi bật." }, { status: 500 });
  }
}
