"use client";

import { ResponsiveImage as Image } from "@/components/ResponsiveImage";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { ArrowRight, ChevronLeft, ChevronRight, Pause, Play } from "lucide-react";

type FeaturedSlide = {
  id: string;
  title: string;
  slug: string;
  excerpt: string;
  coverImage: string;
  coverAlt: string;
  categoryName: string;
  categorySlug: string;
  publishedAt: string | null;
  publishedAtLabel: string;
  minutes: number;
  manuallyFeatured: boolean;
};

export function FeaturedCarousel({ posts }: { posts: FeaturedSlide[] }) {
  const [activeIndex, setActiveIndex] = useState(0);
  const [paused, setPaused] = useState(false);
  const [hovered, setHovered] = useState(false);
  const touchStartX = useRef<number | null>(null);

  useEffect(() => {
    if (paused || hovered || posts.length < 2 || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const timer = window.setInterval(() => setActiveIndex((current) => (current + 1) % posts.length), 6500);
    return () => window.clearInterval(timer);
  }, [paused, hovered, posts.length]);

  if (!posts.length) return null;
  const slide = posts[Math.min(activeIndex, posts.length - 1)];
  const goTo = (index: number) => setActiveIndex((index + posts.length) % posts.length);

  return (
    <article
      className="hero-feature featured-carousel"
      aria-roledescription="carousel"
      aria-label="Tin nổi bật"
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      onFocus={() => setHovered(true)}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setHovered(false);
      }}
      onTouchStart={(event) => { touchStartX.current = event.changedTouches[0]?.clientX ?? null; }}
      onTouchEnd={(event) => {
        const start = touchStartX.current;
        const end = event.changedTouches[0]?.clientX;
        touchStartX.current = null;
        if (start === null || end === undefined || posts.length < 2) return;
        const distance = end - start;
        if (Math.abs(distance) >= 48) goTo(activeIndex + (distance < 0 ? 1 : -1));
      }}
    >
      {slide.coverImage ? (
        <Image
          key={slide.id}
          className="hero-feature-image featured-carousel-image"
          src={slide.coverImage}
          alt={slide.coverAlt || slide.title}
          fill
          priority={activeIndex === 0}
          sizes="(max-width: 800px) 100vw, 65vw"
        />
      ) : <div className="featured-carousel-image-placeholder" aria-hidden="true" />}

      <div className="hero-feature-content" key={`${slide.id}-content`}>
        <span className="hero-kicker">
          {slide.manuallyFeatured ? "Câu chuyện nổi bật" : "Mới đăng"}
          <span className="featured-carousel-kicker-count">{String(activeIndex + 1).padStart(2, "0")} / {String(posts.length).padStart(2, "0")}</span>
        </span>
        <h1><Link href={`/bai-viet/${slide.slug}`}>{slide.title}</Link></h1>
        {slide.excerpt && <p>{slide.excerpt}</p>}
        <div className="hero-meta">
          <Link href={`/chuyen-muc/${slide.categorySlug}`}>{slide.categoryName}</Link><span className="meta-dot" />
          <time dateTime={slide.publishedAt || undefined}>{slide.publishedAtLabel}</time><span className="meta-dot" />
          <span>{slide.minutes} phút đọc</span>
        </div>
        <div className="featured-carousel-actions">
          <Link href={`/bai-viet/${slide.slug}`} className="hero-text-link">Đọc câu chuyện <ArrowRight size={16} /></Link>
          <div className="featured-carousel-buttons" aria-label="Điều khiển tin nổi bật">
            <button type="button" onClick={() => goTo(activeIndex - 1)} aria-label="Tin nổi bật trước" disabled={posts.length < 2}><ChevronLeft size={17} /></button>
            <button type="button" onClick={() => goTo(activeIndex + 1)} aria-label="Tin nổi bật tiếp theo" disabled={posts.length < 2}><ChevronRight size={17} /></button>
            <button type="button" onClick={() => setPaused((value) => !value)} aria-label={paused ? "Tiếp tục tự chuyển slide" : "Tạm dừng tự chuyển slide"} title={paused ? "Tiếp tục" : "Tạm dừng"} disabled={posts.length < 2}>
              {paused ? <Play size={13} /> : <Pause size={13} />}
            </button>
          </div>
        </div>
        {posts.length > 1 && <div className="featured-carousel-dots" aria-label="Chọn tin nổi bật">
          {posts.map((post, index) => (
            <button
              key={post.id}
              type="button"
              className={index === activeIndex ? "is-active" : ""}
              onClick={() => goTo(index)}
              aria-label={`Hiển thị tin ${index + 1}: ${post.title}`}
              aria-current={index === activeIndex ? "true" : undefined}
            />
          ))}
        </div>}
      </div>
    </article>
  );
}
