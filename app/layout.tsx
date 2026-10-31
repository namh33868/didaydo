import type { Metadata, Viewport } from "next";
import "./globals.css";
import { Header } from "@/components/Header";
import { Footer } from "@/components/Footer";
import { defaultDescription, siteName, siteUrl } from "@/lib/seo";
import { AnalyticsConsent } from "@/components/AnalyticsConsent";

export const metadata: Metadata = {
  metadataBase: new URL(siteUrl),
  title: { default: `${siteName} — Tạp chí du lịch & đời sống`, template: `%s | ${siteName}` },
  description: defaultDescription,
  applicationName: siteName,\n  creator: siteName,\n  publisher: siteName,\n  other: { "dcterms.rights": "© " + new Date().getFullYear() + " " + siteName + ". Nội dung biên tập thuộc quyền của đơn vị xuất bản; tài sản bên thứ ba thuộc chủ sở hữu tương ứng.", "dcterms.rightsHolder": siteName },
  keywords: ["du lịch", "điểm đến", "kinh nghiệm du lịch", "ẩm thực", "du lịch Việt Nam"],
  openGraph: { type: "website", locale: "vi_VN", siteName, title: `${siteName} — Tạp chí du lịch & đời sống`, description: defaultDescription, url: siteUrl },
  twitter: { card: "summary_large_image", title: `${siteName} — Tạp chí du lịch & đời sống`, description: defaultDescription },
  robots: { index: true, follow: true, googleBot: { index: true, follow: true, "max-image-preview": "large", "max-snippet": -1, "max-video-preview": -1 } },
};

export const viewport: Viewport = { width: "device-width", initialScale: 1, themeColor: "#f7f7f2" };

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="vi"><body><Header />{children}<Footer /><AnalyticsConsent /></body></html>;
}
