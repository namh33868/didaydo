import { NextResponse } from "next/server";
import { z } from "zod";
import { getAdminSession, hasPermission } from "@/lib/auth";
import { db } from "@/lib/db";
import { ensureCopyrightTables } from "@/lib/copyright";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const updateSchema = z.object({
  id: z.string().uuid(),
  status: z.enum(["new", "reviewing", "resolved", "rejected"]),
  reviewNote: z.string().trim().max(2000).optional().default(""),
});

function sameOrigin(request: Request) {
  const origin = request.headers.get("origin");
  if (!origin) return true;
  try { return new URL(origin).origin === new URL(request.url).origin; } catch { return false; }
}

async function authorizeReviewer() {
  const session = await getAdminSession();
  if (!session) return { response: NextResponse.json({ error: "Cần đăng nhập." }, { status: 401 }) };
  if (!hasPermission(session.role, "posts:publish")) {
    return { response: NextResponse.json({ error: "Chỉ quản trị viên và biên tập viên được xem các thông báo vi phạm." }, { status: 403 }) };
  }
  return { response: null };
}

export async function GET() {
  const auth = await authorizeReviewer();
  if (auth.response) return auth.response;
  try {
    await ensureCopyrightTables();
    const reports = await db<{
      id: string; claimant_name: string; claimant_email: string; relationship: string;
      work_title: string; original_work_url: string; reported_url: string; details: string;
      status: string; review_note: string; created_at: Date; updated_at: Date;
    }[]>`
      SELECT id, claimant_name, claimant_email, relationship, work_title,
        original_work_url, reported_url, details, status, review_note, created_at, updated_at
      FROM copyright_reports ORDER BY created_at DESC LIMIT 200
    `;
    return NextResponse.json({ reports: reports.map((report) => ({
      id: report.id, claimantName: report.claimant_name, claimantEmail: report.claimant_email,
      relationship: report.relationship, workTitle: report.work_title,
      originalWorkUrl: report.original_work_url, reportedUrl: report.reported_url,
      details: report.details, status: report.status, reviewNote: report.review_note,
      createdAt: report.created_at.toISOString(), updatedAt: report.updated_at.toISOString(),
    })) });
  } catch (error) {
    console.error("admin copyright reports GET failed", error);
    return NextResponse.json({ error: "Không tải được báo cáo bản quyền." }, { status: 500 });
  }
}

export async function PATCH(request: Request) {
  const auth = await authorizeReviewer();
  if (auth.response) return auth.response;
  if (!sameOrigin(request)) return NextResponse.json({ error: "Origin không hợp lệ." }, { status: 403 });

  let body: unknown;
  try { body = await request.json(); } catch { return NextResponse.json({ error: "Dữ liệu không hợp lệ." }, { status: 400 }); }
  const parsed = updateSchema.safeParse(body);
  if (!parsed.success) return NextResponse.json({ error: "Trạng thái hoặc nội dung ghi chú không hợp lệ." }, { status: 400 });

  try {
    await ensureCopyrightTables();
    const input = parsed.data;
    const rows = await db<{ id: string }[]>`
      UPDATE copyright_reports SET status = ${input.status}, review_note = ${input.reviewNote},
        reviewed_at = CASE WHEN ${input.status} = 'new' THEN NULL ELSE NOW() END,
        updated_at = NOW()
      WHERE id = ${input.id} RETURNING id
    `;
    if (!rows.length) return NextResponse.json({ error: "Không tìm thấy báo cáo." }, { status: 404 });
    return NextResponse.json({ success: true });
  } catch (error) {
    console.error("admin copyright report PATCH failed", error);
    return NextResponse.json({ error: "Không cập nhật được báo cáo." }, { status: 500 });
  }
}
