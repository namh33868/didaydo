import { Search } from "lucide-react";

export function SearchBox({ initialValue = "", large = false }: { initialValue?: string; large?: boolean }) {
  return <form action="/tim-kiem" className={`search-form ${large ? "search-form-large" : ""}`} role="search"><label className="sr-only" htmlFor={large ? "site-search-large" : "site-search"}>Tìm bài viết</label><Search size={large ? 22 : 18} /><input id={large ? "site-search-large" : "site-search"} name="q" defaultValue={initialValue} placeholder="Tìm điểm đến, kinh nghiệm, món ngon..." /><button type="submit">Tìm kiếm</button></form>;
}
