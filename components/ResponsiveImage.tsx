import Image, { type ImageProps } from "next/image";

type ResponsiveImageProps = Omit<ImageProps, "src" | "unoptimized"> & {
  src: string;
  /** Set this only for special cases; by default, optimize trusted image hosts. */
  unoptimized?: boolean;
};

const OPTIMIZABLE_REMOTE_HOSTS = new Set(["images.unsplash.com", "images.pexels.com"]);

function canOptimize(src: string) {
  // Local public assets can be optimized by Next.js (except SVG/GIF).
  if (src.startsWith("/")) {
    const pathname = src.split("?")[0].toLowerCase();
    return !pathname.endsWith(".svg") && !pathname.endsWith(".gif");
  }

  try {
    const url = new URL(src);
    return url.protocol === "https:" && OPTIMIZABLE_REMOTE_HOSTS.has(url.hostname)
      && !url.pathname.toLowerCase().endsWith(".svg")
      && !url.pathname.toLowerCase().endsWith(".gif");
  } catch {
    return false;
  }
}

/**
 * Uses Next.js image optimization for local, Unsplash, and Pexels images.
 * Unknown crawl source hosts stay unoptimized so existing article images do not break
 * because of Next.js remotePatterns restrictions. Add trusted hosts to both this set
 * and next.config.ts when the crawler's image sources are known.
 */
export function ResponsiveImage({ src, unoptimized, quality = 75, ...props }: ResponsiveImageProps) {
  return <Image {...props} src={src} quality={quality} unoptimized={unoptimized ?? !canOptimize(src)} />;
}
