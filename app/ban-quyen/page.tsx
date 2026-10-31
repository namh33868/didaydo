import type { Metadata } from "next";
import { Breadcrumbs } from "@/components/Breadcrumbs";
import { CopyrightReportForm } from "@/components/CopyrightReportForm";
import { siteName } from "@/lib/seo";

export const metadata: Metadata = {
  title: "Bản quyền và sử dụng nội dung",
  description: "Quy định sử dụng nội dung, quyền đối với hình ảnh và cách gửi báo cáo vi phạm bản quyền tới Đi Đây Đó.",
};

export default function CopyrightPage() {
  return (
    <main>
      <div className="container static-page copyright-page">
        <Breadcrumbs items={[{ label: "Trang chủ", href: "/" }, { label: "Bản quyền" }]} />
        <span className="eyebrow">QUYỀN TÁC GIẢ & SỬ DỤNG NỘI DUNG</span>
        <h1>Bản quyền và<br/>sử dụng nội dung.</h1>
        <p>Nội dung biên tập do {siteName} tự sản xuất, gồm bài viết, phần giới thiệu, cách tổ chức nội dung và các yếu tố thiết kế, được bảo vệ theo quy định pháp luật áp dụng. Quyền đối với hình ảnh, trích dẫn và tài sản của bên thứ ba vẫn thuộc chủ sở hữu hoặc được điều chỉnh theo giấy phép tương ứng.</p>
        <h2>Quyền đối với nội dung của Đi Đây Đó</h2>
        <p>Bạn có thể chia sẻ đường dẫn bài viết và trích dẫn một phần ngắn cho mục đích bình luận, giới thiệu hoặc dẫn nguồn, với điều kiện ghi rõ {siteName} và đặt liên kết trực tiếp tới bài gốc. Không được sao chép hàng loạt, đăng lại toàn văn, tạo bản sao có hệ thống, bán lại hoặc sử dụng nội dung như sản phẩm của mình khi chưa có sự đồng ý bằng văn bản của chủ sở hữu quyền.</p>
        <h2>Hình ảnh và tài sản bên thứ ba</h2>
        <p>Không phải mọi hình ảnh xuất hiện trên website đều thuộc sở hữu của {siteName}. Một số hình ảnh được sử dụng theo giấy phép mở hoặc điều kiện của nhà cung cấp. Việc ghi nhận tác giả, nguồn và giấy phép được lưu trong dữ liệu biên tập/metadata; việc không hiển thị dòng ghi công ngay dưới ảnh không làm thay đổi quyền của tác giả hoặc điều kiện giấy phép. Không được suy diễn rằng toàn bộ ảnh trên website được cấp phép tự do để tải về, chỉnh sửa hoặc tái sử dụng.</p>
        <h2>Quy định khi trích dẫn hoặc sử dụng lại</h2>
        <ul>
          <li>Ưu tiên chia sẻ liên kết tới bài gốc thay vì sao chép toàn bộ nội dung.</li>
          <li>Khi trích dẫn, giữ nguyên ngữ cảnh, ghi tên {siteName} và liên kết tới nguồn.</li>
          <li>Muốn sử dụng lại toàn văn, hình ảnh thuộc quyền của website hoặc nội dung cho mục đích thương mại, hãy liên hệ và nhận chấp thuận trước.</li>
          <li>Đối với ảnh có giấy phép riêng, cần tuân thủ đúng giấy phép của tác giả/nhà cung cấp; sự chấp thuận của {siteName} không thay thế chấp thuận của chủ sở hữu ảnh.</li>
        </ul>
        <h2>Gửi yêu cầu xử lý vi phạm</h2>
        <p>Nếu bạn cho rằng một nội dung trên website sử dụng tác phẩm thuộc quyền của mình mà chưa được cho phép, hãy cung cấp thông tin nhận diện tác phẩm gốc, URL nội dung bị báo cáo, phần bị ảnh hưởng, căn cứ quyền sở hữu hoặc ủy quyền và thông tin liên hệ. Ban biên tập sẽ xem xét, có thể yêu cầu bổ sung bằng chứng, liên hệ các bên liên quan và áp dụng biện pháp phù hợp sau khi xác minh. Báo cáo không tự động dẫn đến việc gỡ nội dung.</p>
        <section id="bao-cao-vi-pham" className="copyright-report-section">
          <span className="eyebrow">KÊNH TIẾP NHẬN CHÍNH THỨC</span>
          <h2>Biểu mẫu báo cáo bản quyền</h2>
          <CopyrightReportForm />
        </section>
        <p className="copyright-policy-note">Chính sách này mô tả quy trình tiếp nhận của website, không thay thế tư vấn pháp lý cho từng trường hợp cụ thể. Nội dung có thể được cập nhật khi hoạt động xuất bản hoặc quy định áp dụng thay đổi.</p>
      </div>
    </main>
  );
}
