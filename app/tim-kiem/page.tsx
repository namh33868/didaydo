import type { Metadata } from "next";
import { Breadcrumbs } from "@/components/Breadcrumbs";
import { PostCard } from "@/components/PostCard";
import { SearchBox } from "@/components/SearchBox";
import { searchPosts } from "@/lib/posts";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Tìm kiếm", description: "Tìm điểm đến, câu chuyện và kinh nghiệm du lịch trên Đi Đây Đó.", robots: { index: false, follow: true } };

type Props = { searchParams: Promise<{ q?: string }> };
export default async function SearchPage({ searchParams }: Props) {
  const { q = "" } = await searchParams;
  const query = q.trim().slice(0, 100);
  const results = query.length >= 2 ? await searchPosts(query, 50) : [];
  return <main><section className="page-intro"><div className="container"><Breadcrumbs items={[{ label: "Trang chủ", href: "/" }, { label: "Tìm kiếm" }]} /><span className="eyebrow">TÌM CẢM HỨNG CHO HÀNH TRÌNH</span><h1>Tìm câu chuyện<br/>bạn đang kiếm.</h1><p>Khám phá điểm đến, kinh nghiệm, văn hóa và những điều thú vị trên mỗi hành trình.</p><div style={{ marginTop: 24 }}><SearchBox initialValue={query} large /></div></div></section><section className="section"><div className="container">{query.length < 2 ? <div className="empty-content"><h2>Bạn muốn khám phá điều gì?</h2><p>Nhập ít nhất 2 ký tự để tìm kiếm trong tiêu đề, mô tả, danh mục và thẻ bài viết.</p></div> : <><div className="section-heading"><div><span className="eyebrow">KẾT QUẢ TÌM KIẾM</span><h2>“{query}”</h2></div><span className="issue-date">{results.length} kết quả</span></div>{results.length ? <div className="post-grid">{results.map((post) => <PostCard key={post.id} post={post}/>)}</div> : <div className="empty-content"><h2>Chưa tìm thấy bài phù hợp</h2><p>Thử một từ khóa khác hoặc khám phá các chuyên mục trên website.</p></div>}</>}</div></section></main>;
}
