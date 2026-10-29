import { ResponsiveImage as Image } from "@/components/ResponsiveImage";
import Link from "next/link";
import { ArrowUpRight, Clock3 } from "lucide-react";
import type { PostRecord, PostSummary } from "@/lib/db";
import { formatDate, readingMinutes, readingMinutesFromLength } from "@/lib/format";

export function PostCard({ post, variant = "default" }: { post: PostRecord | PostSummary; variant?: "default" | "compact" }) {
  return (
    <article className={`post-card ${variant === "compact" ? "post-card-compact" : ""}`}>
      <Link href={`/bai-viet/${post.slug}`} className="post-image-wrap" aria-label={post.title}>
        {post.cover_image ? <Image src={post.cover_image} alt={post.cover_alt || post.title} fill sizes={variant === "compact" ? "(max-width: 680px) 38vw, 180px" : "(max-width: 680px) 100vw, (max-width: 1000px) 50vw, 33vw"} className="post-image" /> : <div className="image-placeholder"><span>ĐI ĐÂY ĐÓ</span></div>}
        <span className="image-arrow"><ArrowUpRight size={18} /></span>
      </Link>
      <div className="post-card-body">
        <Link className="category-label" href={`/chuyen-muc/${post.category_slug}`}>{post.category_name}</Link>
        <h3><Link href={`/bai-viet/${post.slug}`}>{post.title}</Link></h3>
        {variant !== "compact" && <p className="post-excerpt">{post.excerpt || "Một câu chuyện và những gợi ý hữu ích cho hành trình tiếp theo của bạn."}</p>}
        <div className="post-meta"><time dateTime={post.published_at?.toISOString()}>{formatDate(post.published_at)}</time><span className="meta-dot" /><span><Clock3 size={13} /> {"content_length" in post ? readingMinutesFromLength(post.content_length) : readingMinutes(post.content_html)} phút đọc</span></div>
      </div>
    </article>
  );
}
