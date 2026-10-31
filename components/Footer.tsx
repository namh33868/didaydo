import Link from "next/link";
import { Compass, Facebook, Instagram, Mail, MoveUpRight } from "lucide-react";
import { siteName } from "@/lib/seo";

export function Footer() {
  const email = process.env.NEXT_PUBLIC_CONTACT_EMAIL || "hello@example.com";
  const facebookUrl = process.env.NEXT_PUBLIC_FACEBOOK_URL;
  const instagramUrl = process.env.NEXT_PUBLIC_INSTAGRAM_URL;
  return (
    <footer className="site-footer">
      <div className="container footer-main">
        <div className="footer-brand-column">
          <Link href="/" className="brand footer-brand"><span className="brand-mark"><Compass size={25} /></span><span className="brand-copy"><strong>{siteName}</strong><small>TẠP CHÍ DU LỊCH & ĐỜI SỐNG</small></span></Link>
          <p>Gom nhặt những câu chuyện đẹp, kinh nghiệm hữu ích và cảm hứng để mỗi hành trình đều đáng nhớ.</p>
          <div className="social-links">{facebookUrl && <a href={facebookUrl} aria-label="Facebook" target="_blank" rel="noreferrer"><Facebook size={17} /></a>}{instagramUrl && <a href={instagramUrl} aria-label="Instagram" target="_blank" rel="noreferrer"><Instagram size={17} /></a>}<a href={"mailto:" + email} aria-label="Email"><Mail size={17} /></a></div>
        </div>
        <div><h3>Khám phá</h3><Link href="/the-gioi">Thế giới & quốc gia</Link><Link href="/diem-den">Tất cả điểm đến</Link><Link href="/chuyen-muc/cam-nang">Cẩm nang</Link><Link href="/chuyen-muc/kinh-nghiem-du-lich">Kinh nghiệm du lịch</Link><Link href="/chuyen-muc/am-thuc">Ẩm thực</Link><Link href="/chuyen-muc/hotel-review">Hotel review</Link><Link href="/chuyen-muc/check-in">Check-in</Link></div>
        <div><h3>Về chúng tôi</h3><Link href="/gioi-thieu">Giới thiệu</Link><Link href="/lien-he">Liên hệ</Link><Link href="/chinh-sach-bao-mat">Chính sách bảo mật</Link><Link href="/ban-quyen">Thông báo vi phạm nội dung</Link><a href="/ban-quyen#bao-cao-vi-pham">Gửi yêu cầu gỡ nội dung</a><a href="/rss.xml">RSS tin mới <MoveUpRight size={13} /></a></div>
        <div className="footer-note"><span className="eyebrow">MỘT CHÚT CẢM HỨNG</span><h3>Thế giới rộng lớn. Hãy đi và kể lại câu chuyện của bạn.</h3><Link href="/tim-kiem" className="text-link">Tìm hành trình tiếp theo <MoveUpRight size={15} /></Link></div>
      </div>
      <div className="container footer-bottom"><span>Nội dung trên website có thể được tạo hoặc hỗ trợ bởi AI. Quyền đối với tài sản của bên thứ ba thuộc chủ sở hữu tương ứng.</span><span>Đi tử tế · Kể chân thành · Khám phá có trách nhiệm</span></div>
    </footer>
  );
}
