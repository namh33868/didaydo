export function formatDate(value: Date | string | null | undefined) {
  if (!value) return "Chưa xuất bản";
  const date = value instanceof Date ? value : new Date(value);
  return new Intl.DateTimeFormat("vi-VN", { day: "2-digit", month: "long", year: "numeric", timeZone: "Asia/Ho_Chi_Minh" }).format(date);
}

export function readingMinutes(html: string) {
  const text = html.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
  return Math.max(1, Math.ceil(text.split(" ").filter(Boolean).length / 220));
}

/** Estimate reading time from visible text character count returned by the list queries. */
export function readingMinutesFromLength(characterCount: number | null | undefined) {
  const estimatedWords = Math.ceil(Math.max(0, characterCount || 0) / 5.5);
  return Math.max(1, Math.ceil(estimatedWords / 220));
}

export function slugify(value: string) {
  return value
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/đ/g, "d").replace(/Đ/g, "D")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 120) || "bai-viet-moi";
}

export function stripHtml(html: string) {
  return html.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();
}
