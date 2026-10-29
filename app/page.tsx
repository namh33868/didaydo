import { ResponsiveImage as Image } from "@/components/ResponsiveImage";
import Link from "next/link";
import { ArrowUpRight, Compass, MoveRight } from "lucide-react";
import { getFeaturedPosts, getRecentPosts } from "@/lib/posts";
import { getCountries } from "@/lib/taxonomy";
import { PostCard } from "@/components/PostCard";
import { FeaturedCarousel } from "@/components/FeaturedCarousel";
import { SectionHeading } from "@/components/SectionHeading";
import { formatDate, readingMinutesFromLength } from "@/lib/format";
import { absoluteUrl, siteName } from "@/lib/seo";

// Rebuild the public homepage at most once per minute; article ingestion is 10/day.
export const revalidate = 60;

const topics = [
  { title: "Cẩm nang", shortTitle: "Cẩm nang", subtitle: "Chuẩn bị hành trình tự tin hơn", href: "/chuyen-muc/cam-nang", image: "https://images.unsplash.com/photo-1473448912268-2022ce9509d8?auto=format&fit=crop&w=900&q=85", imageAlt: "Con đường đi bộ giữa rừng xanh" },
  { title: "Ẩm thực", shortTitle: "Ẩm thực", subtitle: "Đi qua mỗi nơi bằng hương vị", href: "/chuyen-muc/am-thuc", image: "https://images.unsplash.com/photo-1555939594-58d7cb561ad1?auto=format&fit=crop&w=900&q=85", imageAlt: "Các món ăn địa phương được bày trên bàn" },
  { title: "Hotel review", shortTitle: "Hotel review", subtitle: "Tìm nơi lưu trú phù hợp", href: "/chuyen-muc/hotel-review", image: "https://images.unsplash.com/photo-1571896349842-33c89424de2d?auto=format&fit=crop&w=900&q=85", imageAlt: "Khu nghỉ dưỡng với hồ bơi và cây xanh" },
  { title: "Check-in", shortTitle: "Check-in", subtitle: "Những góc đáng khám phá", href: "/chuyen-muc/check-in", image: "https://images.unsplash.com/photo-1518548419970-58e3b4079ab2?auto=format&fit=crop&w=900&q=85", imageAlt: "Khung cảnh du lịch nổi bật" },
];

export default async function HomePage() {
  const [featuredPosts, latest, countries] = await Promise.all([getFeaturedPosts(8), getRecentPosts(24), getCountries()]);
  const activeCountries = countries.filter((country) => country.post_count > 0);
  const featuredSlugs = new Set(featuredPosts.map((post) => post.slug));
  const nonFeatured = latest.filter((post) => !featuredSlugs.has(post.slug));
  // Keep the editorial hierarchy clean: featured stories appear in the carousel,
  // side stories show the newest non-featured posts, and the grid excludes both.
  const sidePosts = nonFeatured.slice(0, 3);
  const sideSlugs = new Set(sidePosts.map((post) => post.slug));
  const gridPosts = latest
    .filter((post) => !featuredSlugs.has(post.slug) && !sideSlugs.has(post.slug))
    .slice(0, 6);
  const jsonLd = {
    "@context": "https://schema.org",
    "@type": "WebSite",
    name: siteName,
    url: absoluteUrl("/"),
    description: "Tạp chí du lịch, điểm đến và kinh nghiệm cho những hành trình đáng nhớ.",
    inLanguage: "vi-VN",
    potentialAction: { "@type": "SearchAction", target: `${absoluteUrl("/tim-kiem")}?q={search_term_string}`, "query-input": "required name=search_term_string" },
  };

  return (
    <main className="home-page">
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd).replace(/</g, "\\u003c") }} />

      <section className="hero-section">
        <div className="container">
          <div className="hero-topline">
            <span className="eyebrow">CHUYỆN ĐI · CHUYỆN ĐẾN · CHUYỆN ĐỜI</span>
            <span className="issue-date">Tạp chí trực tuyến · Mỗi ngày một góc nhìn</span>
          </div>

          {featuredPosts.length > 0 ? (
            <div className="hero-grid">
              <FeaturedCarousel posts={featuredPosts.map((post) => ({
                id: post.id,
                title: post.title,
                slug: post.slug,
                excerpt: post.excerpt,
                coverImage: post.cover_image,
                coverAlt: post.cover_alt || post.title,
                categoryName: post.category_name,
                categorySlug: post.category_slug,
                publishedAt: post.published_at?.toISOString() || null,
                publishedAtLabel: formatDate(post.published_at),
                minutes: readingMinutesFromLength(post.content_length),
                manuallyFeatured: post.featured,
              }))} />
            </div>
          ) : (
            <div className="empty-content">
              <h2>Đi để hiểu hơn, trở về với nhiều câu chuyện hơn.</h2>
              <p>Website đã sẵn sàng. Bài viết sẽ tự hiển thị khi crawler/AI gửi dữ liệu vào API và xuất bản thành công.</p>
              <Link className="text-link" href="/dang-nhap">Mở trang quản trị <ArrowUpRight size={16} /></Link>
            </div>
          )}
        </div>
      </section>

      <section className="topic-strip" aria-label="Khám phá nhanh">
        <div className="container topic-strip-inner">
          <div className="topic-strip-heading">
            <span className="eyebrow">BẮT ĐẦU TỪ ĐÂU?</span>
            <p>Khám phá theo mối quan tâm</p>
          </div>
          <nav className="topic-chips" aria-label="Danh mục nổi bật">
            {topics.map((topic) => <Link className="topic-chip" href={topic.href} key={topic.href}>{topic.shortTitle}<ArrowUpRight size={14} /></Link>)}
          </nav>
        </div>
      </section>

      {sidePosts.length > 0 && <section className="section home-recent-section">
        <div className="container">
          <SectionHeading eyebrow="VỪA LÊN SÓNG" title="Những câu chuyện mới" href="/the-gioi" linkText="Xem tất cả tin mới" />
          <div className="recent-story-grid">
            {sidePosts.map((post, index) => (
              <article key={post.id} className="recent-story-card">
                <Link className="recent-story-image" href={`/bai-viet/${post.slug}`} aria-label={post.title}>
                  {post.cover_image && <Image src={post.cover_image} alt={post.cover_alt || post.title} fill sizes="(max-width: 700px) 38vw, 28vw" />}
                  <span className="recent-story-number">0{index + 1}</span>
                </Link>
                <div className="recent-story-copy">
                  <Link href={`/chuyen-muc/${post.category_slug}`} className="category-label">{post.category_name}</Link>
                  <h3><Link href={`/bai-viet/${post.slug}`}>{post.title}</Link></h3>
                  {post.excerpt && <p>{post.excerpt}</p>}
                  <time dateTime={post.published_at?.toISOString()}>{formatDate(post.published_at)}</time>
                </div>
              </article>
            ))}
          </div>
        </div>
      </section>}

      <section className="section home-latest-section">
        <div className="container">
          <SectionHeading eyebrow="TỪ NHỮNG HÀNH TRÌNH MỚI NHẤT" title="Chuyện mới kể" href="/the-gioi" linkText="Khám phá bài viết" />
          {gridPosts.length > 0 ? (
            <div className="post-grid">{gridPosts.map((post) => <PostCard key={post.id} post={post} />)}</div>
          ) : (
            <div className="empty-content"><h2>Mở đầu cho những câu chuyện mới</h2><p>Hãy kết nối API crawl + AI để đưa nội dung đầu tiên lên trang.</p></div>
          )}
        </div>
      </section>

      <section className="editorial-banner">
        <div className="container editorial-banner-inner">
          <div>
            <span className="eyebrow">KHÔNG CHỈ LÀ CHECK-IN</span>
            <h2>Mỗi nơi ta đến đều có một câu chuyện đáng để lắng nghe.</h2>
            <p>Gợi ý hành trình, góc nhìn bản địa và những trải nghiệm giúp bạn khám phá thế giới một cách gần gũi hơn.</p>
            <div className="editorial-banner-cta"><Link href="/gioi-thieu" className="hero-text-link">Tìm hiểu về chúng tôi <MoveRight size={16} /></Link></div>
          </div>
          <div className="banner-mark"><Compass size={33} /></div>
        </div>
      </section>

      {activeCountries.length > 0 && <section className="section home-country-section">
        <div className="container">
          <SectionHeading eyebrow="ĐI ĐÂU TIẾP THEO?" title="Bắt đầu từ điểm đến" href="/diem-den" linkText="Xem tất cả điểm đến" />
          <div className="home-country-grid">
            {activeCountries.slice(0, 4).map((country) => <Link href={`/diem-den/${country.slug}`} className="home-country-card" key={country.id}>
              <div className="home-country-image">{country.resolved_cover && <Image src={country.resolved_cover} alt={`Khám phá ${country.name}`} fill sizes="(max-width: 600px) 75vw, 25vw"/>}</div>
              <div className="home-country-copy"><h3>{country.name}</h3><span>{country.post_count} bài viết <ArrowUpRight size={13}/></span></div>
            </Link>)}
          </div>
        </div>
      </section>}

      <section className="section destination-section">
        <div className="container">
          <SectionHeading eyebrow="ĐI THEO CÁCH CỦA BẠN" title="Khám phá theo chủ đề" href="/chuyen-muc/cam-nang" linkText="Xem tất cả" />
          <div className="destination-grid">
            {topics.map((topic, index) => (
              <Link href={topic.href} className={`destination-card destination-card-${index + 1}`} key={topic.href}>
                <Image src={topic.image} alt={topic.imageAlt} fill sizes="(max-width: 520px) 48vw, (max-width: 900px) 48vw, 25vw" />
                <div className="destination-card-content"><span>{topic.subtitle}</span><h3>{topic.title}</h3><b>Khám phá <ArrowUpRight size={15} /></b></div>
              </Link>
            ))}
          </div>
        </div>
      </section>
    </main>
  );
}
