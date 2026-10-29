import sanitizeHtml from "sanitize-html";

export function cleanArticleHtml(html: string) {
  return sanitizeHtml(html, {
    allowedTags: ["h2", "h3", "h4", "p", "br", "strong", "b", "em", "i", "u", "code", "pre", "ul", "ol", "li", "blockquote", "a", "figure", "figcaption", "img", "hr", "table", "thead", "tbody", "tr", "th", "td"],
    allowedAttributes: {
      a: ["href", "name", "target", "rel"],
      img: ["src", "alt", "title", "width", "height", "loading"],
      th: ["scope"],
    },
    allowedSchemes: ["http", "https", "mailto"],
    allowedSchemesByTag: { img: ["https"] },
    transformTags: {
      a: sanitizeHtml.simpleTransform("a", { rel: "noopener noreferrer", target: "_blank" }),
      img: sanitizeHtml.simpleTransform("img", { loading: "lazy" }),
    },
    disallowedTagsMode: "discard",
  });
}
