# Thiết lập thông báo crawler và Google Analytics

## 1. Email báo cáo xuất bản

Repository đã có bước gửi báo cáo sau mỗi lượt GitHub Actions. Báo cáo gồm số bài đã xuất bản, mục tiêu 3/5/10, bài lỗi/quota và link từng bài. GitHub Actions Summary vẫn có báo cáo nếu chưa bật email.

### Dùng Gmail (khuyến nghị khi muốn gửi từ hộp thư Gmail cá nhân)

Kết nối Gmail trong ChatGPT không tự cấp quyền gửi thư cho GitHub Actions. Crawler chạy trên GitHub nên cần thông tin SMTP riêng.

1. Đăng nhập Google Account → **Security** → bật **2-Step Verification**.
2. Vào **App passwords**: https://myaccount.google.com/apppasswords.
3. Tạo App Password tên `Didaydo GitHub Actions`, sao chép mã 16 ký tự.
4. Trong **GitHub → namh33868/didaydo → Settings → Secrets and variables → Actions**, tạo:
   - `GMAIL_USERNAME`: địa chỉ Gmail đầy đủ dùng để gửi.
   - `GMAIL_APP_PASSWORD`: App Password 16 ký tự vừa tạo, không phải mật khẩu đăng nhập Gmail.
   - `REPORT_EMAIL_TO`: địa chỉ email nhận báo cáo (có thể là cùng Gmail).
5. Không đưa App Password vào code, .env đã commit, Issue hoặc chat.

Gmail SMTP dùng `smtp.gmail.com`, cổng 587 và TLS. Nếu Google không hiển thị App passwords, tài khoản có thể không đủ điều kiện (ví dụ cấu hình bảo mật chỉ dùng security key, Advanced Protection hoặc chính sách quản trị Workspace). Xem hướng dẫn chính thức: https://support.google.com/mail/answer/185833.

### Dùng Resend thay thế

Nếu không muốn dùng Gmail SMTP, tạo tài khoản Resend, xác minh domain gửi email rồi thêm:
- `RESEND_API_KEY`
- `REPORT_EMAIL_TO`
- `REPORT_EMAIL_FROM` (địa chỉ thuộc domain đã xác minh).

Khi cả Gmail và Resend được cấu hình, crawler ưu tiên Gmail.


## 2. Google Analytics 4

Tạo property và Web data stream cho `https://didaydo.vercel.app` trong Google Analytics. Sao chép Measurement ID có dạng `G-XXXXXXXXXX`.

Trong **Vercel → Project → Settings → Environment Variables**, thêm:

- Name: `NEXT_PUBLIC_GA_MEASUREMENT_ID`
- Value: Measurement ID dạng `G-XXXXXXXXXX`
- Environment: Production

Sau đó redeploy production. Component `GoogleAnalytics` chỉ tải Google tag khi Measurement ID hợp lệ được cấu hình và độc giả đã chọn đồng ý cookie phân tích. Người đọc có thể đổi lựa chọn tại trang Chính sách bảo mật. GA4 ghi nhận page views trên cả tải trang và điều hướng client-side; bật **Enhanced Measurement → Page changes based on browser history events** trong GA4 Web data stream để đo chuyển trang đúng cách.

Xem số liệu ở **Google Analytics → Reports**:
- Realtime: lượt truy cập đang diễn ra.
- Reports → Acquisition: nguồn người dùng/phiên truy cập.
- Reports → Engagement → Pages and screens: lượt xem và tương tác theo trang.
- Reports → Retention: người dùng quay lại.

GA4 chỉ bắt đầu có dữ liệu sau khi đã cài Measurement ID và redeploy; dữ liệu không hồi tố. Trước khi bật, rà soát thông báo quyền riêng tư và yêu cầu đồng ý cookie áp dụng cho website.

## 3. Lưu ý

Báo cáo email là số liệu xuất bản của crawler, không phải báo cáo traffic. GA4 là nơi xem số người dùng, phiên, lượt xem và tần suất quay lại. Số liệu GA4 không được kéo tự động vào email trong phiên bản tích hợp này.


Website có hộp lựa chọn cookie phân tích: GA4 không được tải trước khi độc giả đồng ý. Người đọc có thể mở lại lựa chọn ở trang `/chinh-sach-bao-mat`.
