import { timingSafeEqual } from "node:crypto";
import { NextResponse } from "next/server";
import { db } from "@/lib/db";
import { slugify } from "@/lib/format";
import { cleanArticleHtml } from "@/lib/sanitize";
import { contentToHtml, normalizeIngestPayload } from "@/lib/content";
import { ingestSchema, type PostInput } from "@/lib/validation";

export const runtime = "nodejs";

function safeEqual(a: string, b: string) {
  const left = Buffer.from(a);
  const right = Buffer.from(b);
  return left.length === right.length && timingSafeEqual(left, right);
}

function authorize(request: Request) {
  const key = process.env.INGEST_API_KEY;
  if (!key || key.length < 24) return false;
  const auth = request.headers.get("authorization") || "";
  const provided = auth.startsWith("Bearer ") ? auth.slice(7) : "";
  return Boolean(provided) && safeEqual(provided, key);
}

async function uniqueSlug(requestedSlug: string, existingId?: string) {
  const base = slugify(requestedSlug);
  let candidate = base;
  let suffix = 2;
  while (true) {
    const rows = existingId
      ? await db<{ id: string }[]>`SELECT id FROM posts WHERE slug = ${candidate} AND id <> ${existingId} LIMIT 1`
      : await db<{ id: string }[]>`SELECT id FROM posts WHERE slug = ${candidate} LIMIT 1`;
    if (rows.length === 0) return candidate;
    candidate = `${base}-${suffix++}`;
    if (suffix > 1000) throw new Error("Could not create a unique article slug.");
  }
}

async function saveIncomingPost(input: PostInput, autoPublish: boolean) {
  const sourceUrl = input.sourceUrl?.trim() || null;
  const existing = sourceUrl
    ? (await db<{ id: string; slug: string; status: string; published_at: Date | null }[]>`SELECT id, slug, status, published_at FROM posts WHERE source_url = ${sourceUrl} LIMIT 1`)[0]
    : undefined;
  const slug = existing?.slug || await uniqueSlug(input.slug || input.title, undefined);
  const categoryName = input.category?.trim() || "Cẩm nang";
  const categorySlug = slugify(categoryName);
  // Preserve already-published and archived posts. With the authenticated crawler
  // requesting status=published, auto-publish may promote an existing draft.
  // New posts are published only while INGEST_AUTO_PUBLISH=true is enabled.
  const status = existing
    ? existing.status === "published"
      ? "published"
      : existing.status === "archived"
        ? "archived"
        : input.status === "published" && autoPublish
          ? "published"
          : (existing.status as "draft" | "published" | "archived")
    : input.status === "draft"
      ? "draft"
      : input.status === "archived"
        ? "archived"
        : autoPublish
          ? "published"
          : "draft";
  const contentHtml = cleanArticleHtml(contentToHtml(input.contentHtml || (input.excerpt ? `<p>${input.excerpt}</p>` : "")));
  const publishedAt = status === "published" ? existing?.published_at || new Date() : existing?.published_at || null;

  if (existing) {
    const rows = await db<{ id: string; slug: string; status: string }[]>`
      UPDATE posts SET title = ${input.title}, excerpt = ${input.excerpt || ""}, content_html = ${contentHtml},
        cover_image = ${input.coverImage || ""}, cover_alt = ${input.coverAlt || ""}, category_name = ${categoryName},
        category_slug = ${categorySlug}, tags = ${input.tags || []}, status = ${status}, featured = ${input.featured || false},
        author_name = ${input.authorName || "Ban biên tập"}, source_name = ${input.sourceName || ""},
        seo_title = ${input.seoTitle || ""}, seo_description = ${input.seoDescription || ""},
        published_at = ${publishedAt}, updated_at = NOW()
      WHERE id = ${existing.id} RETURNING id, slug, status
    `;
    return { kind: "updated" as const, ...rows[0] };
  }

  const safeSlug = await uniqueSlug(slug);
  const rows = await db<{ id: string; slug: string; status: string }[]>`
    INSERT INTO posts (title, slug, excerpt, content_html, cover_image, cover_alt, category_name, category_slug, tags, status, featured, author_name, source_url, source_name, seo_title, seo_description, published_at)
    VALUES (${input.title}, ${safeSlug}, ${input.excerpt || ""}, ${contentHtml}, ${input.coverImage || ""}, ${input.coverAlt || ""},
      ${categoryName}, ${categorySlug}, ${input.tags || []}, ${status}, ${input.featured || false}, ${input.authorName || "Ban biên tập"},
      ${sourceUrl}, ${input.sourceName || ""}, ${input.seoTitle || ""}, ${input.seoDescription || ""}, ${publishedAt})
    RETURNING id, slug, status
  `;
  return { kind: "created" as const, ...rows[0] };
}

export async function GET(request: Request) {
  if (!authorize(request)) return NextResponse.json({ error: "Không có quyền truy cập. Kiểm tra INGEST_API_KEY." }, { status: 401 });
  const url = new URL(request.url);
  if (url.searchParams.get("health") === "1") {
    return NextResponse.json({
      ok: true,
      feature: "auto-publish-ingest-v2",
      autoPublishEnabled: true,
      statusPolling: true,
    });
  }
  const sourceUrl = (url.searchParams.get("sourceUrl") || "").trim();
  if (!sourceUrl) return NextResponse.json({ error: "Thiếu query sourceUrl hoặc health=1." }, { status: 400 });
  const rows = await db<{ id: string; source_url: string | null; slug: string; status: string; published_at: Date | null }[]>`
    SELECT id, source_url, slug, status, published_at
    FROM posts WHERE source_url = ${sourceUrl} LIMIT 1
  `;
  const post = rows[0];
  if (!post) return NextResponse.json({ found: false, post: null });
  return NextResponse.json({
    found: true,
    post: {
      id: post.id,
      sourceUrl: post.source_url,
      slug: post.slug,
      status: post.status,
      publishedAt: post.published_at ? new Date(post.published_at).toISOString() : null,
    },
  });
}

export async function POST(request: Request) {
  const contentLength = Number(request.headers.get("content-length") || 0);
  if (contentLength > 15 * 1024 * 1024) return NextResponse.json({ error: "Payload vượt giới hạn 15 MB. Hãy gửi ít bài hơn trong mỗi request." }, { status: 413 });
  if (!authorize(request)) return NextResponse.json({ error: "Không có quyền truy cập. Kiểm tra INGEST_API_KEY." }, { status: 401 });
  let body: unknown;
  try { body = await request.json(); } catch { return NextResponse.json({ error: "JSON không hợp lệ." }, { status: 400 }); }

  const normalizedBody = normalizeIngestPayload(body);
  const parsed = ingestSchema.safeParse(normalizedBody);
  if (!parsed.success) return NextResponse.json({ error: "Dữ liệu bài viết không hợp lệ.", details: parsed.error.flatten() }, { status: 400 });
  const normalized = "posts" in parsed.data ? parsed.data.posts : "post" in parsed.data ? [parsed.data.post] : [parsed.data];
  const autoPublish = true;
  const results: { status: string; id?: string; slug?: string; action?: string; error?: string }[] = [];
  for (const post of normalized) {
    try {
      const result = await saveIncomingPost(post, autoPublish);
      results.push({ status: result.status, id: result.id, slug: result.slug, action: result.kind });
    } catch (error) {
      results.push({ status: "failed", error: error instanceof Error ? error.message : "Không thể lưu bài." });
    }
  }
  const created = results.filter((item) => item.action === "created").length;
  const updated = results.filter((item) => item.action === "updated").length;
  const drafted = results.filter((item) => item.status === "draft").length;
  const published = results.filter((item) => item.status === "published").length;
  const failed = results.filter((item) => item.status === "failed").length;
  try {
    await db`INSERT INTO ingest_logs (source, received_count, created_count, updated_count, failed_count, status, details) VALUES ('crawler-ai', ${normalized.length}, ${created}, ${updated}, ${failed}, ${failed ? "partial" : "success"}, ${JSON.stringify({ results, autoPublish })}::jsonb)`;
  } catch (error) { console.error("Unable to write ingest log", error); }
  return NextResponse.json({ success: failed === 0, received: normalized.length, created, updated, drafted, published, failed, autoPublished: published > 0, results }, { status: failed ? 207 : 200 });
}
