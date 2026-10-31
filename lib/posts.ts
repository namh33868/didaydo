import { db, type PostRecord, type PostSummary } from "@/lib/db";
import { ensureFeaturedSchedule } from "@/lib/featured";

// List queries return PostSummary and avoid transferring full article HTML.
export async function getPublishedPosts(limit = 12, offset = 0) {
  await ensureFeaturedSchedule();
  return db<PostSummary[]>`
    SELECT id, title, slug, excerpt,
      char_length(regexp_replace(content_html, '<[^>]+>', ' ', 'g'))::int AS content_length,
      cover_image, cover_alt, cover_credit, category_name, category_slug,
      country_id, country_name, country_slug, destination_id, destination_name, destination_slug,
      tags, status, featured, author_name, source_url, source_name, seo_title, seo_description,
      published_at, created_at, updated_at
    FROM posts
    WHERE status = 'published' AND published_at <= NOW()
    ORDER BY featured DESC, published_at DESC NULLS LAST, created_at DESC
    LIMIT ${limit} OFFSET ${offset}
  `;
}

export async function getRecentPosts(limit = 6, excludeSlug?: string) {
  if (excludeSlug) {
    return db<PostSummary[]>`
      SELECT id, title, slug, excerpt,
        char_length(regexp_replace(content_html, '<[^>]+>', ' ', 'g'))::int AS content_length,
        cover_image, cover_alt, cover_credit, category_name, category_slug,
        country_id, country_name, country_slug, destination_id, destination_name, destination_slug,
        tags, status, featured, author_name, source_url, source_name, seo_title, seo_description,
        published_at, created_at, updated_at
      FROM posts
      WHERE status = 'published' AND published_at <= NOW() AND slug <> ${excludeSlug}
      ORDER BY published_at DESC NULLS LAST LIMIT ${limit}
    `;
  }
  return db<PostSummary[]>`
    SELECT id, title, slug, excerpt,
      char_length(regexp_replace(content_html, '<[^>]+>', ' ', 'g'))::int AS content_length,
      cover_image, cover_alt, cover_credit, category_name, category_slug,
      country_id, country_name, country_slug, destination_id, destination_name, destination_slug,
      tags, status, featured, author_name, source_url, source_name, seo_title, seo_description,
      published_at, created_at, updated_at
    FROM posts
    WHERE status = 'published' AND published_at <= NOW()
    ORDER BY published_at DESC NULLS LAST LIMIT ${limit}
  `;
}

export async function getWorldPosts(limit = 8) {
  await ensureFeaturedSchedule();
  return db<PostSummary[]>`
    SELECT p.id, p.title, p.slug, p.excerpt,
      char_length(regexp_replace(p.content_html, '<[^>]+>', ' ', 'g'))::int AS content_length,
      p.cover_image, p.cover_alt, p.cover_credit, p.category_name, p.category_slug,
      p.country_id, p.country_name, p.country_slug, p.destination_id, p.destination_name, p.destination_slug,
      p.tags, p.status, p.featured, p.author_name, p.source_url, p.source_name, p.seo_title, p.seo_description,
      p.published_at, p.created_at, p.updated_at
    FROM posts p
    LEFT JOIN destinations country ON country.id = p.country_id
    WHERE p.status = 'published' AND p.published_at <= NOW()
      AND (
        (country.kind = 'country' AND country.slug <> 'viet-nam')
        OR (p.country_id IS NULL AND p.country_name <> '' AND lower(p.country_slug) <> 'viet-nam')
      )
    ORDER BY p.featured DESC, p.published_at DESC NULLS LAST, p.created_at DESC
    LIMIT ${limit}
  `;
}

export async function getFeaturedPosts(limit = 8) {
  await ensureFeaturedSchedule();
  // Active manual picks first; newest published stories fill every remaining slot.
  return db<PostSummary[]>`
    SELECT id, title, slug, excerpt,
      char_length(regexp_replace(content_html, '<[^>]+>', ' ', 'g'))::int AS content_length,
      cover_image, cover_alt, cover_credit, category_name, category_slug,
      country_id, country_name, country_slug, destination_id, destination_name, destination_slug,
      tags, status, featured, author_name, source_url, source_name, seo_title, seo_description,
      published_at, created_at, updated_at
    FROM posts
    WHERE status = 'published' AND published_at <= NOW()
    ORDER BY CASE WHEN featured = TRUE AND featured_until > NOW() THEN 0 ELSE 1 END, published_at DESC NULLS LAST, created_at DESC
    LIMIT ${limit}
  `;
}

export async function getFeaturedPost() {
  await ensureFeaturedSchedule();
  const rows = await db<PostRecord[]>`
    SELECT * FROM posts WHERE status = 'published' AND published_at <= NOW()
    ORDER BY featured DESC, published_at DESC NULLS LAST LIMIT 1
  `;
  return rows[0] ?? null;
}

export async function getPostBySlug(slug: string) {
  const rows = await db<PostRecord[]>`
    SELECT * FROM posts WHERE slug = ${slug} AND status = 'published' AND published_at <= NOW() LIMIT 1
  `;
  return rows[0] ?? null;
}

export async function getPostsByCategory(slug: string, limit = 12, offset = 0) {
  await ensureFeaturedSchedule();
  return db<PostSummary[]>`
    SELECT id, title, slug, excerpt,
      char_length(regexp_replace(content_html, '<[^>]+>', ' ', 'g'))::int AS content_length,
      cover_image, cover_alt, cover_credit, category_name, category_slug,
      country_id, country_name, country_slug, destination_id, destination_name, destination_slug,
      tags, status, featured, author_name, source_url, source_name, seo_title, seo_description,
      published_at, created_at, updated_at
    FROM posts WHERE category_slug = ${slug} AND status = 'published' AND published_at <= NOW()
    ORDER BY featured DESC, published_at DESC NULLS LAST LIMIT ${limit} OFFSET ${offset}
  `;
}

export async function getCategorySlugs() {
  return db<{ category_slug: string; category_name: string; total: number }[]>`
    SELECT category_slug, MAX(category_name) AS category_name, COUNT(*)::int AS total
    FROM posts WHERE status = 'published' AND published_at <= NOW()
    GROUP BY category_slug ORDER BY MAX(category_name) ASC
  `;
}

export async function searchPosts(query: string, limit = 30) {
  const needle = `%${query.trim().replace(/[%_]/g, "\\$&")}%`;
  return db<PostSummary[]>`
    SELECT id, title, slug, excerpt,
      char_length(regexp_replace(content_html, '<[^>]+>', ' ', 'g'))::int AS content_length,
      cover_image, cover_alt, cover_credit, category_name, category_slug,
      country_id, country_name, country_slug, destination_id, destination_name, destination_slug,
      tags, status, featured, author_name, source_url, source_name, seo_title, seo_description,
      published_at, created_at, updated_at
    FROM posts
    WHERE status = 'published' AND published_at <= NOW()
      AND (title ILIKE ${needle} OR excerpt ILIKE ${needle} OR category_name ILIKE ${needle} OR country_name ILIKE ${needle} OR destination_name ILIKE ${needle} OR ${query} = ANY(tags))
    ORDER BY published_at DESC NULLS LAST LIMIT ${limit}
  `;
}

export async function getPublishedSlugs() {
  return db<{ slug: string; updated_at: Date }[]>`
    SELECT slug, updated_at FROM posts WHERE status = 'published' AND published_at <= NOW()
  `;
}

export async function getRelatedPosts(post: Pick<PostRecord, "slug" | "category_slug" | "country_id" | "destination_id">, limit = 4) {
  return db<PostSummary[]>`
    SELECT id, title, slug, excerpt,
      char_length(regexp_replace(content_html, '<[^>]+>', ' ', 'g'))::int AS content_length,
      cover_image, cover_alt, cover_credit, category_name, category_slug,
      country_id, country_name, country_slug, destination_id, destination_name, destination_slug,
      tags, status, featured, author_name, source_url, source_name, seo_title, seo_description,
      published_at, created_at, updated_at
    FROM posts
    WHERE status = 'published' AND published_at <= NOW() AND slug <> ${post.slug}
    ORDER BY
      CASE
        -- Explicit UUID casts make nullable parameters unambiguous to PostgreSQL.
        WHEN destination_id = ${post.destination_id ?? null}::uuid THEN 0
        WHEN country_id = ${post.country_id ?? null}::uuid THEN 1
        WHEN category_slug = ${post.category_slug} THEN 2
        ELSE 3
      END,
      published_at DESC NULLS LAST, created_at DESC
    LIMIT ${limit}
  `;
}
