import Link from "next/link";
import { ArrowLeft, ArrowUpRight, Compass } from "lucide-react";

export default function NotFound() {
  return <main className="not-found"><div><strong>404</strong><h1>Lạc đường một chút rồi.</h1><p>Trang bạn tìm có thể đã được chuyển đi hoặc chưa tồn tại. Mình thử một lối khác nhé.</p><div style={{ display: "flex", justifyContent: "center", flexWrap: "wrap", gap: 12, marginTop: 22 }}><Link href="/" className="button-primary"><ArrowLeft size={16}/> Về trang chủ</Link><Link href="/tim-kiem" className="button-secondary">Tìm kiếm <ArrowUpRight size={15}/></Link></div><div style={{ marginTop: 25, color: "#77907b" }}><Compass size={28}/></div></div></main>;
}
