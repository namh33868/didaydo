function escapeHtml(value: string) {
  return value.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

function inlineMarkdown(value: string) {
  let text = escapeHtml(value);
  text = text.replace(/!\[([^\]]*)\]\((https?:\/\/[^\s)]+)(?:\s+"([^"]*)")?\)/g, (_match, alt: string, url: string, title: string | undefined) => `<img src="${url}" alt="${alt}"${title ? ` title="${title}"` : ""} />`);
  text = text.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2">$1</a>');
  text = text.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>").replace(/__([^_]+)__/g, "<strong>$1</strong>");
  text = text.replace(/\*([^*]+)\*/g, "<em>$1</em>").replace(/_([^_]+)_/g, "<em>$1</em>").replace(/`([^`]+)`/g, "<code>$1</code>");
  return text;
}

/** Supports crawler payloads that provide plain text or Markdown instead of HTML. */
export function contentToHtml(value: string) {
  const source = value.trim();
  if (!source) return "";
  if (/<\/?(?:p|h[1-6]|ul|ol|li|blockquote|figure|img|table|div|article|section|a|strong|em)\b/i.test(source)) return source;

  const lines = source.replace(/\r\n?/g, "\n").split("\n");
  const output: string[] = [];
  let paragraph: string[] = [];
  let listType: "ul" | "ol" | null = null;
  let quote: string[] = [];

  const flushParagraph = () => {
    if (paragraph.length) output.push(`<p>${paragraph.map(inlineMarkdown).join(" ")}</p>`);
    paragraph = [];
  };
  const flushList = () => {
    if (listType) output.push(`</${listType}>`);
    listType = null;
  };
  const flushQuote = () => {
    if (quote.length) output.push(`<blockquote><p>${quote.map(inlineMarkdown).join(" ")}</p></blockquote>`);
    quote = [];
  };

  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (!line) { flushParagraph(); flushList(); flushQuote(); continue; }

    const heading = line.match(/^(#{1,6})\s+(.+)$/);
    if (heading) {
      flushParagraph(); flushList(); flushQuote();
      const level = heading[1].length <= 2 ? 2 : heading[1].length === 3 ? 3 : 4;
      output.push(`<h${level}>${inlineMarkdown(heading[2])}</h${level}>`);
      continue;
    }
    if (/^>\s?/.test(line)) {
      flushParagraph(); flushList();
      quote.push(line.replace(/^>\s?/, ""));
      continue;
    }
    const unordered = line.match(/^[-*+]\s+(.+)$/);
    const ordered = line.match(/^\d+[.)]\s+(.+)$/);
    if (unordered || ordered) {
      flushParagraph(); flushQuote();
      const nextType = unordered ? "ul" : "ol";
      if (listType !== nextType) { flushList(); output.push(`<${nextType}>`); listType = nextType; }
      output.push(`<li>${inlineMarkdown((unordered || ordered)![1])}</li>`);
      continue;
    }
    flushList(); flushQuote();
    paragraph.push(line);
  }
  flushParagraph(); flushList(); flushQuote();
  return output.join("\n");
}

function firstDefined(...values: unknown[]) {
  return values.find((value) => value !== undefined && value !== null && value !== "");
}

function normalizeOneArticle(value: unknown) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return value;
  const row = value as Record<string, unknown>;
  const rawTags = firstDefined(row.tags, row.keywords, row.labels);
  const tags = Array.isArray(rawTags) ? rawTags : typeof rawTags === "string" ? rawTags.split(/[;,]/).map((tag) => tag.trim()).filter(Boolean) : [];
  return {
    ...row,
    title: firstDefined(row.title, row.headline, row.name),
    slug: firstDefined(row.slug, row.urlSlug),
    excerpt: firstDefined(row.excerpt, row.summary, row.description, row.dek, row.intro),
    contentHtml: firstDefined(row.contentHtml, row.content_html, row.bodyHtml, row.html, row.content, row.body, row.markdown, row.contentMarkdown),
    coverImage: firstDefined(row.coverImage, row.cover_image, row.imageUrl, row.image_url, row.featuredImage, row.featured_image, row.heroImage, row.image),
    coverAlt: firstDefined(row.coverAlt, row.cover_alt, row.imageAlt, row.image_alt, row.alt),
    coverCredit: firstDefined(row.coverCredit, row.cover_credit, row.imageCredit, row.image_credit, row.photoCredit, row.photo_credit),
    country: firstDefined(row.country, row.countryName, row.country_name),
    destination: firstDefined(row.destination, row.destinationName, row.destination_name, row.city, row.cityName, row.city_name),
    category: firstDefined(row.category, row.categoryName, row.category_name, row.topic),
    tags,
    sourceUrl: firstDefined(row.sourceUrl, row.source_url, row.originalUrl, row.original_url, row.originUrl, row.url),
    sourceName: firstDefined(row.sourceName, row.source_name, row.publisher, row.source),
    authorName: firstDefined(row.authorName, row.author_name, row.author, row.byline),
    seoTitle: firstDefined(row.seoTitle, row.seo_title, row.metaTitle, row.meta_title),
    seoDescription: firstDefined(row.seoDescription, row.seo_description, row.metaDescription, row.meta_description),
    featured: firstDefined(row.featured, row.isFeatured, row.is_featured),
  };
}

export function normalizeIngestPayload(value: unknown) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return value;
  const row = value as Record<string, unknown>;
  if (Array.isArray(row.posts)) return { ...row, posts: row.posts.map(normalizeOneArticle) };
  if (row.post && typeof row.post === "object") return { ...row, post: normalizeOneArticle(row.post) };
  return normalizeOneArticle(value);
}
