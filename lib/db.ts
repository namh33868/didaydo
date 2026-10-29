import postgres from "postgres";

const connectionString = process.env.DATABASE_URL;

if (!connectionString && process.env.NODE_ENV === "production") {
  console.warn("DATABASE_URL is not configured. Database-backed pages and APIs will fail until it is set.");
}

export const db = postgres(connectionString || "postgres://postgres:postgres@localhost:5432/diddaydo", {
  max: process.env.NODE_ENV === "development" ? 5 : 10,
  idle_timeout: 20,
  connect_timeout: 10,
  prepare: false,
});

export type PostRecord = {
  id: string;
  title: string;
  slug: string;
  excerpt: string;
  content_html: string;
  cover_image: string;
  cover_alt: string;
  cover_credit: string;
  category_name: string;
  category_slug: string;
  country_id: string | null;
  country_name: string;
  country_slug: string;
  destination_id: string | null;
  destination_name: string;
  destination_slug: string;
  created_by: string | null;
  updated_by: string | null;
  tags: string[];
  status: "draft" | "published" | "archived";
  featured: boolean;
  author_name: string;
  source_url: string | null;
  source_name: string;
  seo_title: string;
  seo_description: string;
  published_at: Date | null;
  created_at: Date;
  updated_at: Date;
};


/** Lightweight record for lists/cards; full HTML is fetched only for the article page. */
export type PostSummary = Omit<PostRecord, "content_html" | "created_by" | "updated_by"> & { content_length: number };
