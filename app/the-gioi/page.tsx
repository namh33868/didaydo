import type { Metadata } from "next";
import { ResponsiveImage as Image } from "@/components/ResponsiveImage";
import Link from "next/link";
import { ArrowRight, ArrowUpRight, BookOpen, Camera, Compass, Hotel, MapPin, Utensils } from "lucide-react";
import { Breadcrumbs } from "@/components/Breadcrumbs";
import { PostCard } from "@/components/PostCard";
import { getWorldPosts } from "@/lib/posts";
import { getCountries } from "@/lib/taxonomy";
import { EDITORIAL_CATEGORIES } from "@/lib/editorial-taxonomy";
import { absoluteUrl, siteName } from "@/lib/seo";

// Public directory changes occasionally; cache it for five minutes.
export const revalidate = 300;

export async function generateMetadata(): Promise<Metadata> {
  const title = "Thế giới: khám phá theo quốc gia";
  const description = "Chọn quốc gia rồi khám phá cẩm nang, ẩm thực, check-in, khách sạn và kinh nghiệm du lịch tại từng điểm đến.";
  return {
    title,
    description,
    alternates: { canonical: absoluteUrl("/the-gioi") },
    openGraph: { type: "website", title: `${title} | ${siteName}`, description, url: absoluteUrl("/the-gioi") },
  };
}

const featureTopics = [
  { slug: "cam-nang", name: "Cẩm nang", text: "Những điều nên biết trước khi đi", Icon: BookOpen },
  { slug: "am-thuc", name: "Ẩm thực", text: "Món ngon, quán địa phương và văn hóa ăn uống", Icon: Utensils },
  { slug: "hotel-review", name: "Hotel review", text: "Đánh giá khách sạn, resort và homestay", Icon: Hotel },
  { slug: "check-in", name: "Check-in", text: "Các địa điểm nổi bật và góc chụp đẹp", Icon: Camera },
];

export default async function WorldPage() {
  const [countries, worldPosts] = await Promise.all([getCountries(), getWorldPosts(6)]);
  const jsonLd = {
    "@context": "https://schema.org",
    "@type": "CollectionPage",
    name: "Thế giới: khám phá theo quốc gia",
    description: "Khám phá quốc gia, điểm đến và kinh nghiệm du lịch theo chủ đề.",
    url: absoluteUrl("/the-gioi"),
    inLanguage: "vi-VN",
    about: countries.map((country) => ({ "@type": "Country", name: country.name, url: absoluteUrl(`/diem-den/${country.slug}`) })),
  };

  return <main className="world-page">
    <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd).replace(/</g, "\\u003c") }}/>
    <section className="page-intro world-intro">
      <div className="container">
        <Breadcrumbs items={[{ label: "Trang chủ", href: "/" }, { label: "Thế giới" }]}/>
        <span className="eyebrow">KHÁM PHÁ THEO QUỐC GIA</span>
        <h1>Mỗi quốc gia, một cách nhìn thế giới.</h1>
        <p>Chọn đất nước bạn muốn khám phá, rồi tìm sâu hơn qua cẩm nang, ẩm thực, check-in, nơi lưu trú và những kinh nghiệm tại từng điểm đến.</p>
        <div className="world-intro-actions"><Link className="button-primary" href="/diem-den">Xem toàn bộ điểm đến <ArrowRight size={15}/></Link><span><MapPin size={15}/> Quốc gia → thành phố → chủ đề</span></div>
      </div>
    </section>

    <section className="section world-country-section">
      <div className="container">
        <div className="section-heading"><div><span className="eyebrow">CHỌN NƠI BẠN MUỐN ĐẾN</span><h2>Khám phá theo quốc gia</h2></div><span className="directory-count">{countries.length} quốc gia</span></div>
        {countries.length ? <div className="country-grid world-country-grid">
          {countries.map((country) => <Link href={`/diem-den/${country.slug}`} className="country-card" key={country.id}>
            <div className="country-card-image">{country.resolved_cover ? <Image src={country.resolved_cover} alt={`Cảnh quan ${country.name}`} fill sizes="(max-width: 640px) 100vw, (max-width: 1000px) 50vw, 33vw"/> : <div className="country-card-placeholder"><Compass size={28}/><span>Đang mở rộng cẩm nang</span></div>}<span className="country-card-arrow"><ArrowUpRight size={18}/></span></div>
            <div className="country-card-copy"><span className="eyebrow">{country.post_count ? `${country.post_count} BÀI VIẾT` : "ĐIỂM ĐẾN ĐANG ĐƯỢC BỔ SUNG"}</span><h3>{country.name}</h3><p>{country.description || `Cẩm nang, trải nghiệm và gợi ý khám phá ${country.name} theo cách riêng.`}</p><b>Khám phá {country.name} <ArrowUpRight size={14}/></b></div>
          </Link>)}
        </div> : <div className="empty-content"><h2>Danh sách quốc gia đang được xây dựng</h2><p>Khi crawler gửi bài kèm quốc gia hoặc biên tập viên thêm dữ liệu, quốc gia sẽ xuất hiện tại đây.</p></div>}
      </div>
    </section>

    <section className="section world-topics-section">
      <div className="container">
        <div className="section-heading"><div><span className="eyebrow">ĐI SÂU VÀO TỪNG TRẢI NGHIỆM</span><h2>Khám phá theo mối quan tâm</h2></div><Link className="text-link" href="/chuyen-muc/cam-nang">Tất cả chuyên mục <ArrowUpRight size={15}/></Link></div>
        <div className="world-topic-grid">{featureTopics.map(({ slug, name, text, Icon }) => <Link className="world-topic-card" key={slug} href={`/chuyen-muc/${slug}`}><span className="world-topic-icon"><Icon size={21}/></span><span className="world-topic-copy"><b>{name}</b><small>{text}</small></span><ArrowUpRight className="world-topic-arrow" size={16}/></Link>)}</div>
        <nav className="world-extra-topics" aria-label="Các chuyên mục du lịch khác">{EDITORIAL_CATEGORIES.filter((category) => !featureTopics.some((topic) => topic.slug === category.slug)).map((category) => <Link key={category.slug} href={`/chuyen-muc/${category.slug}`}>{category.name}<ArrowUpRight size={13}/></Link>)}</nav>
      </div>
    </section>

    {worldPosts.length > 0 && <section className="section world-latest-section"><div className="container"><div className="section-heading"><div><span className="eyebrow">NHỮNG CÂU CHUYỆN QUỐC TẾ</span><h2>Mới từ các điểm đến</h2></div></div><div className="post-grid">{worldPosts.map((post) => <PostCard key={post.id} post={post}/>)}</div></div></section>}
  </main>;
}
