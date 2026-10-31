import type { Metadata } from "next";
import { ResponsiveImage as Image } from "@/components/ResponsiveImage";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowUpRight, Clock3, MapPin } from "lucide-react";
import { Breadcrumbs } from "@/components/Breadcrumbs";
import { PostCard } from "@/components/PostCard";
import { getPostBySlug, getRelatedPosts } from "@/lib/posts";
import { formatDate, readingMinutes, slugify } from "@/lib/format";
import { absoluteUrl, siteName } from "@/lib/seo";

// Cache article HTML after its first request; refresh periodically for manual edits.
export const revalidate = 60;

// Generate dynamic article URLs on demand rather than querying every article during build.
export async function generateStaticParams() {
  return [];
}

type Props = { params: Promise<{ slug: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug } = await params;
  const post = await getPostBySlug(slug);
  if (!post) return { title: "Không tìm thấy bài viết", robots: { index: false, follow: true } };
  const title = post.seo_title || post.title;
  const description = post.seo_description || post.excerpt || `Đọc câu chuyện du lịch ${post.title} trên ${siteName}.`;
  const url = absoluteUrl(`/bai-viet/${post.slug}`);
  return {
    title,
    description,
    alternates: { canonical: url },
    openGraph: {
      type: "article", title, description, url,
      publishedTime: post.published_at?.toISOString(), modifiedTime: post.updated_at.toISOString(),
      authors: [post.author_name],
      images: post.cover_image ? [{ url: post.cover_image, alt: post.cover_alt || post.title }] : undefined,
      tags: post.tags,
    },
    twitter: { card: post.cover_image ? "summary_large_image" : "summary", title, description, images: post.cover_image ? [post.cover_image] : undefined },
  };
}

function makeArticleBody(html: string) {
  const toc: { title: string; id: string; level: number }[] = [];
  const counts = new Map<string, number>();
  const content = html.replace(/<(h2|h3)([^>]*)>([\s\S]*?)<\/\1>/gi, (full, tag: string, attrs: string, inner: string) => {
    const title = inner.replace(/<[^>]*>/g, "").trim();
    let id = slugify(title);
    const count = counts.get(id) || 0;
    counts.set(id, count + 1);
    if (count > 0) id = `${id}-${count + 1}`;
    toc.push({ title, id, level: tag.toLowerCase() === "h3" ? 3 : 2 });
    const cleanAttrs = attrs.replace(/\s+id=("|')[^"']*\1/gi, "");
    return `<${tag}${cleanAttrs} id="${id}">${inner}</${tag}>`;
  });
  return { content, toc };
}

function locationHref(countrySlug: string, destinationSlug?: string) {
  return destinationSlug ? `/diem-den/${countrySlug}/${destinationSlug}` : `/diem-den/${countrySlug}`;
}

export default async function ArticlePage({ params }: Props) {
  const { slug } = await params;
  const post = await getPostBySlug(slug);
  if (!post) notFound();
  const related = await getRelatedPosts(post, 6);
  const articleUrl = absoluteUrl(`/bai-viet/${post.slug}`);
  const description = post.seo_description || post.excerpt;
  const articleJsonLd = {
    "@context": "https://schema.org", "@type": "NewsArticle",
    headline: post.title, alternativeHeadline: post.seo_title || undefined,
    description, image: post.cover_image ? [post.cover_image] : undefined,
    datePublished: post.published_at?.toISOString(), dateModified: post.updated_at.toISOString(),
    author: { "@type": "Organization", name: post.author_name || "Ban biên tập" },
    publisher: { "@type": "Organization", name: siteName, url: absoluteUrl("/") },
    mainEntityOfPage: articleUrl, inLanguage: "vi-VN", articleSection: post.category_name,
    keywords: post.tags.join(", "), isAccessibleForFree: true,
  };
  const breadcrumbItems: { label: string; href?: string }[] = [
    { label: "Trang chủ", href: "/" },
    ...(post.country_name && post.country_slug ? [{ label: post.country_name, href: locationHref(post.country_slug) }] : []),
    ...(post.destination_name && post.country_slug && post.destination_slug ? [{ label: post.destination_name, href: locationHref(post.country_slug, post.destination_slug) }] : []),
    { label: post.title },
  ];
  const breadcrumbJsonLd = {
    "@context": "https://schema.org", "@type": "BreadcrumbList",
    itemListElement: breadcrumbItems.map((item, index) => ({
      "@type": "ListItem", position: index + 1, name: item.label,
      item: absoluteUrl(item.href || `/bai-viet/${post.slug}`),
    })),
  };
  const article = makeArticleBody(post.content_html || (post.excerpt ? `<p>${post.excerpt}</p>` : ""));
  const relatedByPlace = related.filter((item) => post.destination_id && item.destination_id === post.destination_id);
  const relatedPosts = [...relatedByPlace, ...related.filter((item) => !relatedByPlace.some((placeItem) => placeItem.id === item.id))].slice(0, 3);

  return (
    <main className="article-page">
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(articleJsonLd).replace(/</g, "\\u003c") }} />
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(breadcrumbJsonLd).replace(/</g, "\\u003c") }} />

      <div className="container article-breadcrumb-wrap"><Breadcrumbs items={breadcrumbItems} /></div>
      <div className="container article-layout">
        <article className="article-main">
          <header className="article-header">
            <div className="article-taxonomy">
              <Link className="category-label" href={`/chuyen-muc/${post.category_slug}`}>{post.category_name}</Link>
              {(post.country_name && post.country_slug) && <span className="article-place"><MapPin size={13}/><Link href={locationHref(post.country_slug)}>{post.country_name}</Link>{post.destination_name && post.destination_slug && <><span className="place-separator">/</span><Link href={locationHref(post.country_slug, post.destination_slug)}>{post.destination_name}</Link></>}</span>}
            </div>
            <h1>{post.title}</h1>
            {post.excerpt && <p className="article-deck">{post.excerpt}</p>}
            <div className="article-byline">
              <div className="author-avatar">ĐĐ</div>
              <div className="byline-copy"><b>{post.author_name || "Ban biên tập"}</b><span>Đăng ngày {formatDate(post.published_at)}{post.updated_at && ` · Cập nhật ${formatDate(post.updated_at)}`}</span></div>
              <span className="readtime"><Clock3 size={14}/>{readingMinutes(post.content_html)} phút đọc</span>
            </div>
          </header>

          {post.cover_image && <figure className="article-cover">
            <div className="article-cover-image"><Image src={post.cover_image} alt={post.cover_alt || post.title} fill priority sizes="(max-width: 800px) 100vw, 800px" /></div>
          </figure>}

          {article.toc.length > 1 && <nav className="article-toc-mobile" aria-label="Mục lục bài viết"><b>Trong bài viết này</b><ul>{article.toc.map((item) => <li key={item.id} className={item.level === 3 ? "toc-level-3" : ""}><a href={`#${item.id}`}>{item.title}</a></li>)}</ul></nav>}

          <div className="article-reading-layout">
            <div className="article-content-column">
              <div className="article-body" dangerouslySetInnerHTML={{ __html: article.content }} />
              {post.tags.length > 0 && <div className="article-tags"><b>Từ khóa</b>{post.tags.map((tag) => <Link key={tag} href={`/tim-kiem?q=${encodeURIComponent(tag)}`}>{tag}</Link>)}</div>}
              {post.source_url && <div className="article-source"><b>Nguồn tham khảo</b><p>{post.source_name ? `${post.source_name} · ` : ""}<a href={post.source_url} rel="noopener noreferrer nofollow" target="_blank">Xem nguồn gốc <ArrowUpRight size={12}/></a></p><small>Nội dung được biên tập và trình bày lại. Hãy đối chiếu nguồn chính thức khi cần thông tin du lịch cập nhật.</small></div>}
            </div>
          </div>
        </article>

        <aside className="article-sidebar">
          {article.toc.length > 1 && <div className="sidebar-block"><h2>Trong bài viết</h2><ul className="toc-list">{article.toc.map((item) => <li key={item.id} style={{ paddingLeft: item.level === 3 ? 12 : 0 }}><a href={`#${item.id}`}>{item.title}</a></li>)}</ul></div>}
          <div className="sidebar-block"><h2>Bài viết cùng chủ đề</h2>{related.slice(0, 3).map((item) => <PostCard key={item.id} post={item} variant="compact" />)}</div>
          <div className="sidebar-block"><h2>Khám phá tiếp</h2><p className="article-sidebar-note">Đi sâu hơn vào điểm đến hoặc tìm thêm những câu chuyện cùng mối quan tâm.</p>{post.country_name && post.country_slug && <Link href={locationHref(post.country_slug)} className="sidebar-category">{post.country_name}<span>↗</span></Link>}<Link href={`/chuyen-muc/${post.category_slug}`} className="sidebar-category">{post.category_name}<span>↗</span></Link></div>
        </aside>
      </div>

      {relatedPosts.length > 0 && <section className="section related-section"><div className="container"><div className="section-heading"><div><span className="eyebrow">ĐỌC TIẾP</span><h2>Có thể bạn cũng thích</h2></div><Link className="text-link" href={post.destination_slug && post.country_slug ? locationHref(post.country_slug, post.destination_slug) : `/chuyen-muc/${post.category_slug}`}>Khám phá thêm <ArrowUpRight size={15}/></Link></div><div className="post-grid">{relatedPosts.map((item) => <PostCard key={item.id} post={item}/>)}</div></div></section>}
    </main>
  );
}
