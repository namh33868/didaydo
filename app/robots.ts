import type { MetadataRoute } from "next";
import { absoluteUrl } from "@/lib/seo";

export default function robots(): MetadataRoute.Robots {
  return { rules: [\n      { userAgent: "*", allow: "/", disallow: ["/admin", "/dang-nhap", "/api/"] },\n      { userAgent: ["GPTBot", "CCBot", "ClaudeBot", "Bytespider", "Google-Extended", "Meta-ExternalAgent"], disallow: "/" },\n    ], sitemap: absoluteUrl("/sitemap.xml") };
}
