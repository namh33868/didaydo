"use client";

import { useCallback, useEffect, useState } from "react";
import { ArticleContentEditor } from "@/components/ArticleContentEditor";
import { Archive, Check, ChevronDown, CirclePlus, ExternalLink, Eye, LogOut, Pencil, RefreshCw, Save, Search, Send, ShieldAlert, ShieldCheck, Star, Trash2, X } from "lucide-react";
import { EDITORIAL_CATEGORIES, normalizeEditorialCategory } from "@/lib/editorial-taxonomy";

type AdminPost = {
  id: string; title: string; slug: string; excerpt: string; contentHtml: string; coverImage: string; coverAlt: string;
  category: string; country: string; destination: string; coverCredit: string; tags: string[]; status: "draft" | "published" | "archived"; featured: boolean; authorName: string;
  sourceUrl: string; sourceName: string; seoTitle: string; seoDescription: string; publishedAt: string | null; createdAt: string;
};
type IngestLog = { id: string; source: string; received_count: number; created_count: number; updated_count: number; failed_count: number; status: string; createdAt: string };
type AdminRole = "admin" | "editor" | "author" | "viewer";
type SessionInfo = { email: string; fullName: string; role: AdminRole; userId: string | null };
const roleLabel: Record<AdminRole, string> = { admin: "Quản trị viên", editor: "Biên tập viên", author: "Tác giả", viewer: "Chỉ xem" };

type Editor = Omit<AdminPost, "id" | "publishedAt" | "createdAt"> & { id?: string }
type PreviewPost = Editor & { publishedAt?: string | null; createdAt?: string };
const siteName = process.env.NEXT_PUBLIC_SITE_NAME || "Đi Đây Đó";
const emptyEditor: Editor = { title: "", slug: "", excerpt: "", contentHtml: "", coverImage: "", coverAlt: "", category: "Cẩm nang", country: "", destination: "", coverCredit: "", tags: [], status: "draft", featured: false, authorName: "Ban biên tập", sourceUrl: "", sourceName: "", seoTitle: "", seoDescription: "" };

function editorFromPost(post: AdminPost): Editor {
  return { id: post.id, title: post.title, slug: post.slug, excerpt: post.excerpt, contentHtml: post.contentHtml, coverImage: post.coverImage, coverAlt: post.coverAlt, coverCredit: post.coverCredit || "", category: normalizeEditorialCategory(post.category).name, country: post.country || "", destination: post.destination || "", tags: post.tags || [], status: post.status, featured: post.featured, authorName: post.authorName, sourceUrl: post.sourceUrl || "", sourceName: post.sourceName, seoTitle: post.seoTitle, seoDescription: post.seoDescription };
}

// Browser-side allowlist for the preview. This protects the unsaved editor HTML
// before rendering it with dangerouslySetInnerHTML; persisted HTML is also
// sanitized by the API when saved.
function sanitizePreviewHtml(input: string) {
  if (!input || typeof window === "undefined") return "";
  const parsed = new DOMParser().parseFromString(input, "text/html");
  const allowedTags = new Set(["p", "br", "strong", "b", "em", "i", "u", "code", "pre", "h2", "h3", "h4", "ul", "ol", "li", "blockquote", "a", "figure", "figcaption", "img", "hr", "table", "thead", "tbody", "tr", "th", "td"]);
  const removeWithChildren = new Set(["script", "style", "iframe", "object", "embed", "svg", "math", "template", "form", "input", "button", "textarea", "select"]);
  const isSafeUrl = (value: string, kind: "href" | "src") => {
    const trimmed = value.trim();
    if (kind === "href" && trimmed.startsWith("#")) return true;
    if (trimmed.startsWith("//")) return false;
    if (trimmed.startsWith("/")) return true;
    try {
      const url = new URL(trimmed, window.location.origin);
      if (url.protocol === "https:") return true;
      if (url.protocol === "http:" && url.origin === window.location.origin) return true;
      return kind === "href" && url.protocol === "mailto:";
    } catch {
      return false;
    }
  };

  const elements = Array.from(parsed.body.querySelectorAll<HTMLElement>("*")).reverse();
  for (const element of elements) {
    const tag = element.tagName.toLowerCase();
    if (!allowedTags.has(tag)) {
      if (removeWithChildren.has(tag)) element.remove();
      else element.replaceWith(...Array.from(element.childNodes));
      continue;
    }

    for (const attribute of Array.from(element.attributes)) {
      const name = attribute.name.toLowerCase();
      const allowed = tag === "a"
        ? ["href", "title", "target", "rel"].includes(name)
        : tag === "img"
          ? ["src", "alt", "title", "width", "height", "loading"].includes(name)
          : tag === "th"
            ? ["scope", "colspan", "rowspan"].includes(name)
            : tag === "td"
              ? ["colspan", "rowspan"].includes(name)
              : false;
      if (!allowed || name.startsWith("on")) {
        element.removeAttribute(attribute.name);
        continue;
      }
      if ((name === "href" || name === "src") && !isSafeUrl(attribute.value, name)) element.removeAttribute(attribute.name);
    }
    if (tag === "a") {
      element.setAttribute("target", "_blank");
      element.setAttribute("rel", "noopener noreferrer nofollow");
    }
    if (tag === "img") element.setAttribute("loading", "lazy");
  }
  return parsed.body.innerHTML;
}

function formatPreviewDate(value?: string | null) {
  if (!value) return "Bản xem trước";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Bản xem trước";
  return date.toLocaleDateString("vi-VN", { day: "numeric", month: "long", year: "numeric" });
}

export function AdminPanel() {
  const [posts, setPosts] = useState<AdminPost[]>([]);
  const [ingestLogs, setIngestLogs] = useState<IngestLog[]>([]);
  const [selected, setSelected] = useState<Editor | null>(null);
  const [previewing, setPreviewing] = useState<PreviewPost | null>(null);
  const [filter, setFilter] = useState("all");
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [currentUser, setCurrentUser] = useState<SessionInfo | null>(null);
  const [selectedPostIds, setSelectedPostIds] = useState<string[]>([]);
  const [bulkBusy, setBulkBusy] = useState(false);
  const [showFeaturedManager, setShowFeaturedManager] = useState(false);
  const [featuredQuery, setFeaturedQuery] = useState("");
  const [featuredBusyId, setFeaturedBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setBusy(true);
    try {
      const response = await fetch("/api/admin/posts", { cache: "no-store" });
      if (response.status === 401) { window.location.href = "/dang-nhap"; return; }
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Không tải được danh sách bài viết.");
      setPosts(data.posts as AdminPost[]);
      setIngestLogs((data.ingestLogs || []) as IngestLog[]);
      setCurrentUser((data.currentUser || null) as SessionInfo | null);
    } catch (e) { setError(e instanceof Error ? e.message : "Có lỗi xảy ra."); }
    finally { setBusy(false); }
  }, []);

  useEffect(() => { void load(); }, [load]);

  useEffect(() => {
    if (!previewing) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setPreviewing(null);
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [previewing]);

  const filtered = posts.filter((post) => (filter === "all" || post.status === filter) && `${post.title} ${post.category} ${post.country} ${post.destination}`.toLowerCase().includes(query.toLowerCase()));
  const allFilteredSelected = filtered.length > 0 && filtered.every((post) => selectedPostIds.includes(post.id));
  const publishedCount = posts.filter((p) => p.status === "published").length;
  const draftCount = posts.filter((p) => p.status === "draft").length;
  const canCreate = currentUser?.role === "admin" || currentUser?.role === "editor" || currentUser?.role === "author";
  const canPublish = currentUser?.role === "admin" || currentUser?.role === "editor";
  const canDelete = currentUser?.role === "admin" || currentUser?.role === "editor";
  const canViewIngest = canPublish;
  const currentTime = Date.now();
  const publishedPosts = posts.filter((post) => post.status === "published" && !!post.publishedAt && new Date(post.publishedAt).getTime() <= currentTime).sort((a, b) => {
    const dateA = a.publishedAt ? new Date(a.publishedAt).getTime() : 0;
    const dateB = b.publishedAt ? new Date(b.publishedAt).getTime() : 0;
    return dateB - dateA;
  });
  const featuredCount = publishedPosts.filter((post) => post.featured).length;
  const featuredChoices = publishedPosts
    .filter((post) => `${post.title} ${post.category} ${post.country} ${post.destination}`.toLowerCase().includes(featuredQuery.toLowerCase()))
    .slice(0, featuredQuery.trim() ? 200 : 60);

  async function save(statusOverride?: Editor["status"]) {
    if (!selected) return;
    const payload: Editor = statusOverride ? { ...selected, status: statusOverride } : selected;
    const existingPost = payload.id ? posts.find((post) => post.id === payload.id) : undefined;
    if (payload.status === "published" && payload.featured && featuredCount >= 8 && !(existingPost?.status === "published" && existingPost.featured)) {
      setError("Đã chọn đủ 8 tin nổi bật. Hãy bỏ chọn một tin trước khi xuất bản bài này ở trạng thái nổi bật.");
      return;
    }
    setBusy(true); setError(""); setMessage("");
    try {
      const response = await fetch("/api/admin/posts", { method: payload.id ? "PATCH" : "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Không lưu được bài viết.");
      setMessage("Đã lưu bài viết thành công.");
      setSelected(null);
      await load();
    } catch (e) { setError(e instanceof Error ? e.message : "Có lỗi xảy ra."); }
    finally { setBusy(false); }
  }

  async function removePost(post: AdminPost) {
    if (!window.confirm(`Xóa bài “${post.title}”? Thao tác này không thể hoàn tác.`)) return;
    setError(""); setMessage("");
    const response = await fetch(`/api/admin/posts?id=${encodeURIComponent(post.id)}`, { method: "DELETE" });
    const data = await response.json();
    if (!response.ok) { setError(data.error || "Không xóa được bài viết."); return; }
    setMessage("Đã xóa bài viết."); await load();
  }

  function togglePostSelection(id: string, checked: boolean) {
    setSelectedPostIds((current) => checked
      ? (current.includes(id) ? current : [...current, id])
      : current.filter((selectedId) => selectedId !== id));
  }

  function toggleAllFiltered(checked: boolean) {
    setSelectedPostIds(checked ? filtered.map((post) => post.id) : []);
  }

  async function bulkSetStatus(status: AdminPost["status"]) {
    const ids = selectedPostIds.filter((id) => filtered.some((post) => post.id === id));
    if (!ids.length || bulkBusy) return;
    const verb = status === "published" ? "xuất bản" : status === "draft" ? "chuyển về bản nháp" : "lưu trữ";
    const statusLabel = status === "published" ? "Đã xuất bản" : status === "draft" ? "Bản nháp" : "Lưu trữ";
    if (!window.confirm(`Xác nhận ${verb} ${ids.length} bài viết đã chọn?`)) return;

    setBulkBusy(true);
    setError("");
    setMessage("");
    try {
      const response = await fetch("/api/admin/posts/bulk", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ids, status }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || `Không thể ${verb} hàng loạt.`);
      setSelectedPostIds([]);
      setMessage(`Đã chuyển ${data.updatedCount ?? ids.length} bài viết sang trạng thái “${statusLabel}”.`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : `Không thể ${verb} hàng loạt.`);
    } finally {
      setBulkBusy(false);
    }
  }

  async function changeFeatured(post: AdminPost, featured: boolean) {
    if (featuredBusyId) return;
    if (featured && !post.featured && featuredCount >= 8) {
      setError("Đã chọn đủ 8 tin nổi bật. Bỏ chọn một bài trước khi thêm bài khác.");
      return;
    }
    setFeaturedBusyId(post.id);
    setError("");
    setMessage("");
    try {
      const response = await fetch("/api/admin/featured", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: post.id, featured }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Không cập nhật được tin nổi bật.");
      setPosts((current) => current.map((item) => item.id === post.id ? { ...item, featured: data.featured as boolean } : item));
      setMessage(featured ? `Đã thêm “${post.title}” vào tin nổi bật.` : `Đã bỏ “${post.title}” khỏi tin nổi bật.`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Không cập nhật được tin nổi bật.");
    } finally {
      setFeaturedBusyId(null);
    }
  }

  async function logout() {
    await fetch("/api/admin/logout", { method: "POST" });
    window.location.href = "/dang-nhap";
  }

  function update<K extends keyof Editor>(key: K, value: Editor[K]) { setSelected((current) => current ? { ...current, [key]: value } : current); }

  return <div className="admin-shell">
    <aside className="admin-sidebar"><a href="/" className="admin-logo"><span className="brand-mark">ĐĐ</span><span><b>{siteName}</b><small>STUDIO / CMS</small></span></a><div className="admin-side-label">NỘI DUNG</div><a className="admin-side-link active" href="/admin"><Pencil size={17} /> Bài viết <span>{posts.length}</span></a>{canPublish && <a className="admin-side-link" href="/admin/bao-cao-ban-quyen"><ShieldAlert size={17}/> Yêu cầu gỡ nội dung</a>}{currentUser?.role === "admin" && <a className="admin-side-link" href="/admin/phan-quyen"><ShieldCheck size={17}/> Tài khoản & phân quyền</a>}<a className="admin-side-link" href="/" target="_blank" rel="noreferrer"><ExternalLink size={17} /> Xem website</a><div className="admin-sidebar-bottom"><div className="admin-user-mark">{(currentUser?.fullName || "Q").slice(0, 1).toUpperCase()}</div><div className="admin-user-text"><b>{currentUser?.fullName || "Đang tải..."}</b><small>{currentUser ? roleLabel[currentUser.role] : "Tài khoản CMS"}</small></div><button onClick={logout} title="Đăng xuất" aria-label="Đăng xuất"><LogOut size={17}/></button></div></aside>
    <main className="admin-main">
      <div className="admin-topbar"><div><span className="eyebrow">WORKSPACE / CONTENT</span><h1>Quản lý bài viết</h1><p className="admin-page-subtitle">{currentUser ? `Đăng nhập với vai trò ${roleLabel[currentUser.role]}.` : "Đang tải quyền truy cập..."}</p></div><div className="admin-top-actions">{canPublish && <button className="button-secondary admin-featured-toggle" onClick={() => setShowFeaturedManager((value) => !value)} aria-expanded={showFeaturedManager}><Star size={15}/>{showFeaturedManager ? "Đóng tin nổi bật" : `Tin nổi bật (${featuredCount}/8)`}</button>}<a href="/" className="button-secondary" target="_blank" rel="noreferrer">Xem website <ExternalLink size={15}/></a>{canCreate && <button className="button-primary" onClick={() => { setSelected({ ...emptyEditor }); setError(""); setMessage(""); }}><CirclePlus size={16}/> Tạo bài viết</button>}</div></div>
      <div className="admin-stats"><div><span>Tổng bài viết</span><strong>{posts.length}</strong><small>Toàn bộ nội dung</small></div><div><span>Đã xuất bản</span><strong>{publishedCount}</strong><small>Đang hiển thị công khai</small></div><div><span>Bản nháp</span><strong>{draftCount}</strong><small>Chờ hoàn thiện</small></div><div><span>Đồng bộ dữ liệu</span><strong className="admin-live"><i/> Sẵn sàng</strong><small>API-first publishing</small></div></div>
      {(message || error) && <div className={`admin-alert ${error ? "is-error" : "is-success"}`}>{error ? <X size={16}/> : <Check size={16}/>} {error || message}<button onClick={() => { setError(""); setMessage(""); }} aria-label="Đóng thông báo"><X size={15}/></button></div>}
      {canPublish && showFeaturedManager && <section className="admin-table-card admin-featured-manager">
        <div className="admin-table-toolbar admin-featured-toolbar">
          <div><h2>Quản lý tin nổi bật</h2><p>Chọn tối đa 8 bài đã xuất bản để ưu tiên hiển thị trong slide đầu trang.</p></div>
          <span className={`admin-featured-count ${featuredCount >= 8 ? "is-full" : ""}`}><Star size={15}/>{featuredCount}/8 đã chọn</span>
        </div>
        <div className="admin-featured-auto-note"><Star size={16}/><p><b>Tự động bổ sung bài mới</b><span>{Math.max(0, 8 - featuredCount)} vị trí còn lại sẽ tự lấy từ các bài mới xuất bản. Khi mày đánh dấu tin nổi bật, bài đó sẽ được ưu tiên trước.</span></p></div>
        <div className="admin-featured-search-wrap"><label className="admin-search"><Search size={16}/><input value={featuredQuery} onChange={(event) => setFeaturedQuery(event.target.value)} placeholder="Tìm bài đã xuất bản theo tiêu đề, danh mục, điểm đến..." /></label><span>{featuredChoices.length} bài hiển thị / {publishedPosts.length} bài đã xuất bản</span></div>
        <div className="admin-featured-list">
          {featuredChoices.map((post) => <label key={post.id} className={`admin-featured-choice ${post.featured ? "is-featured" : ""}`}>
            <input type="checkbox" className="admin-row-checkbox" checked={post.featured} disabled={featuredBusyId !== null || (!post.featured && featuredCount >= 8)} onChange={(event) => void changeFeatured(post, event.target.checked)} aria-label={`${post.featured ? "Bỏ khỏi" : "Thêm vào"} tin nổi bật: ${post.title}`} />
            <span className="admin-featured-thumb">{post.coverImage ? <img src={post.coverImage} alt="" loading="lazy"/> : <Star size={16}/>}</span>
            <span className="admin-featured-copy"><b>{post.title}</b><small>{post.category}{post.destination ? ` · ${post.destination}` : post.country ? ` · ${post.country}` : ""}</small><small>{post.publishedAt ? new Date(post.publishedAt).toLocaleDateString("vi-VN") : "Đã xuất bản"}</small></span>
            <span className={`admin-featured-badge ${post.featured ? "is-on" : ""}`}>{post.featured ? "Tin nổi bật" : "Bài mới"}</span>
          </label>)}
          {featuredChoices.length === 0 && <p className="admin-featured-empty">Không tìm thấy bài đã xuất bản phù hợp.</p>}
        </div>
        {publishedPosts.length > 60 && !featuredQuery.trim() && <p className="admin-featured-footnote">Đang hiển thị 60 bài mới nhất. Dùng ô tìm kiếm để tìm bài cũ hơn.</p>}
      </section>}

      <section className="admin-table-card"><div className="admin-table-toolbar"><div><h2>Nội dung website</h2><p>Quản lý nội dung từ AI và bài viết biên tập thủ công.</p></div><button className="icon-button" onClick={() => void load()} disabled={busy} aria-label="Tải lại"><RefreshCw size={16}/></button></div><div className="admin-list-controls"><label className="admin-search"><Search size={16}/><input value={query} onChange={(e) => { setQuery(e.target.value); setSelectedPostIds([]); }} placeholder="Tìm theo tiêu đề, danh mục..."/></label><label className="admin-select"><span className="sr-only">Lọc trạng thái</span><select value={filter} onChange={(e) => { setFilter(e.target.value); setSelectedPostIds([]); }}><option value="all">Tất cả trạng thái</option><option value="published">Đã xuất bản</option><option value="draft">Bản nháp</option><option value="archived">Đã lưu trữ</option></select><ChevronDown size={15}/></label></div>
        {canPublish && selectedPostIds.length > 0 && <div className="admin-bulk-toolbar" role="region" aria-label="Thao tác hàng loạt">
          <div className="admin-bulk-selected"><strong>{selectedPostIds.length}</strong><span>bài viết được chọn</span><button type="button" className="admin-bulk-clear" onClick={() => setSelectedPostIds([])} disabled={bulkBusy}>Bỏ chọn</button></div>
          <div className="admin-bulk-actions">
            <button type="button" className="admin-bulk-action is-publish" onClick={() => void bulkSetStatus("published")} disabled={bulkBusy}><Send size={14}/>{bulkBusy ? "Đang xử lý..." : "Xuất bản"}</button>
            <button type="button" className="admin-bulk-action" onClick={() => void bulkSetStatus("draft")} disabled={bulkBusy}><Pencil size={14}/>Chuyển về bản nháp</button>
            <button type="button" className="admin-bulk-action is-archive" onClick={() => void bulkSetStatus("archived")} disabled={bulkBusy}><Archive size={14}/>Lưu trữ</button>
          </div>
        </div>}
        <div className="admin-table-scroll"><table className="admin-table"><thead><tr>{canPublish && <th className="admin-select-cell"><input className="admin-row-checkbox" type="checkbox" checked={allFilteredSelected} onChange={(event) => toggleAllFiltered(event.target.checked)} aria-label="Chọn tất cả bài viết đang hiển thị" title="Chọn tất cả bài viết đang hiển thị"/></th>}<th>Bài viết</th><th>Danh mục</th><th>Trạng thái</th><th>Ngày đăng</th><th><span className="sr-only">Thao tác</span></th></tr></thead><tbody>{filtered.map((post) => <tr key={post.id}>{canPublish && <td className="admin-select-cell"><input className="admin-row-checkbox" type="checkbox" checked={selectedPostIds.includes(post.id)} onChange={(event) => togglePostSelection(post.id, event.target.checked)} aria-label={`Chọn bài ${post.title}`}/></td>}<td><div className="admin-post-title"><div className="admin-thumb">{post.coverImage ? <img src={post.coverImage} alt=""/> : <span>ĐĐ</span>}</div><div><b>{post.title}</b><small>/{post.slug}</small>{(post.country || post.destination) && <small>{[post.country, post.destination].filter(Boolean).join(" / ")}</small>}{post.featured && <em>Nổi bật</em>}</div></div></td><td><span className="table-category">{post.category}</span></td><td><span className={`status-pill status-${post.status}`}>{post.status === "published" ? "Đã xuất bản" : post.status === "draft" ? "Bản nháp" : "Đã lưu trữ"}</span></td><td>{post.publishedAt ? new Date(post.publishedAt).toLocaleDateString("vi-VN") : "—"}</td><td><div className="table-actions"><button title="Xem trước bài" aria-label={`Xem trước ${post.title}`} onClick={() => setPreviewing({ ...editorFromPost(post), publishedAt: post.publishedAt, createdAt: post.createdAt })}><Eye size={15}/></button>{canCreate && <button title="Sửa bài" aria-label={`Sửa ${post.title}`} onClick={() => { setSelected(editorFromPost(post)); setError(""); setMessage(""); }}><Pencil size={15}/></button>}{canDelete && <button title="Xóa bài" aria-label={`Xóa ${post.title}`} onClick={() => void removePost(post)}><Trash2 size={15}/></button>}</div></td></tr>)}{filtered.length === 0 && <tr><td colSpan={canPublish ? 6 : 5} className="admin-empty">{busy ? "Đang tải nội dung..." : "Chưa tìm thấy bài viết phù hợp."}</td></tr>}</tbody></table></div>
        <div className="admin-table-foot">Hiển thị {filtered.length} / {posts.length} bài viết <span>{canPublish ? "Có thể chọn nhiều bài để thay đổi trạng thái cùng lúc." : "Nội dung do AI gửi vào sẽ xuất hiện tại đây."}</span></div>
      </section>
      {canViewIngest && <section className="admin-table-card ingest-history"><div className="admin-table-toolbar"><div><h2>Lịch sử đồng bộ Crawl + AI</h2><p>Những lượt gửi dữ liệu gần nhất được ghi nhận từ API.</p></div><span className="status-pill status-published">API-first</span></div><div className="admin-table-scroll"><table className="admin-table"><thead><tr><th>Thời gian</th><th>Nguồn</th><th>Đã nhận</th><th>Tạo mới</th><th>Cập nhật</th><th>Lỗi</th><th>Trạng thái</th></tr></thead><tbody>{ingestLogs.map((log) => <tr key={log.id}><td>{new Date(log.createdAt).toLocaleString("vi-VN")}</td><td>{log.source}</td><td>{log.received_count}</td><td>{log.created_count}</td><td>{log.updated_count}</td><td>{log.failed_count}</td><td><span className={`status-pill ${log.failed_count ? "status-draft" : "status-published"}`}>{log.failed_count ? "Có lỗi" : "Thành công"}</span></td></tr>)}{ingestLogs.length === 0 && <tr><td colSpan={7} className="admin-empty">Chưa có lượt đồng bộ nào. Lịch sử sẽ xuất hiện khi crawler gửi bài đầu tiên.</td></tr>}</tbody></table></div><div className="admin-table-foot"><span>Giữ tối đa 8 lượt gần nhất trên màn hình này; log đầy đủ nằm trong database.</span><code>POST /api/ingest/posts</code></div></section>}
      {canViewIngest && <div className="admin-api-note"><div className="api-note-icon">{`</>`}</div><div><b>API publishing đang sẵn sàng</b><p>Endpoint <code>POST /api/ingest/posts</code> · Xác thực bằng Bearer API key · Biến môi trường <code>INGEST_AUTO_PUBLISH</code> quyết định xuất bản ngay hay lưu nháp.</p></div></div>}
    </main>
    {selected && <div className="editor-overlay" role="presentation" onMouseDown={(e) => { if (e.target === e.currentTarget) setSelected(null); }}>
      <section className="editor-drawer editor-workspace" role="dialog" aria-modal="true" aria-label="Chỉnh sửa bài viết">
        <header className="editor-header">
          <div><span className="eyebrow">WORKSPACE / BIÊN TẬP</span><h2>{selected.id ? "Chỉnh sửa bài viết" : "Tạo bài viết mới"}</h2><p className="editor-header-subtitle">Soạn nội dung ở cột trái, thiết lập xuất bản ở cột phải.</p></div>
          <div className="editor-header-actions"><button className="button-secondary editor-preview-launch" onClick={() => setPreviewing({ ...selected, publishedAt: selected.status === "published" ? (selected.id ? posts.find((post) => post.id === selected.id)?.publishedAt || null : null) : null })}><Eye size={15}/> Xem trước</button><button className="icon-button" onClick={() => setSelected(null)} aria-label="Đóng trình soạn thảo"><X size={19}/></button></div>
        </header>

        <div className="editor-workspace-body">
          <div className="editor-main-column">
            <section className="editor-panel-card editor-title-panel">
              <label className="editor-title-field"><span>Tiêu đề bài viết *</span><input className="editor-title-input" value={selected.title} onChange={(e) => update("title", e.target.value)} required maxLength={220} placeholder="Thêm tiêu đề bài viết" /></label>
              <label className="editor-field editor-slug-field"><span>Đường dẫn (slug)</span><div className="editor-slug-input"><span>/bai-viet/</span><input value={selected.slug} onChange={(e) => update("slug", e.target.value)} placeholder="de-trong-se-tu-tao-tu-tieu-de" /></div><small>Để trống nếu muốn hệ thống tự tạo từ tiêu đề.</small></label>
              <label className="editor-field"><span>Mô tả ngắn / đoạn giới thiệu</span><textarea rows={3} value={selected.excerpt} onChange={(e) => update("excerpt", e.target.value)} maxLength={500} placeholder="Tóm tắt bài viết để hiển thị trên trang chủ và danh sách bài."/><small className="editor-character-count">{selected.excerpt.length}/500 ký tự</small></label>
            </section>

            <section className="editor-panel-card editor-body-panel">
              <div className="editor-panel-heading"><div><h3>Nội dung bài viết</h3><p>Click công cụ hoặc bôi đen đoạn chữ để định dạng.</p></div><span className="editor-required-label">BẮT BUỘC</span></div>
              <ArticleContentEditor key={selected.id || "new-post"} initialHtml={selected.contentHtml} onChange={(html) => update("contentHtml", html)} />
            </section>

            <section className="editor-panel-card editor-seo-panel">
              <div className="editor-panel-heading"><div><h3>SEO trên Google</h3><p>Tùy chỉnh tiêu đề và mô tả hiển thị trên kết quả tìm kiếm.</p></div><span className="editor-panel-icon">SEO</span></div>
              <div className="seo-preview-card"><span className="seo-preview-site">{siteName}</span><strong>{selected.seoTitle.trim() || selected.title.trim() || "Tiêu đề bài viết sẽ hiển thị ở đây"}</strong><p>{selected.seoDescription.trim() || selected.excerpt.trim() || "Mô tả bài viết sẽ hiển thị ở đây khi người đọc tìm thấy nội dung trên Google."}</p><small>https://example.com/bai-viet/{selected.slug || "duong-dan-bai-viet"}</small></div>
              <label className="editor-field"><span>SEO title</span><input value={selected.seoTitle} onChange={(e) => update("seoTitle", e.target.value)} maxLength={220} placeholder="Để trống sẽ dùng tiêu đề bài viết"/><small className={selected.seoTitle.length > 60 ? "editor-count-warn" : "editor-character-count"}>{selected.seoTitle.length}/60 ký tự khuyến nghị</small></label>
              <label className="editor-field"><span>SEO description</span><textarea rows={3} value={selected.seoDescription} onChange={(e) => update("seoDescription", e.target.value)} maxLength={320} placeholder="Mô tả hấp dẫn, nêu rõ giá trị của bài viết."/><small className={selected.seoDescription.length > 160 ? "editor-count-warn" : "editor-character-count"}>{selected.seoDescription.length}/160 ký tự khuyến nghị</small></label>
            </section>
          </div>

          <aside className="editor-side-column">
            <section className="editor-panel-card editor-side-card editor-publish-card">
              <div className="editor-side-card-heading"><h3>Xuất bản</h3><span className={`status-pill status-${selected.status}`}>{selected.status === "published" ? "Đã xuất bản" : selected.status === "draft" ? "Bản nháp" : "Đã lưu trữ"}</span></div>
              {currentUser?.role === "author" ? <div className="permission-author-note">Bài của tác giả luôn được lưu dưới dạng <b>bản nháp</b> để biên tập viên duyệt trước khi xuất bản.</div> : <label className="editor-field"><span>Trạng thái</span><select value={selected.status} onChange={(e) => update("status", e.target.value as Editor["status"])}><option value="draft">Bản nháp</option><option value="published">Đã xuất bản</option><option value="archived">Lưu trữ</option></select></label>}
              {currentUser?.role !== "author" && <label className="editor-featured"><input type="checkbox" checked={selected.featured} disabled={!selected.featured && featuredCount >= 8} onChange={(e) => update("featured", e.target.checked)}/><span><b>Đưa lên bài nổi bật</b><small>{!selected.featured && featuredCount >= 8 ? "Đã chọn đủ 8 tin. Hãy bỏ chọn một tin trong mục quản lý nổi bật." : "Ưu tiên hiển thị trên trang chủ; slide sẽ tự bổ sung bài mới nếu chưa đủ 8 tin."}</small></span></label>}
              {canPublish && <button className="button-primary editor-publish-button" onClick={() => void save("published")} disabled={busy || selected.title.trim().length < 3}><Save size={15}/>{busy ? "Đang lưu..." : selected.id && selected.status === "published" ? "Cập nhật bài viết" : "Xuất bản"}</button>}
              <button className="button-secondary editor-draft-button" onClick={() => void save("draft")} disabled={busy || selected.title.trim().length < 3}>{busy ? "Đang lưu..." : "Lưu thành bản nháp"}</button>
            </section>

            <section className="editor-panel-card editor-side-card">
              <div className="editor-side-card-heading"><h3>Chuyên mục</h3></div>
              <label className="editor-field"><span>Chủ đề / danh mục</span><select value={normalizeEditorialCategory(selected.category).slug} onChange={(e) => update("category", EDITORIAL_CATEGORIES.find((item) => item.slug === e.target.value)?.name || "Cẩm nang")}>{EDITORIAL_CATEGORIES.map((item) => <option value={item.slug} key={item.slug}>{item.name}</option>)}</select></label>
              <label className="editor-field"><span>Tags (cách nhau bằng dấu phẩy)</span><input value={selected.tags.join(", ")} onChange={(e) => update("tags", e.target.value.split(",").map((tag) => tag.trim()).filter(Boolean))} placeholder="Đà Nẵng, du lịch biển"/><small>Giúp nhóm chủ đề liên quan.</small></label>
            </section>

            <section className="editor-panel-card editor-side-card">
              <div className="editor-side-card-heading"><h3>Điểm đến</h3></div>
              <label className="editor-field"><span>Quốc gia</span><input value={selected.country} onChange={(e) => update("country", e.target.value)} placeholder="Ví dụ: Việt Nam"/></label>
              <label className="editor-field"><span>Thành phố / điểm đến</span><input value={selected.destination} onChange={(e) => update("destination", e.target.value)} placeholder="Ví dụ: Đà Nẵng"/></label>
            </section>

            <section className="editor-panel-card editor-side-card">
              <div className="editor-side-card-heading"><h3>Ảnh đại diện</h3></div>
              {selected.coverImage && <div className="editor-cover-preview"><img src={selected.coverImage} alt={selected.coverAlt || "Xem trước ảnh đại diện"}/></div>}
              <label className="editor-field"><span>URL ảnh</span><input value={selected.coverImage} onChange={(e) => update("coverImage", e.target.value)} placeholder="https://..."/></label>
              <label className="editor-field"><span>Mô tả ảnh (alt)</span><input value={selected.coverAlt} onChange={(e) => update("coverAlt", e.target.value)} placeholder="Mô tả nội dung ảnh"/></label>
              <label className="editor-field"><span>Ghi công / nguồn ảnh</span><input value={selected.coverCredit} onChange={(e) => update("coverCredit", e.target.value)} placeholder="Ảnh: Tên tác giả / nguồn"/></label>
            </section>

            <section className="editor-panel-card editor-side-card">
              <div className="editor-side-card-heading"><h3>Thông tin biên tập</h3></div>
              <label className="editor-field"><span>Tác giả / ban biên tập</span><input value={selected.authorName} onChange={(e) => update("authorName", e.target.value)}/></label>
              <label className="editor-field"><span>Tên nguồn</span><input value={selected.sourceName} onChange={(e) => update("sourceName", e.target.value)} placeholder="Tên trang nguồn"/></label>
              <label className="editor-field"><span>URL nguồn tham khảo</span><input value={selected.sourceUrl} onChange={(e) => update("sourceUrl", e.target.value)} placeholder="https://..."/></label>
            </section>
          </aside>
        </div>

        {error && <div className="editor-inline-error" role="alert"><X size={16}/>{error}</div>}
        <footer className="editor-footer"><button className="button-secondary" onClick={() => setSelected(null)} disabled={busy}>Hủy</button><button className="button-primary" onClick={() => void save()} disabled={busy || selected.title.trim().length < 3}><Save size={16}/>{busy ? "Đang lưu..." : "Lưu thay đổi"}</button></footer>
      </section>
    </div>}
    {previewing && <div className="admin-preview-overlay" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setPreviewing(null); }}>
      <section className="admin-preview-dialog" role="dialog" aria-modal="true" aria-label="Xem trước bài viết">
        <header className="admin-preview-toolbar">
          <div className="admin-preview-toolbar-title"><span className="eyebrow">PREVIEW / BÀI VIẾT</span><h2>{previewing.title.trim() || "Bài viết chưa có tiêu đề"}</h2><p>{previewing.status === "published" ? "Xem trước cách bài viết hiển thị trên website." : "Bản xem trước riêng trong Admin — bài viết chưa được công khai."}</p></div>
          <div className="admin-preview-toolbar-actions">
            <span className={`status-pill status-${previewing.status}`}>{previewing.status === "published" ? "Đã xuất bản" : previewing.status === "draft" ? "Bản nháp" : "Đã lưu trữ"}</span>
            {previewing.status === "published" && previewing.slug && <a className="button-secondary admin-preview-public-link" href={`/bai-viet/${encodeURIComponent(previewing.slug)}`} target="_blank" rel="noreferrer"><ExternalLink size={14}/> Trang công khai</a>}
            <button className="button-primary admin-preview-close" onClick={() => setPreviewing(null)}><X size={15}/> Đóng xem trước</button>
          </div>
        </header>
        <div className="admin-preview-viewport">
          <div className="admin-preview-masthead"><a href="/" className="admin-preview-brand" onClick={(event) => event.preventDefault()}><span className="brand-mark">ĐĐ</span><span><b>{siteName}</b><small>DU LỊCH · ẨM THỰC · TRẢI NGHIỆM</small></span></a><span className="admin-preview-masthead-note">TẠP CHÍ DU LỊCH</span></div>
          <main className="admin-preview-page">
            <div className="admin-preview-breadcrumb">Trang chủ <span>/</span> {previewing.country || "Khám phá"}{previewing.destination ? ` / ${previewing.destination}` : ""} <span>/</span> {previewing.category}</div>
            <article className="admin-preview-article">
              <header className="admin-preview-article-header"><span className="category-label">{previewing.category || "Cẩm nang"}</span><h1>{previewing.title || "Tiêu đề bài viết"}</h1>{previewing.excerpt && <p className="article-deck">{previewing.excerpt}</p>}
                <div className="admin-preview-byline"><span className="author-avatar">ĐĐ</span><div><b>{previewing.authorName || "Ban biên tập"}</b><span>{formatPreviewDate(previewing.publishedAt || previewing.createdAt)}</span></div><span className="admin-preview-reading-time">{Math.max(1, Math.ceil((previewing.contentHtml.replace(/<[^>]*>/g, " ").trim().split(/\s+/).filter(Boolean).length || 1) / 220))} phút đọc</span></div>
              </header>
              {previewing.coverImage && <figure className="admin-preview-cover"><img src={previewing.coverImage} alt={previewing.coverAlt || previewing.title || "Ảnh đại diện bài viết"}/><figcaption>{previewing.coverAlt || previewing.title}{previewing.coverCredit ? ` · ${previewing.coverCredit}` : ""}</figcaption></figure>}
              {previewing.contentHtml.trim() ? <div className="article-body admin-preview-body" dangerouslySetInnerHTML={{ __html: sanitizePreviewHtml(previewing.contentHtml) }}/> : <div className="admin-preview-empty-content">Chưa có nội dung bài viết. Nội dung sẽ hiển thị tại đây.</div>}
              {previewing.tags.length > 0 && <div className="article-tags admin-preview-tags"><b>Từ khóa</b>{previewing.tags.map((tag) => <span key={tag}>{tag}</span>)}</div>}
              {previewing.sourceUrl && <div className="article-source admin-preview-source">Nguồn tham khảo: {previewing.sourceName ? `${previewing.sourceName} · ` : ""}<a href={previewing.sourceUrl} target="_blank" rel="noreferrer nofollow">Xem nguồn gốc</a>.</div>}
            </article>
          </main>
          <footer className="admin-preview-site-footer"><b>{siteName}</b><span>Du lịch · Ẩm thực · Check-in · Kinh nghiệm</span></footer>
        </div>
      </section>
    </div>}
  </div>;
}
