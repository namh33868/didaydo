import { getRecentPosts } from "@/lib/posts";
import { absoluteUrl, siteName } from "@/lib/seo";

export const dynamic = "force-dynamic";
function escapeXml(value: string) { return value.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&apos;"); }
export async function GET() {
  const posts = await getRecentPosts(50);
  const items = posts.map((post) => `<item><title>${escapeXml(post.title)}</title><link>${absoluteUrl(`/bai-viet/${post.slug}`)}</link><guid isPermaLink="true">${absoluteUrl(`/bai-viet/${post.slug}`)}</guid><description>${escapeXml(post.excerpt)}</description><pubDate>${(post.published_at || post.created_at).toUTCString()}</pubDate><category>${escapeXml(post.category_name)}</category>${post.cover_image ? `<enclosure url="${escapeXml(post.cover_image)}" type="image/jpeg" />` : ""}</item>`).join("");
  const xml = `<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>${escapeXml(siteName)} — Tạp chí du lịch</title><link>${absoluteUrl("/")}</link><description>Câu chuyện điểm đến, kinh nghiệm và cảm hứng du lịch.</description><language>vi-VN</language><lastBuildDate>${new Date().toUTCString()}</lastBuildDate>${items}</channel></rss>`;
  return new Response(xml, { headers: { "Content-Type": "application/rss+xml; charset=utf-8", "Cache-Control": "public, max-age=300, s-maxage=300" } });
}
