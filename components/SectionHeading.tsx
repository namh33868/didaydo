import Link from "next/link";
import { ArrowUpRight } from "lucide-react";

export function SectionHeading({ eyebrow, title, href, linkText = "Xem tất cả" }: { eyebrow: string; title: string; href?: string; linkText?: string }) {
  return <div className="section-heading"><div><span className="eyebrow">{eyebrow}</span><h2>{title}</h2></div>{href && <Link href={href} className="text-link">{linkText}<ArrowUpRight size={16} /></Link>}</div>;
}
