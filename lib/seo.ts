export const siteUrl = (process.env.NEXT_PUBLIC_SITE_URL || "http://localhost:3000").replace(/\/$/, "");
export const siteName = process.env.NEXT_PUBLIC_SITE_NAME || "Đi Đây Đó";
export const defaultDescription = "Câu chuyện điểm đến, kinh nghiệm hữu ích và cảm hứng cho những hành trình đáng nhớ.";

export function absoluteUrl(path = "") {
  return `${siteUrl}${path.startsWith("/") ? path : `/${path}`}`;
}
