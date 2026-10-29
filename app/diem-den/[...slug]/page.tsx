import type { Metadata } from "next";
import { ResponsiveImage as Image } from "@/components/ResponsiveImage";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowUpRight, MapPin } from "lucide-react";
import { Breadcrumbs } from "@/components/Breadcrumbs";
import { PostCard } from "@/components/PostCard";
import { EDITORIAL_CATEGORIES } from "@/lib/editorial-taxonomy";
import { countPostsForLocation, getCitiesByCountry, getCityBySlug, getCountryBySlug, getPostsForLocation, getTopicsForLocation } from "@/lib/taxonomy";
import { absoluteUrl, siteName } from "@/lib/seo";

export const dynamic = "force-dynamic";
const configuredPageSize = Number(process.env.POSTS_PER_PAGE || 12);
const PAGE_SIZE = Number.isFinite(configuredPageSize) ? Math.min(48, Math.max(6, configuredPageSize)) : 12;
type Props = { params: Promise<{ slug: string[] }>; searchParams: Promise<{ page?: string; topic?: string }> };

export async function generateMetadata({ params, searchParams }: Props): Promise<Metadata> {
  const { slug } = await params;
  const sp = await searchParams;
  if (!slug.length || slug.length > 2) return { title: "Không tìm thấy điểm đến", robots: { index: false, follow: true } };
  const country = await getCountryBySlug(slug[0]);
  if (!country) return { title: "Không tìm thấy điểm đến", robots: { index: false, follow: true } };
  const city = slug.length === 2 ? await getCityBySlug(country.id, slug[1]) : null;
  if (slug.length === 2 && !city) return { title: "Không tìm thấy điểm đến", robots: { index: false, follow: true } };
  const name = city?.name || country.name;
  const title = `Du lịch ${name}: điểm đến, kinh nghiệm và câu chuyện`;
  const description = city?.description || country.description || `Khám phá bài viết, trải nghiệm và kinh nghiệm du lịch tại ${name}.`;
  const path = city ? `/diem-den/${country.slug}/${city.slug}` : `/diem-den/${country.slug}`;
  const hasFilter = Boolean(sp.topic || sp.page && sp.page !== "1");
  const emptyLocation = Number(city?.post_count ?? country.post_count) === 0;
  return { title, description, alternates: { canonical: absoluteUrl(path) }, robots: hasFilter || emptyLocation ? { index: false, follow: true } : { index: true, follow: true }, openGraph: { type: "website", title: `${title} | ${siteName}`, description, url: absoluteUrl(path), images: (city?.resolved_cover || country.resolved_cover) ? [city?.resolved_cover || country.resolved_cover] : undefined } };
}

export default async function DestinationDetailPage({ params, searchParams }: Props) {
  const { slug } = await params;
  const sp = await searchParams;
  if (!slug.length || slug.length > 2) notFound();
  const country = await getCountryBySlug(slug[0]);
  if (!country) notFound();
  const isCity = slug.length === 2;
  const city = isCity ? await getCityBySlug(country.id, slug[1]) : null;
  if (isCity && !city) notFound();

  const page = Math.max(1, Number(sp.page || 1) || 1);
  const topicCounts = await getTopicsForLocation(country.id, city?.id);
  const requestedTopic = sp.topic || "";
  // Keep every canonical editorial topic available for each country/city, even before it has posts.
  const activeTopic = EDITORIAL_CATEGORIES.some((topic) => topic.slug === requestedTopic) ? requestedTopic : undefined;
  const [posts, total, cities] = await Promise.all([
    getPostsForLocation(country.id, city?.id, activeTopic, PAGE_SIZE, (page - 1) * PAGE_SIZE),
    countPostsForLocation(country.id, city?.id, activeTopic),
    city ? Promise.resolve([]) : getCitiesByCountry(country.id),
  ]);
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const name = city?.name || country.name;
  const path = city ? `/diem-den/${country.slug}/${city.slug}` : `/diem-den/${country.slug}`;
  const activeTopicName = EDITORIAL_CATEGORIES.find((topic) => topic.slug === activeTopic)?.name;
  const topicCountBySlug = new Map<string, number>(topicCounts.map((topic): [string, number] => [topic.category_slug, topic.total]));
  const breadcrumbItems = [
    { label: "Trang chủ", href: "/" },
    { label: "Điểm đến", href: "/diem-den" },
    { label: country.name, href: `/diem-den/${country.slug}` },
    ...(city ? [{ label: city.name }] : []),
  ];
  const jsonLd = { "@context": "https://schema.org", "@type": "CollectionPage", name: `Du lịch ${name}`, description: city?.description || country.description || `Câu chuyện và kinh nghiệm du lịch tại ${name}.`, url: absoluteUrl(path), inLanguage: "vi-VN", about: { "@type": city ? "City" : "Country", name } };

  return <main className="destination-detail-page">
    <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd).replace(/</g, "\\u003c") }}/>
    <section className="destination-detail-hero"><div className="container"><Breadcrumbs items={breadcrumbItems}/><div className="destination-detail-grid"><div className="destination-detail-copy"><span className="eyebrow"><MapPin size={12}/> CẨM NANG ĐIỂM ĐẾN</span><h1>{name}</h1><p>{city?.description || country.description || `Những câu chuyện, trải nghiệm và kinh nghiệm hữu ích giúp bạn khám phá ${name} theo cách riêng.`}</p><div className="destination-detail-stats"><span><b>{total}</b> bài viết{activeTopicName ? ` · ${activeTopicName}` : ""}</span>{!city && <span><b>{cities.length}</b> thành phố / điểm đến</span>}</div></div>
        {(city?.resolved_cover || country.resolved_cover) && <div className="destination-detail-image"><Image src={city?.resolved_cover || country.resolved_cover} alt={`Cảnh quan ${name}`} fill priority sizes="(max-width: 800px) 100vw, 40vw"/></div>}
      </div></div></section>

    {!city && cities.length > 0 && <section className="section city-directory-section"><div className="container"><div className="section-heading"><div><span className="eyebrow">ĐIỂM DỪNG CHÂN TIẾP THEO</span><h2>Khám phá thành phố</h2></div><span className="directory-count">{cities.length} điểm đến</span></div><div className="city-chips">{cities.map((item) => <Link href={`/diem-den/${country.slug}/${item.slug}`} key={item.id} className="city-chip">{item.name}<span>{item.post_count} bài</span><ArrowUpRight size={14}/></Link>)}</div></div></section>}

    <section className="section location-stories-section"><div className="container"><div className="location-topics"><div><span className="eyebrow">TÌM THEO MỐI QUAN TÂM</span><h2>Khám phá {city ? city.name : country.name} qua từng chủ đề</h2></div><div className="location-topic-links"><Link className={!activeTopic ? "is-active" : ""} href={path}>Tất cả</Link>{EDITORIAL_CATEGORIES.map((topic) => <Link key={topic.slug} className={activeTopic === topic.slug ? "is-active" : ""} href={`${path}?topic=${encodeURIComponent(topic.slug)}`}>{topic.name}<span>{topicCountBySlug.get(topic.slug) || 0}</span></Link>)}</div></div>
      <div className="section-heading"><div><span className="eyebrow">{total} BÀI VIẾT</span><h2>{activeTopicName ? `${activeTopicName} tại ${name}` : "Những câu chuyện mới nhất"}</h2></div><Link className="text-link" href="/diem-den">Tất cả điểm đến <ArrowUpRight size={15}/></Link></div>
      {posts.length ? <div className="post-grid">{posts.map((post) => <PostCard post={post} key={post.id}/>)}</div> : <div className="empty-content"><h2>Chưa có bài viết phù hợp</h2><p>Khi crawler gắn quốc gia, điểm đến và chủ đề vào bài viết, nội dung sẽ tự động xuất hiện tại đây.</p><Link className="text-link" href={path}>Xóa bộ lọc <ArrowUpRight size={15}/></Link></div>}
      {totalPages > 1 && <nav className="pagination" aria-label="Phân trang">{page > 1 && <Link href={`${path}?${activeTopic ? `topic=${encodeURIComponent(activeTopic)}&` : ""}page=${page - 1}`}>←</Link>}{Array.from({ length: totalPages }, (_, i) => i + 1).slice(Math.max(0, page - 3), Math.min(totalPages, page + 2)).map((number) => number === page ? <span key={number} className="current" aria-current="page">{number}</span> : <Link key={number} href={`${path}?${activeTopic ? `topic=${encodeURIComponent(activeTopic)}&` : ""}page=${number}`}>{number}</Link>)}{page < totalPages && <Link href={`${path}?${activeTopic ? `topic=${encodeURIComponent(activeTopic)}&` : ""}page=${page + 1}`}>→</Link>}</nav>}
    </div></section>
  </main>;
}
