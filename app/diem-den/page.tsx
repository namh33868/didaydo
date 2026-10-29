import type { Metadata } from "next";
import { ResponsiveImage as Image } from "@/components/ResponsiveImage";
import Link from "next/link";
import { ArrowUpRight, MapPin } from "lucide-react";
import { Breadcrumbs } from "@/components/Breadcrumbs";
import { getCountries } from "@/lib/taxonomy";
import { absoluteUrl, siteName } from "@/lib/seo";

// Public directory changes occasionally; cache it for five minutes.
export const revalidate = 300;

export async function generateMetadata(): Promise<Metadata> {
  const title = "Khám phá điểm đến";
  const description = "Khám phá quốc gia, thành phố và những câu chuyện du lịch theo từng điểm đến.";
  return { title, description, alternates: { canonical: absoluteUrl("/diem-den") }, openGraph: { type: "website", title: `${title} | ${siteName}`, description, url: absoluteUrl("/diem-den") } };
}

export default async function DestinationsPage() {
  const countries = await getCountries();
  const jsonLd = { "@context": "https://schema.org", "@type": "CollectionPage", name: "Khám phá điểm đến", description: "Quốc gia, thành phố và câu chuyện du lịch theo điểm đến.", url: absoluteUrl("/diem-den"), inLanguage: "vi-VN" };
  return <main className="destinations-page">
    <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd).replace(/</g, "\\u003c") }}/>
    <section className="page-intro destination-page-intro"><div className="container"><Breadcrumbs items={[{ label: "Trang chủ", href: "/" }, { label: "Điểm đến" }]}/><span className="eyebrow">MỞ BẢN ĐỒ, CHỌN HÀNH TRÌNH</span><h1>Thế giới rộng lớn.<br/>Bắt đầu từ nơi bạn muốn đến.</h1><p>Chọn quốc gia hoặc thành phố, sau đó khám phá bài viết theo cẩm nang, ẩm thực, check-in, khách sạn và kinh nghiệm thực tế.</p></div></section>
    <section className="section destination-directory"><div className="container"><div className="section-heading"><div><span className="eyebrow">DU LỊCH THEO QUỐC GIA</span><h2>Chọn điểm đến</h2></div><span className="directory-count">{countries.length} quốc gia</span></div>
      {countries.length ? <div className="country-grid">{countries.map((country) => <Link href={`/diem-den/${country.slug}`} className="country-card" key={country.id}>
        <div className="country-card-image">{country.resolved_cover ? <Image src={country.resolved_cover} alt={`Cảnh quan ${country.name}`} fill sizes="(max-width: 640px) 100vw, (max-width: 1000px) 50vw, 33vw"/> : <div className="country-card-placeholder"><MapPin size={28}/></div>}<span className="country-card-arrow"><ArrowUpRight size={18}/></span></div>
        <div className="country-card-copy"><span className="eyebrow">{country.post_count} BÀI VIẾT</span><h3>{country.name}</h3><p>{country.description || `Gợi ý thành phố, trải nghiệm và cẩm nang du lịch tại ${country.name}.`}</p><b>Khám phá quốc gia <ArrowUpRight size={14}/></b></div>
      </Link>)}</div> : <div className="empty-content"><h2>Danh sách điểm đến đang được xây dựng</h2><p>Danh mục điểm đến sẽ được mở rộng khi hệ thống crawl + AI hoặc biên tập viên bổ sung quốc gia mới.</p><Link className="text-link" href="/the-gioi">Khám phá theo quốc gia <ArrowUpRight size={15}/></Link></div>}
    </div></section>
  </main>;
}
