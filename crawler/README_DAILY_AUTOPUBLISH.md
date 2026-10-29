# Chạy crawler mỗi ngày và tự xuất bản lên website

Workflow `.github/workflows/daily-crawler.yml` nằm ở thư mục gốc repository. Nó chạy mỗi ngày lúc 08:00 giờ Việt Nam (01:00 UTC), và có thể chạy tay trong tab **Actions**.

## 1. Cấu hình Vercel

Trong **Vercel → Project → Settings → Environment Variables**, đặt ở môi trường **Production**:

```dotenv
INGEST_API_KEY=<key bí mật dùng chung với crawler>
INGEST_AUTO_PUBLISH=true
```

`INGEST_API_KEY` phải trùng với GitHub Actions secret `SITE_INGEST_API_KEY`. Sau khi cập nhật `app/api/ingest/posts/route.ts`, commit và push lên nhánh production để Vercel deploy lại. Crawler sẽ từ chối gửi bài nếu API health chưa xác nhận auto-publish đã bật.

## 2. Thêm GitHub Actions secrets

Vào **GitHub repository → Settings → Secrets and variables → Actions → New repository secret**, tạo:

- `SITE_URL`: domain production, ví dụ `https://ten-project.vercel.app` (không dùng localhost).
- `SITE_INGEST_API_KEY`: cùng giá trị với `INGEST_API_KEY` trên Vercel.
- Ít nhất một key AI đang dùng: `GEMINI_API_KEY`, `OPENAI_API_KEY`, `GROQ_API_KEY` hoặc `OPENROUTER_API_KEY`.
- Thêm các key AI dự phòng nếu cần. Đừng đưa key vào source code, commit hoặc log.

Không cần cấu hình Telegram token; workflow không gửi bài hay thông báo qua Telegram.

## 3. Đưa patch vào đúng cấu trúc repository

Giả sử crawler đã nằm ở `crawler/` trong repository website:

- Thay `crawler/main.py`.
- Thay `crawler/site_publisher.py`.
- Thay `app/api/ingest/posts/route.ts`.
- Thêm `.github/workflows/daily-crawler.yml` ở **root website**, không đặt trong `crawler/.github/`.
- Có thể giữ file này làm tài liệu tham khảo.

Commit và push lên nhánh mặc định của repository (GitHub chỉ kích hoạt lịch `schedule` trên nhánh mặc định). Đảm bảo `crawler/requirements.txt`, `crawler/sources.json` và `crawler/taxonomy.json` đã có trong repository. Không commit `crawler/.env`, API keys, database SQLite hoặc output chứa dữ liệu riêng.

## 4. Chạy thử

Mở **GitHub → Actions → Daily travel crawler → Run workflow**. Xem log job; tải artifact `daily-crawler-log-...` nếu cần đọc log đầy đủ.

Workflow đặt mục tiêu xuất bản tối đa 10 bài mới mỗi lần chạy. Nó thử xuất bản các bản AI hoàn chỉnh đang chờ do lần trước lỗi trước, rồi mới crawl bài mới để bù phần hạn mức còn lại. Bài trùng được bỏ qua. Số bài xuất bản thực tế có thể thấp hơn 10 nếu nguồn không đủ bài mới hoặc AI/API gặp lỗi. Database SQLite và output được giữ qua GitHub Actions cache để hạn chế crawl trùng giữa các lần chạy.

## Lưu ý xuất bản

- Bài mới sẽ được gửi với trạng thái `published` và chỉ được coi là thành công khi API website trả về `published`.
- Bản nháp cũ trên website không tự động bị xuất bản hàng loạt; workflow chủ yếu xử lý bài mới.
- Ảnh nguồn bị tắt mặc định (`SOURCE_IMAGE_REUSE_AUTHORIZED=false`). Chỉ bật tái sử dụng khi đã xác nhận quyền sử dụng; khi chưa được phép, placeholder rà soát quyền ảnh sẽ bị bỏ khỏi HTML công khai.
- Tự động xuất bản không có bước duyệt biên tập thủ công, nên vẫn cần theo dõi nội dung, dữ kiện, bản quyền và log.
