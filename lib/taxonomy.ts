import { db, type PostSummary } from "@/lib/db";
import { slugify } from "@/lib/format";
import { normalizeEditorialCategory } from "@/lib/editorial-taxonomy";

export type DestinationKind = "country" | "city";

const COUNTRY_ALIASES: Record<string, string> = {
  "vietnam": "Việt Nam", "viet-nam": "Việt Nam", "vn": "Việt Nam",
  "japan": "Nhật Bản", "nhat-ban": "Nhật Bản",
  "thailand": "Thái Lan", "thai-land": "Thái Lan",
  "south-korea": "Hàn Quốc", "southkorea": "Hàn Quốc", "korea": "Hàn Quốc", "han-quoc": "Hàn Quốc",
  "singapore": "Singapore", "malaysia": "Malaysia", "indonesia": "Indonesia",
  "taiwan": "Đài Loan", "dai-loan": "Đài Loan",
  "china": "Trung Quốc", "trung-quoc": "Trung Quốc",
  "laos": "Lào", "lao": "Lào", "cambodia": "Campuchia", "campuchia": "Campuchia",
  "france": "Pháp", "phap": "Pháp", "italy": "Ý", "australia": "Úc", "uc": "Úc",
  "united-states": "Hoa Kỳ", "united-states-of-america": "Hoa Kỳ", "usa": "Hoa Kỳ", "us": "Hoa Kỳ", "hoa-ky": "Hoa Kỳ",
};

/** Canonicalize common English/Vietnamese country labels so AI output does not create duplicate country pages. */
export function normalizeCountryName(value: string) {
  const trimmed = value.trim();
  return COUNTRY_ALIASES[slugify(trimmed).toLowerCase()] || trimmed;
}
export type DestinationRecord = {
  id: string;
  name: string;
  slug: string;
  kind: DestinationKind;
  parent_id: string | null;
  description: string;
  cover_image: string;
  display_order: number;
  post_count?: number;
};
export type TopicCount = { category_name: string; category_slug: string; total: number };

export async function ensureTopic(name: string) {
  const normalized = normalizeEditorialCategory(name);
  const rows = await db<{ id: string; name: string; slug: string }[]>`
    INSERT INTO categories (name, slug, description, display_order)
    VALUES (${normalized.name}, ${normalized.slug}, ${normalized.description}, ${normalized.displayOrder})
    ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name, description = EXCLUDED.description, display_order = EXCLUDED.display_order
    RETURNING id, name, slug
  `;
  return rows[0];
}

/** Creates a country or a city attached to a country and returns its stable record. */
export async function ensureDestination(name: string, kind: DestinationKind, parentId?: string | null) {
  const rawName = name.trim();
  if (!rawName) return null;
  const normalized = kind === "country" ? normalizeCountryName(rawName) : rawName;
  if (kind === "city" && !parentId) throw new Error("A city must belong to a country.");

  const existing = kind === "country"
    ? await db<DestinationRecord[]>`SELECT * FROM destinations WHERE kind = 'country' AND parent_id IS NULL AND lower(name) = lower(${normalized}) LIMIT 1`
    : await db<DestinationRecord[]>`SELECT * FROM destinations WHERE kind = 'city' AND parent_id = ${parentId!} AND lower(name) = lower(${normalized}) LIMIT 1`;
  if (existing[0]) return existing[0];

  const baseSlug = slugify(normalized);
  let candidate = baseSlug;
  if (kind === "city") {
    const parent = await db<{ slug: string }[]>`SELECT slug FROM destinations WHERE id = ${parentId!} LIMIT 1`;
    const conflict = await db<{ id: string; parent_id: string | null; kind: DestinationKind }[]>`SELECT id, parent_id, kind FROM destinations WHERE slug = ${candidate} LIMIT 1`;
    if (conflict[0] && (conflict[0].parent_id !== parentId || conflict[0].kind !== "city")) {
      candidate = `${baseSlug}-${parent[0]?.slug || "diem-den"}`;
    }
  }

  let suffix = 2;
  while (true) {
    const collision = await db<DestinationRecord[]>`SELECT * FROM destinations WHERE slug = ${candidate} LIMIT 1`;
    if (collision[0]) {
      const sameParent = kind === "country"
        ? collision[0].kind === "country" && collision[0].parent_id === null
        : collision[0].kind === "city" && collision[0].parent_id === parentId;
      if (sameParent && collision[0].name.toLocaleLowerCase("vi-VN") === normalized.toLocaleLowerCase("vi-VN")) return collision[0];
      candidate = `${baseSlug}-${kind === "city" ? "diem-den" : "quoc-gia"}-${suffix++}`;
      continue;
    }

    const inserted = await db<DestinationRecord[]>`
      INSERT INTO destinations (name, slug, kind, parent_id, updated_at)
      VALUES (${normalized}, ${candidate}, ${kind}, ${parentId || null}, NOW())
      ON CONFLICT (slug) DO NOTHING
      RETURNING *
    `;
    if (inserted[0]) return inserted[0];
    candidate = `${baseSlug}-${suffix++}`;
  }
}

export async function getCountries() {
  return db<(DestinationRecord & { post_count: number; resolved_cover: string })[]>`
    SELECT d.*, COUNT(p.id)::int AS post_count,
      COALESCE(NULLIF(d.cover_image, ''), MAX(NULLIF(p.cover_image, ''))) AS resolved_cover
    FROM destinations d
    LEFT JOIN posts p ON p.country_id = d.id AND p.status = 'published' AND p.published_at <= NOW()
    WHERE d.kind = 'country' AND d.parent_id IS NULL
    GROUP BY d.id
    ORDER BY d.display_order ASC, d.name ASC
  `;
}

export async function getCountryBySlug(slug: string) {
  const rows = await db<(DestinationRecord & { post_count: number; resolved_cover: string })[]>`
    SELECT d.*, COUNT(p.id)::int AS post_count,
      COALESCE(NULLIF(d.cover_image, ''), MAX(NULLIF(p.cover_image, ''))) AS resolved_cover
    FROM destinations d
    LEFT JOIN posts p ON p.country_id = d.id AND p.status = 'published' AND p.published_at <= NOW()
    WHERE d.kind = 'country' AND d.parent_id IS NULL AND d.slug = ${slug}
    GROUP BY d.id LIMIT 1
  `;
  return rows[0] ?? null;
}

export async function getCitiesByCountry(countryId: string) {
  return db<(DestinationRecord & { post_count: number; resolved_cover: string })[]>`
    SELECT d.*, COUNT(p.id)::int AS post_count,
      COALESCE(NULLIF(d.cover_image, ''), MAX(NULLIF(p.cover_image, ''))) AS resolved_cover
    FROM destinations d
    LEFT JOIN posts p ON p.destination_id = d.id AND p.status = 'published' AND p.published_at <= NOW()
    WHERE d.kind = 'city' AND d.parent_id = ${countryId}
    GROUP BY d.id
    HAVING COUNT(p.id) > 0
    ORDER BY d.display_order ASC, d.name ASC
  `;
}

export async function getCityBySlug(countryId: string, slug: string) {
  const rows = await db<(DestinationRecord & { post_count: number; resolved_cover: string })[]>`
    SELECT d.*, COUNT(p.id)::int AS post_count,
      COALESCE(NULLIF(d.cover_image, ''), MAX(NULLIF(p.cover_image, ''))) AS resolved_cover
    FROM destinations d
    LEFT JOIN posts p ON p.destination_id = d.id AND p.status = 'published' AND p.published_at <= NOW()
    WHERE d.kind = 'city' AND d.parent_id = ${countryId} AND d.slug = ${slug}
    GROUP BY d.id LIMIT 1
  `;
  return rows[0] ?? null;
}

export async function getTopicsForLocation(countryId: string, cityId?: string): Promise<TopicCount[]> {
  if (cityId) {
    return db<TopicCount[]>`
      SELECT category_name, category_slug, COUNT(*)::int AS total FROM posts
      WHERE destination_id = ${cityId} AND status = 'published' AND published_at <= NOW()
      GROUP BY category_name, category_slug ORDER BY total DESC, category_name ASC
    `;
  }
  return db<TopicCount[]>`
    SELECT category_name, category_slug, COUNT(*)::int AS total FROM posts
    WHERE country_id = ${countryId} AND status = 'published' AND published_at <= NOW()
    GROUP BY category_name, category_slug ORDER BY total DESC, category_name ASC
  `;
}

export async function getPostsForLocation(countryId: string, cityId: string | undefined, topicSlug: string | undefined, limit = 12, offset = 0) {
  if (cityId && topicSlug) {
    return db<PostSummary[]>`
      SELECT id, title, slug, excerpt,
        char_length(regexp_replace(content_html, '<[^>]+>', ' ', 'g'))::int AS content_length,
        cover_image, cover_alt, cover_credit, category_name, category_slug,
        country_id, country_name, country_slug, destination_id, destination_name, destination_slug,
        tags, status, featured, author_name, source_url, source_name, seo_title, seo_description,
        published_at, created_at, updated_at FROM posts WHERE destination_id = ${cityId} AND category_slug = ${topicSlug}
        AND status = 'published' AND published_at <= NOW()
      ORDER BY featured DESC, published_at DESC NULLS LAST, created_at DESC LIMIT ${limit} OFFSET ${offset}
    `;
  }
  if (cityId) {
    return db<PostSummary[]>`
      SELECT id, title, slug, excerpt,
        char_length(regexp_replace(content_html, '<[^>]+>', ' ', 'g'))::int AS content_length,
        cover_image, cover_alt, cover_credit, category_name, category_slug,
        country_id, country_name, country_slug, destination_id, destination_name, destination_slug,
        tags, status, featured, author_name, source_url, source_name, seo_title, seo_description,
        published_at, created_at, updated_at FROM posts WHERE destination_id = ${cityId} AND status = 'published' AND published_at <= NOW()
      ORDER BY featured DESC, published_at DESC NULLS LAST, created_at DESC LIMIT ${limit} OFFSET ${offset}
    `;
  }
  if (topicSlug) {
    return db<PostSummary[]>`
      SELECT id, title, slug, excerpt,
        char_length(regexp_replace(content_html, '<[^>]+>', ' ', 'g'))::int AS content_length,
        cover_image, cover_alt, cover_credit, category_name, category_slug,
        country_id, country_name, country_slug, destination_id, destination_name, destination_slug,
        tags, status, featured, author_name, source_url, source_name, seo_title, seo_description,
        published_at, created_at, updated_at FROM posts WHERE country_id = ${countryId} AND category_slug = ${topicSlug}
        AND status = 'published' AND published_at <= NOW()
      ORDER BY featured DESC, published_at DESC NULLS LAST, created_at DESC LIMIT ${limit} OFFSET ${offset}
    `;
  }
  return db<PostSummary[]>`
    SELECT id, title, slug, excerpt,
        char_length(regexp_replace(content_html, '<[^>]+>', ' ', 'g'))::int AS content_length,
        cover_image, cover_alt, cover_credit, category_name, category_slug,
        country_id, country_name, country_slug, destination_id, destination_name, destination_slug,
        tags, status, featured, author_name, source_url, source_name, seo_title, seo_description,
        published_at, created_at, updated_at FROM posts WHERE country_id = ${countryId} AND status = 'published' AND published_at <= NOW()
    ORDER BY featured DESC, published_at DESC NULLS LAST, created_at DESC LIMIT ${limit} OFFSET ${offset}
  `;
}

export async function countPostsForLocation(countryId: string, cityId?: string, topicSlug?: string) {
  if (cityId && topicSlug) {
    const rows = await db<{ total: number }[]>`SELECT COUNT(*)::int AS total FROM posts WHERE destination_id = ${cityId} AND category_slug = ${topicSlug} AND status = 'published' AND published_at <= NOW()`;
    return rows[0]?.total ?? 0;
  }
  if (cityId) {
    const rows = await db<{ total: number }[]>`SELECT COUNT(*)::int AS total FROM posts WHERE destination_id = ${cityId} AND status = 'published' AND published_at <= NOW()`;
    return rows[0]?.total ?? 0;
  }
  if (topicSlug) {
    const rows = await db<{ total: number }[]>`SELECT COUNT(*)::int AS total FROM posts WHERE country_id = ${countryId} AND category_slug = ${topicSlug} AND status = 'published' AND published_at <= NOW()`;
    return rows[0]?.total ?? 0;
  }
  const rows = await db<{ total: number }[]>`SELECT COUNT(*)::int AS total FROM posts WHERE country_id = ${countryId} AND status = 'published' AND published_at <= NOW()`;
  return rows[0]?.total ?? 0;
}

export async function getDestinationSlugs() {
  // Keep empty starter destinations navigable internally, but don't put noindex pages in the XML sitemap.
  return db<{ slug: string; kind: DestinationKind; country_slug: string | null; updated_at: Date }[]>`
    SELECT d.slug, d.kind, p.slug AS country_slug, d.updated_at
    FROM destinations d
    LEFT JOIN destinations p ON p.id = d.parent_id
    WHERE EXISTS (
      SELECT 1 FROM posts a
      WHERE a.status = 'published' AND a.published_at <= NOW()
        AND (
          (d.kind = 'country' AND (a.country_id = d.id OR (a.country_id IS NULL AND lower(a.country_slug) = lower(d.slug))))
          OR (d.kind = 'city' AND (a.destination_id = d.id OR (a.destination_id IS NULL AND lower(a.destination_slug) = lower(d.slug))))
        )
    )
    ORDER BY d.kind, d.slug
  `;
}
