import { createHash } from "node:crypto";
import { NextResponse } from "next/server";
import { z } from "zod";
import { db } from "@/lib/db";
import { ensureCopyrightTables } from "@/lib/copyright";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const reportSchema = z.object({
  claimantName: z.string().trim().min(2).max(120),
  claimantEmail: z.string().trim().email().max(254),
  relationship: z.enum(["owner", "authorized_agent", "other"]),
  workTitle: z.string().trim().max(180).default(""),
  originalWorkUrl: z.string().trim().max(2000).default(""),
  reportedUrl: z.string().trim().min(8).max(2000),
  details: z.string().trim().min(30).max(5000),
  declaration: z.literal(true),
  website: z.string().max(200).optional().default(""),
});

function sameOrigin(request: Request) {
  const origin = request.headers.get("origin");
  if (!origin) return false;
  try {
    return new URL(origin).origin === new URL(request.url).origin;
  } catch {
    return false;
  }
}

function isHttpsUrl(value: string, optional = false) {
  if (!value && optional) return true;
  try {
    const url = new URL(value);
    return url.protocol === "https:" && !!url.hostname && !url.username && !url.password;
  } catch {
    return false;
  }
}

function getRateLimitKey(request: Request) {
  const forwarded = request.headers.get("x-forwarded-for")?.split(",")[0]?.trim();
  const ip = forwarded || request.headers.get("x-real-ip") || "unavailable";
  const secret = process.env.SESSION_SECRET || process.env.INGEST_API_KEY || "copyright-report";
  return createHash("sha256").update(`${secret}:${ip}`).digest("hex");
}

export async function POST(request: Request) {
  if (!sameOrigin(request)) {
    return NextResponse.json({ error: "Nguồn gửi yêu cầu không hợp lệ." }, { status: 403 });
  }

  const raw = await request.text();
  if (raw.length > 16_000) {
    return NextResponse.json({ error: "Thông tin gửi lên vượt dung lượng cho phép." }, { status: 413 });
  }

  let body: unknown;
  try {
    body = JSON.parse(raw);
  } catch {
    return NextResponse.json({ error: "Dữ liệu gửi lên không hợp lệ." }, { status: 400 });
  }

  const parsed = reportSchema.safeParse(body);
  if (!parsed.success) {
    return NextResponse.json({ error: "Vui lòng kiểm tra lại thông tin và xác nhận quyền đại diện." }, { status: 400 });
  }

  const input = parsed.data;
  if (input.website.trim()) return NextResponse.json({ success: true });

  if (!isHttpsUrl(input.reportedUrl) || !isHttpsUrl(input.originalWorkUrl, true)) {
    return NextResponse.json({ error: "Các đường dẫn tác phẩm phải là URL HTTPS hợp lệ." }, { status: 400 });
  }

  try {
    await ensureCopyrightTables();
    const ipHash = getRateLimitKey(request);
    const limits = await db<{ request_count: number }[]>`
      INSERT INTO copyright_report_rate_limits (ip_hash, window_started_at, request_count)
      VALUES (${ipHash}, NOW(), 1)
      ON CONFLICT (ip_hash) DO UPDATE SET
        request_count = CASE
          WHEN copyright_report_rate_limits.window_started_at < NOW() - INTERVAL '1 hour' THEN 1
          ELSE copyright_report_rate_limits.request_count + 1
        END,
        window_started_at = CASE
          WHEN copyright_report_rate_limits.window_started_at < NOW() - INTERVAL '1 hour' THEN NOW()
          ELSE copyright_report_rate_limits.window_started_at
        END
      RETURNING request_count
    `;
    if (Number(limits[0]?.request_count || 0) > 5) {
      return NextResponse.json( { error: "Bán đã gửi quá nhiều báo cáo trong thời gian ngắn. Vui lòng thử lại sau." }, { status: 429 });
    }

    const rows = await db<{ id: string }[]>`
      INSERT INTO copyright_reports (
        claimant_name, claimant_email, relationship, work_title,
        original_work_url, reported_url, details, declaration
      ) VALUES (
        ${input.claimantName}, ${input.claimantEmail.toLowerCase()}, ${input.relationship},
        ${input.workTitle}, ${input.originalWorkUrl}, ${input.reportedUrl},
        ${input.details}, TRUE
      )
      RETURNING id
    `;

    return NextResponse.json({ success: true, reference: rows[0]?.id }, { status: 201 });
  } catch (error) {
    console.error("[copyright-report] Could not save report", error);
    return NextResponse.json({ error: "Chưa thể tiếp nhận báo cáo lúc này. Vui lòng thử lại sau." }, { status: 500 });
  }
}
