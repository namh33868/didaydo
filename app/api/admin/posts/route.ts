import { NextResponse } from "next/server";
import { getAdminSession, hasPermission } from "@/lib/auth";
import { db, type PostRecord } from "@/lib/db";
import { slugify } from "@/lib/format";
import { cleanArticleHtml } from "@/lib/sanitize";
import { contentToHtml } from "@/lib/content";
import { adminPostSchema } from "@/lib/validation";
import { ensureDestination, ensureTopic } from "@/lib/taxonomy";

export const runtime = "nodejs";

function sameOrigin(request: Request) {
  const origin = request.headers.get("origin");
  if (!origin) return true;
  try { return new URL(origin).origin === new URL(request.url).origin; } catch { return false; }
}

function toAdminPost(post: PostRecord) {
  return {
    id: post.id, title: post.title, slug: post.slug, excerpt: post.excerpt, contentHtml: post.content_html,
    coverImage: post.cover_image, coverAlt: post.cover_alt, coverCredit: post.cover_credit, category: post.category_name, categorySlug: post.category_slug,
    country: post.country_name, destination: post.destination_name, createdBy: post.created_by,
    tags: post.tags, status: post.status, featured: post.featured, authorName: post.author_name,
    sourceUrl: post.source_url || "", sourceName: post.source_name, seoTitle: post.seo_title,
    seoDescription: post.seo_description, publishedAt: post.published_at?.toISOString() || null,
    createdAt: post.created_at.toISOString(), updatedAt: post.updated_at.toISOString(),
  };
}

async function findUniqueSlug(value: string, excludeId?: string) {
  const base = slugify(value);
  let slug = base;
  let n = 2;
  while (true) {
    const match = excludeId
      ? await db<{ id: string }[]>`SELECT id FROM posts WHERE slug = ${slug} AND id <> ${excludeId} LIMIT 1`
      : await db<{ id: string }[]>`SELECT id FROM posts WHERE slug = ${slug} LIMIT 1`;
    if (!match.length) return slug;
    slug = `${base}-${n++}`;
    if (n > 1000) throw new Error("Không tạo được slug duy nhất.");
  }
}

export async function GET() {
  const session = await getAdminSession();
  if (!session) return NextResponse.json({ error: "Cần đăng nhập." }, { status: 401 });
  if (!hasPermission(session.role, "posts:view")) return NextResponse.json({ error: "Mày không có quyền xem bài viết." }, { status: 403 });
  try {
    const posts = session.role === "author" && session.userId
      ? await db<PostRecord[]>`SELECT * FROM posts WHERE created_by = ${session.userId} AND status = 'draft' ORDER BY updated_at DESC LIMIT 1000`
      : session.role === "author"
        ? []
        : await db<PostRecord[]>`SELECT * FROM posts ORDER BY updated_at DESC LIMIT 1000`;
    const ingestLogs = hasPermission(session.role, "ingest:view")
      ? await db<{ id: string; source: string; received_count: number; created_count: number; updated_count: number; failed_count: number; status: string; created_at: Date }[]>`SELECT id, source, received_count, created_count, updated_count, failed_count, status, created_at FROM ingest_logs ORDER BY created_at DESC LIMIT 8`
      : [];
    return NextResponse.json({
      posts: posts.map(toAdminPost),
      ingestLogs: ingestLogs.map((log) => ({ ...log, createdAt: log.created_at.toISOString() })),
      currentUser: { email: session.email, fullName: session.fullName, role: session.role, userId: session.userId },
    });
  } catch (error) {
    console.error("admin posts GET failed", error);
    return NextResponse.json({ error: "Không tải được bài viết. Hãy kiểm tra kết nối database." }, { status: 500 });
  }
}

export async function POST(request: Request) {
  const session = await getAdminSession();
  if (!session) return NextResponse.json({ error: "Cần đăng nhập." }, { status: 401 });
  if (!hasPermission(session.role, "posts:create")) return NextResponse.json({ error: "Tài khoản của mày chỉ có quyền xem nội dung." }, { status: 403 });
  if (!sameOrigin(request)) return NextResponse.json({ error: "Origin không hợp lệ." }, { status: 403 });
  let body: unknown;
  try { body = await request.json(); } catch { return NextResponse.json({ error: "Dữ liệu không hợp lệ." }, { status: 400 }); }
  const parsed = adminPostSchema.safeParse(body);
  if (!parsed.success) return NextResponse.json({ error: "Vui lòng kiểm tra tiêu đề và các trường dữ liệu.", details: parsed.error.flatten() }, { status: 400 });
  const input = parsed.data;
  try {
    const slug = await findUniqueSlug(input.slug || input.title);
    const topic = await ensureTopic(input.category || "Cẩm nang");
    const country = input.country ? await ensureDestination(input.country, "country") : null;
    const destination = input.destination && country ? await ensureDestination(input.destination, "city", country.id) : null;
    const status = session.role === "author" ? "draft" : input.status;
    const featured = session.role === "author" ? false : input.featured;
    const coverImage = input.coverImage?.trim() || "";
    if (status === "published" && !coverImage) {
      return NextResponse.json({ error: "Bài viết cần ảnh đại diện trước khi xuất bản." }, { status: 400 });
    }
    const publishedAt = status === "published" ? new Date() : null;
    const rows = await db<PostRecord[]>`
      INSERT INTO posts (title, slug, excerpt, content_html, cover_image, cover_alt, cover_credit, category_name, category_slug, country_id, country_name, country_slug, destination_id, destination_name, destination_slug, tags, status, featured, author_name, created_by, updated_by, source_url, source_name, seo_title, seo_description, published_at)
      VALUES (${input.title}, ${slug}, ${input.excerpt || ""}, ${cleanArticleHtml(contentToHtml(input.contentHtml || ""))}, ${coverImage}, ${input.coverAlt || ""}, ${input.coverCredit || ""}, ${topic.name}, ${topic.slug || slugify(topic.name)}, ${country?.id || null}, ${country?.name || ""}, ${country?.slug || ""}, ${destination?.id || null}, ${destination?.name || ""}, ${destination?.slug || ""}, ${input.tags || []}, ${status}, ${featured || false}, ${input.authorName || session.fullName || "Ban biên tập"}, ${session.userId}, ${session.userId}, ${input.sourceUrl || null}, ${input.sourceName || ""}, ${input.seoTitle || ""}, ${input.seoDescription || ""}, ${publishedAt})
      RETURNING *
    `;
    return NextResponse.json({ post: toAdminPost(rows[0]) }, { status: 201 });
  } catch (error) {
    console.error("admin posts POST failed", error);
    return NextResponse.json({ error: "Không lưu được bài viết. Có thể URL nguồn đã được dùng cho một bài khác." }, { status: 500 });
  }
}

export async function PATCH(request: Request) {
  const session = await getAdminSession();
  if (!session) return NextResponse.json({ error: "Cần đăng nhập." }, { status: 401 });
  if (!hasPermission(session.role, "posts:edit:any") && !hasPermission(session.role, "posts:edit:own")) {
    return NextResponse.json({ error: "Tài khoản của mày không có quyền chỉnh sửa bài viết." }, { status: 403 });
  }
  if (!sameOrigin(request)) return NextResponse.json({ error: "Origin không hợp lệ." }, { status: 403 });
  let body: unknown;
  try { body = await request.json(); } catch { return NextResponse.json({ error: "Dữ liệu không hợp lệ." }, { status: 400 }); }
  const parsed = adminPostSchema.safeParse(body);
  if (!parsed.success) {
    return NextResponse.json({ error: "Dữ liệu cập nhật không hợp lệ hoặc thiếu ID." }, { status: 400 });
  }

  const input = parsed.data;
  // Keep the ID as a definite string: adminPostSchema intentionally makes id optional for POST.
  const postId = input.id ?? "";
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(postId)) {
    return NextResponse.json({ error: "Dữ liệu cập nhật không hợp lệ hoặc thiếu ID." }, { status: 400 });
  }
  try {
    const existing = (await db<PostRecord[]>`SELECT * FROM posts WHERE id = ${postId} LIMIT 1`)[0];
    if (!existing) return NextResponse.json({ error: "Không tìm thấy bài viết." }, { status: 404 });
    if (!hasPermission(session.role, "posts:edit:any")) {
      if (existing.created_by !== session.userId) return NextResponse.json({ error: "Mày chỉ có thể sửa bài do chính mình tạo." }, { status: 403 });
      if (existing.status !== "draft") return NextResponse.json({ error: "Tác giả chỉ được chỉnh sửa bài đang ở trạng thái nháp. Hãy nhờ biên tập viên mở lại bài." }, { status: 403 });
    }
    const slug = await findUniqueSlug(input.slug || input.title, postId);
    const topic = await ensureTopic(input.category || "Cẩm nang");
    const country = input.country ? await ensureDestination(input.country, "country") : null;
    const destination = input.destination && country ? await ensureDestination(input.destination, "city", country.id) : null;
    const status = session.role === "author" ? "draft" : input.status;
    const featured = session.role === "author" ? false : input.featured;
    const coverImage = input.coverImage?.trim() || existing.cover_image || "";
    if (status === "published" && !coverImage) {
      return NextResponse.json({ error: "Bài viết cần ảnh đại diện trước khi xuất bản." }, { status: 400 });
    }
    const publishedAt = status === "published" ? existing.published_at || new Date() : null;
    const rows = await db<PostRecord[]>`
      UPDATE posts SET title = ${input.title}, slug = ${slug}, excerpt = ${input.excerpt || ""}, content_html = ${cleanArticleHtml(contentToHtml(input.contentHtml || ""))},
        cover_image = ${coverImage}, cover_alt = ${input.coverAlt || ""}, cover_credit = ${input.coverCredit || ""}, category_name = ${topic.name}, category_slug = ${topic.slug || slugify(topic.name)},
        country_id = ${country?.id || null}, country_name = ${country?.name || ""}, country_slug = ${country?.slug || ""},
        destination_id = ${destination?.id || null}, destination_name = ${destination?.name || ""}, destination_slug = ${destination?.slug || ""},
        tags = ${input.tags || []}, status = ${status}, featured = ${featured || false}, author_name = ${input.authorName || "Ban biên tập"},
        source_url = ${input.sourceUrl || null}, source_name = ${input.sourceName || ""}, seo_title = ${input.seoTitle || ""}, seo_description = ${input.seoDescription || ""},
        published_at = ${publishedAt}, updated_by = ${session.userId}, updated_at = NOW() WHERE id = ${postId} RETURNING *
    `;
    return NextResponse.json({ post: toAdminPost(rows[0]) });
  } catch (error) {
    console.error("admin posts PATCH failed", error);
    return NextResponse.json({ error: "Không cập nhật được bài viết. Kiểm tra URL nguồn và slug có bị trùng không." }, { status: 500 });
  }
}

export async function DELETE(request: Request) {
  const session = await getAdminSession();
  if (!session) return NextResponse.json({ error: "Cần đăng nhập." }, { status: 401 });
  if (!hasPermission(session.role, "posts:delete")) return NextResponse.json({ error: "Tài khoản của mày không có quyền xóa bài viết." }, { status: 403 });
  if (!sameOrigin(request)) return NextResponse.json({ error: "Origin không hợp lệ." }, { status: 403 });
  const id = new URL(request.url).searchParams.get("id");
  if (!id || !/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(id)) return NextResponse.json({ error: "ID bài viết không hợp lệ." }, { status: 400 });
  const rows = await db<{ id: string }[]>`DELETE FROM posts WHERE id = ${id} RETURNING id`;
  if (!rows.length) return NextResponse.json({ error: "Không tìm thấy bài viết." }, { status: 404 });
  return NextResponse.json({ success: true });
}
