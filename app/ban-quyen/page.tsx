import type { Metadata } from "next";
import { Breadcrumbs } from "@/components/Breadcrumbs";
import { CopyrightReportForm } from "@/components/CopyrightReportForm";
import { siteName } from "@/lib/seo";

export const metadata: Metadata = {
  title: "Thông báo vi phạm nội dung",
  description: "Kênh gửi thông báo về nội dung bị cho là vi phạm quyền tác giả hoặc quyền của bên thứ ba trên Đi Đây Đó.",
};

export default function CopyrightPage() {
  return (
    <main>
      <div className="container static-page copyright-page">
        <Breadcrumbs items={[{ label: "Trang chủ", href: "/" }, { label: "Thông báo vi phạm" }]} />
        <span className="eyebrow">MINH BẠCH NỘI DUNG & TIẾP NHẬN THÔNG BÁO</span>
        <h1>Thông báo vi phạm<br/>và yêu cầu gỡ nội dung.</h1>
        <p>Nội dung trên {siteName} có thể được tạo hoặc hỗ trợ bởi công cụ AI và được biên tập trước khi đăng. Việc xuất hiện trên website không phải là tuyên bố rằng {siteName} sở hữu độc quyền mọi quyền tác giả đối với nội dung đó. Hình ảnh, trích dẫn, nhãn hiệu và tài sản của bên thứ ba có thể thuộc quyền của chủ sở hữu hoặc chịu điều kiện giấy phép riêng.</p>
        <h2>Gửi thông báo khi phát hiện nội dung có vấn đề</h2>
        <p>Nếu bạn là chủ sở hữu quyền hoặc người được ủy quyền và cho rằng một nội dung trên website sử dụng tác phẩm của bạn không phù hợp, hãy gửi thông báo kèm thông tin đủ để chúng tôi xác minh. Kênh này cũng tiếp nhận thông tin về hình ảnh, tài liệu hoặc tài sản của bên thứ ba được đăng tải trên website.</p>
        <ul>
          <li>Thông tin nhận diện tác phẩm hoặc tài sản mà bạn cho rằng bị ảnh hưởng.</li>
          <li>Đường dẫn cụ thể tới nội dung trên {siteName} và vị trí phần nội dung bị phản ánh.</li>
          <li>Đường dẫn tới bản gốc hoặc tài liệu giúp xác minh quyền của bạn, nếu có.</li>
          <li>Họ tên, email liên hệ và căn cứ cho thấy bạn là chủ sở hữu hoặc người được ủy quyền.</li>
          <li>Xác nhận rằng thông tin được cung cấp là chính xác và việc gửi thông báo dựa trên thiện chí.</li>
        </ul>
        <h2>Quy trình xem xét</h2>
        <p>Ban phụ trách sẽ kiểm tra thông tin, có thể liên hệ để yêu cầu làm rõ hoặc bổ sung tài liệu. Tùy kết quả xác minh, website có thể chỉnh sửa, giới hạn truy cập hoặc gỡ nội dung bị phản ánh. Việc gửi thông báo không tự động dẫn đến gỡ bỏ; các yêu cầu thiếu thông tin hoặc không đủ căn cứ có thể chưa được xử lý.</p>
        <section id="bao-cao-vi-pham" className="copyright-report-section">
          <span className="eyebrow">KÊNH TIẾP NHẬN CHÍNH THỨC</span>
          <h2>Gửi thông báo / yêu cầu gỡ nội dung</h2>
          <CopyrightReportForm />
        </section>
        <p className="copyright-policy-note">Quy trình tiếp nhận được thiết kế theo hướng notice-and-takedown và tham khảo cấu trúc thông báo thường dùng trong DMCA. Đây không phải là tuyên bố rằng {siteName} đã đăng ký đại diện DMCA tại Hoa Kỳ hoặc là tư vấn pháp lý. Người gửi cần tự bảo đảm mình có căn cứ và thẩm quyền phù hợp khi gửi yêu cầu.</p>
      </div>
    </main>
  );
}
