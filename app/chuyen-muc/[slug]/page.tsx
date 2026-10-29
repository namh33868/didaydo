import type { Metadata } from "next";
import Link from "next/link";
import { notFound, redirect } from "next/navigation";
import { ArrowRight, ArrowUpRight } from "lucide-react";
import { Breadcrumbs } from "@/components/Breadcrumbs";
import { PostCard } from "@/components/PostCard";
import { SectionHeading } from "@/components/SectionHeading";
import { getCategorySlugs, getPostsByCategory, getRecentPosts } from "@/lib/posts";
import { EDITORIAL_CATEGORIES } from "@/lib/editorial-taxonomy";
import { absoluteUrl, siteName } from "@/lib/seo";

export const dynamic = "force-dynamic";
const configuredPageSize = Number(process.env.POSTS_PER_PAGE || 12);
const PAGE_SIZE = Number.isFinite(configuredPageSize) ? Math.min(48, Math.max(6, configuredPageSize)) : 12;
type Props = { params: Promise<{ slug: string }>; searchParams: Promise<{ page?: string }> };

export async function generateMetadata({ params, searchParams }: Props): Promise<Metadata> {
  const { slug } = await params;
  const sp = await searchParams;
  if (slug === "the-gioi") return { title: "Thế giới: khám phá theo quốc gia", alternates: { canonical: absoluteUrl("/the-gioi") } };
  if (slug === "diem-den-viet-nam") return { title: "Du lịch Việt Nam", alternates: { canonical: absoluteUrl("/diem-den/viet-nam") } };
  const category = EDITORIAL_CATEGORIES.find((item) => item.slug === slug);
  if (!category) return { title: "Không tìm thấy chuyên mục", robots: { index: false, follow: true } };
  const counts = await getCategorySlugs();
  const count = counts.find((item) => item.category_slug === slug)?.total || 0;
  const page = Math.max(1, Number(sp.page || 1) || 1);
  const title = category.name;
  const description = category.description;
  const canonicalPath = page > 1 ? `/chuyen-muc/${slug}?page=${page}` : `/chuyen-muc/${slug}`;
  return {
    title,
    description,
    alternates: { canonical: absoluteUrl(canonicalPath) },
    robots: count > 0 ? { index: true, follow: true } : { index: false, follow: true },
    openGraph: { type: "website", title: `${title} | ${siteName}`, description, url: absoluteUrl(canonicalPath) },
  };
}

export default async function CategoryPage({ params, searchParams }: Props) {
  const { slug } = await params;
  const sp = await searchParams;
  if (slug === "the-gioi") redirect("/the-gioi");
  if (slug === "diem-den-viet-nam") redirect("/diem-den/viet-nam");

  const category = EDITORIAL_CATEGORIES.find((item) => item.slug === slug);
  if (!category) notFound();
  const page = Math.max(1, Number(sp.page || 1) || 1);
  const [posts, categoryCounts, recent] = await Promise.all([
    getPostsByCategory(slug, PAGE_SIZE, (page - 1) * PAGE_SIZE),
    getCategorySlugs(),
    getRecentPosts(4),
  ]);
  const total = categoryCounts.find((item) => item.category_slug === slug)?.total || 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const canonicalPath = `/chuyen-muc/${slug}`;
  const jsonLd = { "@context": "https://schema.org", "@type": "CollectionPage", name: category.name, description: category.description, url: absoluteUrl(canonicalPath), inLanguage: "vi-VN" };

  return <main className="category-page">
    <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd).replace(/</g, "\\u003c") }}/>
    <section className="page-intro category-page-intro"><div className="container">
      <Breadcrumbs items={[{ label: "Trang chủ", href: "/" }, { label: "Chuyên mục", href: "/chuyen-muc/cam-nang" }, { label: category.name }]}/>
      <span className="eyebrow">KHÁM PHÁ THEO MỐI QUAN TÂM</span><h1>{category.name}</h1><p>{category.description}</p>
    </div></section>
    <section className="category-topic-directory"><div className="container"><div className="category-topic-heading"><span className="eyebrow">CÁC CHỦ ĐỀ DU LỊCH</span><span>Chọn mối quan tâm để tìm bài phù hợp</span></div><nav className="category-topic-links" aria-label="Danh mục du lịch">{EDITORIAL_CATEGORIES.map((item) => <Link key={item.slug} href={`/chuyen-muc/${item.slug}`} className={item.slug === slug ? "is-active" : ""} aria-current={item.slug === slug ? "page" : undefined}>{item.name}<ArrowUpRight size={13}/></Link>)}</nav></div></section>
    <div className="container listing-layout category-listing-layout"><div>
      <SectionHeading eyebrow={`${total} BÀI VIẾT`} title={total ? `Mới nhất: ${category.name}` : `Nội dung thuộc ${category.name}`} />
      {posts.length ? <div className="post-grid">{posts.map((post) => <PostCard key={post.id} post={post}/>)}</div> : <div className="empty-content"><h2>Chuyên mục đang được cập nhật</h2><p>{category.name} sẽ tập hợp những nội dung về {category.description.toLocaleLowerCase("vi-VN")} Bài viết sẽ tự xuất hiện ở đây sau khi được xuất bản và gắn đúng chủ đề.</p><Link href="/the-gioi" className="text-link">Khám phá theo quốc gia <ArrowRight size={15}/></Link></div>}
      {totalPages > 1 && <nav className="pagination" aria-label="Phân trang">{page > 1 && <Link href={`${canonicalPath}?page=${page - 1}`}>←</Link>}{Array.from({ length: totalPages }, (_, i) => i + 1).slice(Math.max(0, page - 3), Math.min(totalPages, page + 2)).map((n) => n === page ? <span key={n} className="current" aria-current="page">{n}</span> : <Link key={n} href={`${canonicalPath}?page=${n}`}>{n}</Link>)}{page < totalPages && <Link href={`${canonicalPath}?page=${page + 1}`}>→</Link>}</nav>}
    </div><aside className="listing-sidebar"><div className="sidebar-block"><h2>Khám phá nhanh</h2><Link className="sidebar-category" href="/the-gioi">Thế giới & quốc gia <span>↗</span></Link><Link className="sidebar-category" href="/diem-den">Tất cả điểm đến <span>↗</span></Link>{EDITORIAL_CATEGORIES.slice(0, 6).map((item) => <Link className="sidebar-category" href={`/chuyen-muc/${item.slug}`} key={item.slug}>{item.name}<span>↗</span></Link>)}</div><div className="sidebar-block"><h2>Đọc thêm</h2>{recent.slice(0, 3).map((post) => <PostCard key={post.id} post={post} variant="compact"/>)}</div></aside></div>
  </main>;
}
