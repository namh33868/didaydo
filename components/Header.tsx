"use client";

import Link from "next/link";
import { useState } from "react";
import { ChevronDown, Compass, Menu, Search, X } from "lucide-react";
import { siteName } from "@/lib/seo";

type NavItem = { label: string; href: string; children?: { label: string; href: string }[] };

const navItems: NavItem[] = [
  {
    label: "Thế giới",
    href: "/the-gioi",
    children: [
      { label: "Tất cả quốc gia", href: "/the-gioi" },
      { label: "Việt Nam", href: "/diem-den/viet-nam" },
      { label: "Nhật Bản", href: "/diem-den/nhat-ban" },
      { label: "Thái Lan", href: "/diem-den/thai-lan" },
      { label: "Hàn Quốc", href: "/diem-den/han-quoc" },
      { label: "Singapore", href: "/diem-den/singapore" },
    ],
  },
  { label: "Điểm đến", href: "/diem-den" },
  {
    label: "Cẩm nang",
    href: "/chuyen-muc/cam-nang",
    children: [
      { label: "Kinh nghiệm du lịch", href: "/chuyen-muc/kinh-nghiem-du-lich" },
      { label: "Lịch trình", href: "/chuyen-muc/lich-trinh" },
      { label: "Di chuyển", href: "/chuyen-muc/di-chuyen" },
      { label: "Chi phí & ngân sách", href: "/chuyen-muc/chi-phi-du-lich" },
      { label: "Văn hóa & địa phương", href: "/chuyen-muc/van-hoa-dia-phuong" },
    ],
  },
  { label: "Ẩm thực", href: "/chuyen-muc/am-thuc" },
  { label: "Hotel review", href: "/chuyen-muc/hotel-review" },
  { label: "Check-in", href: "/chuyen-muc/check-in" },
];

export function Header() {
  const [open, setOpen] = useState(false);
  const [expandedMobileGroups, setExpandedMobileGroups] = useState<string[]>([]);

  const toggleMobileGroup = (href: string) => {
    setExpandedMobileGroups((current) => current.includes(href)
      ? current.filter((item) => item !== href)
      : [...current, href]);
  };

  const closeMobileMenu = () => {
    setOpen(false);
    setExpandedMobileGroups([]);
  };

  return (
    <header className="site-header">
      <div className="topline"><div className="container top-line-inner"><span>CẢM HỨNG CHO HÀNH TRÌNH TIẾP THEO</span><span className="topline-right">Đi để hiểu hơn, trở về với nhiều câu chuyện hơn.</span></div></div>
      <div className="container header-main">
        <Link href="/" className="brand" aria-label={`${siteName} - Trang chủ`} onClick={closeMobileMenu}>
          <span className="brand-mark"><Compass size={27} strokeWidth={1.8} /></span>
          <span className="brand-copy"><strong>{siteName}</strong><small>TẠP CHÍ DU LỊCH & ĐỜI SỐNG</small></span>
        </Link>
        <nav className="desktop-nav" aria-label="Điều hướng chính">
          {navItems.map((item) => item.children ? (
            <div className="desktop-nav-group" key={item.href}>
              <Link href={item.href} className="desktop-nav-parent">{item.label}<ChevronDown size={12} aria-hidden="true"/></Link>
              <div className="desktop-nav-dropdown">
                {item.children.map((child) => <Link key={child.href} href={child.href}>{child.label}</Link>)}
              </div>
            </div>
          ) : <Link key={item.href} href={item.href}>{item.label}</Link>)}
        </nav>
        <div className="header-actions">
          <Link className="search-icon" href="/tim-kiem" aria-label="Tìm kiếm"><Search size={20} /></Link>
          <button className="mobile-menu-button" type="button" onClick={() => setOpen(!open)} aria-label={open ? "Đóng menu" : "Mở menu"} aria-expanded={open}>
            {open ? <X size={23} /> : <Menu size={23} />}
          </button>
        </div>
      </div>
      {open && <nav className="mobile-menu" aria-label="Menu điện thoại"><div className="container mobile-menu-inner">
        {navItems.map((item) => {
          const expanded = expandedMobileGroups.includes(item.href);
          const subnavId = `mobile-subnav-${item.href.replace(/[^a-z0-9]+/gi, "-").replace(/^-|-$/g, "")}`;
          return <div className={`mobile-nav-group${item.children ? " has-children" : ""}`} key={item.href}>
            <div className="mobile-nav-parent-row">
              <Link className="mobile-nav-parent" href={item.href} onClick={closeMobileMenu}>{item.label}</Link>
              {item.children && <button className={`mobile-nav-toggle${expanded ? " is-expanded" : ""}`} type="button" aria-label={`${expanded ? "Thu gọn" : "Mở rộng"} ${item.label}`} aria-expanded={expanded} aria-controls={subnavId} onClick={() => toggleMobileGroup(item.href)}><ChevronDown size={17}/></button>}
            </div>
            {item.children && expanded && <div className="mobile-nav-children" id={subnavId}>
              {item.children.map((child) => <Link className="mobile-nav-child" key={child.href} href={child.href} onClick={closeMobileMenu}>{child.label}</Link>)}
            </div>}
          </div>;
        })}
        <div className="mobile-nav-utility"><Link href="/gioi-thieu" onClick={closeMobileMenu}>Về chúng tôi</Link><Link href="/tim-kiem" onClick={closeMobileMenu}>Tìm kiếm bài viết</Link></div>
      </div></nav>}
    </header>
  );
}
