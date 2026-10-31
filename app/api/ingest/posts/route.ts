import { timingSafeEqual } from "node:crypto";
import { NextResponse } from "next/server";
import { db } from "@/lib/db";
import { slugify } from "@/lib/format";
import { cleanArticleHtml } from "@/lib/sanitize";
import { contentToHtml, normalizeIngestPayload } from "@/lib/content";
import { ingestSchema, type PostInput } from "@/lib/validation";
import { ensureDestination, ensureTopic } from "@/lib/taxonomy";

export const runtime = "nodejs";

type PostStatus = "draft" | "published" | "archived";

type ExistingPost = {
  id: string;
  slug: string;
  status: PostStatus;
  published_at: Date | null;
  excerpt: string;
  content_html: string;
  cover_image: string;
  cover_alt: string;
  cover_credit: string;
  category_name: string;
  featured: boolean;
  author_name: string;
  source_name: string;
  seo_title: string;
  seo_description: string;
  tags: string[];
  country_id: string | null;
  country_name: string;
  country_slug: string;
  destination_id: string | null;
  destination_name: string;
  destination_slug: string;
};

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

function isAutoPublishEnabled() {
  const configured = process.env.INGEST_AUTO_PUBLISH?.trim().toLowerCase();
  // Keep the current production behavior by default; set INGEST_AUTO_PUBLISH=false
  // to pause automatic publication without changing code.
  return configured ? configured === "true" : true;
}

function resolveIngestStatus(
  requestedStatus: PostInput["status"],
  existingStatus: PostStatus | undefined,
  autoPublish: boolean,
): PostStatus {
  // An ingestion retry must never unpublish a public post or restore an archived one.
  if (existingStatus === "published" || existingStatus === "archived") return existingStatus;
  if (requestedStatus === "archived") return "archived";

  // INGEST_AUTO_PUBLISH is the policy switch for this authenticated crawler endpoint.
  // The crawler currently sends status="draft" for compatibility with its old draft
  // workflow, so that value must not silently defeat the site's auto-publish setting.
  return autoPublish ? "published" : "draft";
}

async function uniqueSlug(requestedSlug: string, existingId?: string) {
  const base = slugify(requestedSlug) || "bai-viet";
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
    ? (
        await db<ExistingPost[]>`
          SELECT id, slug, status, published_at, excerpt, content_html, cover_image, cover_alt,
            cover_credit, category_name, featured, author_name, source_name, seo_title,
            seo_description, tags, country_id, country_name, country_slug, destination_id,
            destination_name, destination_slug
          FROM posts WHERE source_url = ${sourceUrl} LIMIT 1
        `
      )[0]
    : undefined;

  const incomingContent = input.contentHtml?.trim()
    || existing?.content_html
    || (input.excerpt?.trim() ? `<p>${input.excerpt}</p>` : "");
  if (!incomingContent.trim()) {
    throw new Error("Article content is empty.");
  }
  const contentHtml = cleanArticleHtml(contentToHtml(incomingContent));
  const status = resolveIngestStatus(input.status, existing?.status, autoPublish);
  const publishedAt: Date | null = status === "published"
    ? existing?.published_at || new Date()
    : status === "archived"
      ? existing?.published_at || null
      : null;

  // Avoid erasing editorial metadata when a crawler retry omits optional fields.
  const requestedCategory = input.category?.trim();
  const categoryName = requestedCategory && (requestedCategory !== "Cẩm nang" || !existing?.category_name)
    ? requestedCategory
    : existing?.category_name || requestedCategory || "Cẩm nang";
  const topic = await ensureTopic(categoryName);
  const categorySlug = topic.slug || slugify(categoryName);

  const countryName = input.country?.trim() || existing?.country_name || "";
  const destinationName = input.destination?.trim() || existing?.destination_name || "";
  const country = countryName ? await ensureDestination(countryName, "country") : null;
  const countryId = country?.id || existing?.country_id || null;
  const storedCountryName = country?.name || existing?.country_name || "";
  const countrySlug = country?.slug || existing?.country_slug || "";
  const destination = destinationName && countryId
    ? await ensureDestination(destinationName, "city", countryId)
    : null;
  const destinationId = destination?.id || existing?.destination_id || null;
  const storedDestinationName = destination?.name || existing?.destination_name || "";
  const destinationSlug = destination?.slug || existing?.destination_slug || "";

  const excerpt = input.excerpt?.trim() || existing?.excerpt || "";
  const coverImage = input.coverImage?.trim() || existing?.cover_image || "";
  if (status === "published" && !coverImage) {
    throw new Error("Published posts must have a cover image.");
  }
  const coverAlt = input.coverAlt?.trim() || existing?.cover_alt || "";
  const coverCredit = input.coverCredit?.trim() || existing?.cover_credit || "";
  const tags = input.tags?.length ? input.tags : existing?.tags || [];
  const featured = Boolean(input.featured || existing?.featured);
  const authorName = input.authorName?.trim() && input.authorName !== "Ban biên tập"
    ? input.authorName.trim()
    : existing?.author_name || input.authorName || "Ban biên tập";
  const sourceName = input.sourceName?.trim() || existing?.source_name || "";
  const seoTitle = input.seoTitle?.trim() || existing?.seo_title || "";
  const seoDescription = input.seoDescription?.trim() || existing?.seo_description || "";

  if (existing) {
    const rows = await db<{ id: string; slug: string; status: PostStatus }[]>`
      UPDATE posts SET title = ${input.title}, excerpt = ${excerpt}, content_html = ${contentHtml},
        cover_image = ${coverImage}, cover_alt = ${coverAlt}, cover_credit = ${coverCredit},
        category_name = ${categoryName}, category_slug = ${categorySlug},
        country_id = ${countryId}, country_name = ${storedCountryName}, country_slug = ${countrySlug},
        destination_id = ${destinationId}, destination_name = ${storedDestinationName}, destination_slug = ${destinationSlug},
        tags = ${tags}, status = ${status}, featured = ${featured}, author_name = ${authorName},
        source_name = ${sourceName}, seo_title = ${seoTitle}, seo_description = ${seoDescription},
        published_at = ${publishedAt}, updated_at = NOW()
      WHERE id = ${existing.id} RETURNING id, slug, status
    `;
    if (!rows[0]) throw new Error("Post update returned no row.");
    return { kind: "updated" as const, ...rows[0] };
  }

  const safeSlug = await uniqueSlug(input.slug || input.title);
  const rows = await db<{ id: string; slug: string; status: PostStatus }[]>`
    INSERT INTO posts (
      title, slug, excerpt, content_html, cover_image, cover_alt, cover_credit,
      category_name, category_slug, country_id, country_name, country_slug,
      destination_id, destination_name, destination_slug, tags, status, featured,
      author_name, source_url, source_name, seo_title, seo_description, published_at
    ) VALUES (
      ${input.title}, ${safeSlug}, ${excerpt}, ${contentHtml}, ${coverImage}, ${coverAlt}, ${coverCredit},
      ${categoryName}, ${categorySlug}, ${countryId}, ${storedCountryName}, ${countrySlug},
      ${destinationId}, ${storedDestinationName}, ${destinationSlug}, ${tags}, ${status}, ${featured},
      ${authorName}, ${sourceUrl}, ${sourceName}, ${seoTitle}, ${seoDescription}, ${publishedAt}
    )
    RETURNING id, slug, status
  `;
  if (!rows[0]) throw new Error("Post insert returned no row.");
  return { kind: "created" as const, ...rows[0] };
}

export async function GET(request: Request) {
  if (!authorize(request)) {
    return NextResponse.json({ error: "Không có quyền truy cập." }, { status: 401 });
  }

  const url = new URL(request.url);
  if (url.searchParams.get("health") === "1") {
    return NextResponse.json({
      ok: true,
      feature: "auto-publish-ingest-v2",
      autoPublishEnabled: isAutoPublishEnabled(),
      statusPolling: true,
    });
  }

  if (url.searchParams.get("missingCover") === "1") {
    const requestedLimit = Number(url.searchParams.get("limit") || "5");
    const limit = Number.isFinite(requestedLimit) ? Math.max(1, Math.min(Math.trunc(requestedLimit), 25)) : 5;
    const posts = await db<{
      id: string; title: string; excerpt: string; category_name: string;
      country_name: string; destination_name: string; source_url: string;
      source_name: string; seo_title: string; seo_description: string; tags: string[];
    }[]>`
      SELECT id, title, excerpt, category_name, country_name, destination_name,
        source_url, source_name, seo_title, seo_description, tags
      FROM posts
      WHERE status = 'published'
        AND COALESCE(BTRIM(cover_image), '') = ''
        AND source_url IS NOT NULL
        AND BTRIM(source_url) <> ''
      ORDER BY random()
      LIMIT ${limit}
    `;
    return NextResponse.json({ posts });
  }

  const sourceUrl = (url.searchParams.get("sourceUrl") || "").trim();
  if (!sourceUrl) {
    return NextResponse.json({ error: "Thiếu query sourceUrl, missingCover=1 hoặc health=1." }, { status: 400 });
  }

  const rows = await db<{ id: string; source_url: string | null; slug: string; status: PostStatus; published_at: Date | null }[]>`
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
  if (contentLength > 15 * 1024 * 1024) {
    return NextResponse.json({ error: "Payload vượt giới hạn 15 MB. Hãy gửi ít bài hơn trong mỗi request." }, { status: 413 });
  }
  if (!authorize(request)) {
    return NextResponse.json({ error: "Không có quyền truy cập. Kiểm tra INGEST_API_KEY." }, { status: 401 });
  }

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "JSON không hợp lệ." }, { status: 400 });
  }

  const normalizedBody = normalizeIngestPayload(body);
  const parsed = ingestSchema.safeParse(normalizedBody);
  if (!parsed.success) {
    return NextResponse.json({ error: "Dữ liệu bài viết không hợp lệ.", details: parsed.error.flatten() }, { status: 400 });
  }

  const normalized = "posts" in parsed.data
    ? parsed.data.posts
    : "post" in parsed.data
      ? [parsed.data.post]
      : [parsed.data];
  const autoPublish = isAutoPublishEnabled();
  const results: { status: string; id?: string; slug?: string; action?: string; error?: string }[] = [];

  for (const post of normalized) {
    try {
      const result = await saveIncomingPost(post, autoPublish);
      results.push({ status: result.status, id: result.id, slug: result.slug, action: result.kind });
    } catch (error) {
      // Keep database/SQL details in server logs, not in the HTTP response.
      console.error("[ingest] Failed to save incoming post", {
        sourceUrl: post.sourceUrl || null,
        error,
      });
      results.push({ status: "failed", error: "Không thể lưu bài viết. Kiểm tra log server để biết chi tiết." });
    }
  }

  const created = results.filter((item) => item.action === "created").length;
  const updated = results.filter((item) => item.action === "updated").length;
  const drafted = results.filter((item) => item.status === "draft").length;
  const published = results.filter((item) => item.status === "published").length;
  const failed = results.filter((item) => item.status === "failed").length;

  try {
    await db`
      INSERT INTO ingest_logs (source, received_count, created_count, updated_count, failed_count, status, details)
      VALUES ('crawler-ai', ${normalized.length}, ${created}, ${updated}, ${failed},
        ${failed ? "partial" : "success"},
        ${JSON.stringify({ results, autoPublish, requestedArchivedCount: normalized.filter((post) => post.status === "archived").length })}::jsonb)
    `;
  } catch (error) {
    console.error("[ingest] Unable to write ingest log", error);
  }

  return NextResponse.json({
    success: failed === 0,
    received: normalized.length,
    created,
    updated,
    drafted,
    published,
    failed,
    autoPublished: autoPublish && published > 0,
    results,
  }, { status: failed ? 207 : 200 });
}
