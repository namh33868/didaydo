# Thiết lập thông báo crawler và Google Analytics

## 1. Email báo cáo xuất bản

Repository đã có bước gửi báo cáo cuối mỗi lượt GitHub Actions bằng Resend. Báo cáo gồm số bài đã xuất bản, mục tiêu 3/5/10, bài lỗi/quota và link từng bài. Nếu chưa cấu hình email, GitHub Actions vẫn ghi báo cáo trong phần Summary và lưu log.

Tạo tài khoản Resend, xác minh domain gửi email theo hướng dẫn của Resend, sau đó thêm các GitHub repository secrets sau:

- `RESEND_API_KEY`: API key của Resend.
- `REPORT_EMAIL_TO`: email nhận báo cáo.
- `REPORT_EMAIL_FROM`: địa chỉ người gửi thuộc domain đã xác minh, ví dụ `Đi Đây Đó <bot@your-domain.com>`.

Mở **GitHub → namh33868/didaydo → Settings → Secrets and variables → Actions → New repository secret** để thêm từng secret. Không đưa API key vào file hoặc commit.

## 2. Google Analytics 4

Tạo property và Web data stream cho `https://didaydo.vercel.app` trong Google Analytics. Sao chép Measurement ID có dạng `G-XXXXXXXXXX`.

Trong **Vercel → Project → Settings → Environment Variables**, thêm:

- Name: `NEXT_PUBLIC_GA_MEASUREMENT_ID`
- Value: Measurement ID dạng `G-XXXXXXXXXX`
- Environment: Production

Sau đó redeploy production. Component `GoogleAnalytics` chỉ tải Google tag khi Measurement ID hợp lệ được cấu hình. GA4 ghi nhận page views trên cả tải trang và điều hướng client-side; bật **Enhanced Measurement → Page changes based on browser history events** trong GA4 Web data stream để đo chuyển trang đúng cách.

Xem số liệu ở **Google Analytics → Reports**:
- Realtime: lượt truy cập đang diễn ra.
- Reports → Acquisition: nguồn người dùng/phiên truy cập.
- Reports → Engagement → Pages and screens: lượt xem và tương tác theo trang.
- Reports → Retention: người dùng quay lại.

GA4 chỉ bắt đầu có dữ liệu sau khi đã cài Measurement ID và redeploy; dữ liệu không hồi tố. Trước khi bật, rà soát thông báo quyền riêng tư và yêu cầu đồng ý cookie áp dụng cho website.

## 3. Lưu ý

Báo cáo email là số liệu xuất bản của crawler, không phải báo cáo traffic. GA4 là nơi xem số người dùng, phiên, lượt xem và tần suất quay lại. Số liệu GA4 không được kéo tự động vào email trong phiên bản tích hợp này.
