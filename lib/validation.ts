import { z } from "zod";

export const postInputSchema = z.object({
  title: z.string().trim().min(3).max(220),
  slug: z.string().trim().max(150).optional().or(z.literal("")),
  excerpt: z.string().trim().max(500).optional().default(""),
  contentHtml: z.string().max(500_000).optional().default(""),
  coverImage: z.string().trim().max(2000).optional().default("").refine((value) => !value || /^https:\/\//i.test(value), "Ảnh đại diện phải là URL HTTPS."),
  coverAlt: z.string().trim().max(300).optional().default(""),
  coverCredit: z.string().trim().max(300).optional().default(""),
  country: z.string().trim().max(120).optional().default(""),
  destination: z.string().trim().max(120).optional().default(""),
  category: z.string().trim().max(100).optional().default("Cẩm nang"),
  tags: z.array(z.string().trim().min(1).max(80)).max(20).optional().default([]),
  status: z.enum(["draft", "published", "archived"]).optional(),
  featured: z.boolean().optional().default(false),
  authorName: z.string().trim().max(120).optional().default("Ban biên tập"),
  sourceUrl: z.string().trim().url().max(2000).optional().or(z.literal("")),
  sourceName: z.string().trim().max(200).optional().default(""),
  seoTitle: z.string().trim().max(220).optional().default(""),
  seoDescription: z.string().trim().max(320).optional().default(""),
});

export const ingestSchema = z.union([
  z.object({ posts: z.array(postInputSchema).min(1).max(100) }),
  z.object({ post: postInputSchema }),
  postInputSchema,
]);

export const adminPostSchema = postInputSchema.extend({
  id: z.string().uuid().optional(),
  status: z.enum(["draft", "published", "archived"]).default("draft"),
});

export type PostInput = z.infer<typeof postInputSchema>;
export type AdminPostInput = z.infer<typeof adminPostSchema>;
