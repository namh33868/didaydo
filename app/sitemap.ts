import type { MetadataRoute } from "next";
import { getPublishedSlugs, getCategorySlugs } from "@/lib/posts";
import { getDestinationSlugs } from "@/lib/taxonomy";
import { absoluteUrl } from "@/lib/seo";
import { EDITORIAL_CATEGORIES } from "@/lib/editorial-taxonomy";

export const dynamic = "force-dynamic";
export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const [posts, categories, destinations] = await Promise.all([getPublishedSlugs(), getCategorySlugs(), getDestinationSlugs()]);
  const now = new Date();
  const staticRoutes = ["", "/the-gioi", "/diem-den", "/gioi-thieu", "/lien-he", "/chinh-sach-bao-mat"];
  const canonicalSlugs = new Set(EDITORIAL_CATEGORIES.map((category) => category.slug));
  const categorySlugs = [...new Set(categories.map((cat) => cat.category_slug))].filter((slug) => canonicalSlugs.has(slug));
  const destinationRoutes = destinations.flatMap((item) => {
    if (item.kind === "country") return [{ url: absoluteUrl(`/diem-den/${item.slug}`), lastModified: item.updated_at, changeFrequency: "daily" as const, priority: 0.65 }];
    if (!item.country_slug) return [];
    return [{ url: absoluteUrl(`/diem-den/${item.country_slug}/${item.slug}`), lastModified: item.updated_at, changeFrequency: "daily" as const, priority: 0.6 }];
  });
  return [
    ...staticRoutes.map((route) => ({ url: absoluteUrl(route || "/"), lastModified: now, changeFrequency: route === "" ? "daily" as const : "monthly" as const, priority: route === "" ? 1 : route === "/diem-den" ? 0.8 : 0.45 })),
    ...categorySlugs.map((slug) => ({ url: absoluteUrl(`/chuyen-muc/${slug}`), lastModified: now, changeFrequency: "daily" as const, priority: 0.7 })),
    ...destinationRoutes,
    ...posts.map((post) => ({ url: absoluteUrl(`/bai-viet/${post.slug}`), lastModified: post.updated_at, changeFrequency: "weekly" as const, priority: 0.8 })),
  ];
}
