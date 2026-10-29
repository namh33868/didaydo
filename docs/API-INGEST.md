# Tích hợp crawler / AI với website

Endpoint: `POST /api/ingest/posts`

Header bắt buộc:

```http
Authorization: Bearer <INGEST_API_KEY>
Content-Type: application/json
```

## Gửi một bài

```json
{
  "title": "Khám phá một điểm đến",
  "slug": "kham-pha-mot-diem-den",
  "excerpt": "Tóm tắt hiển thị ở danh sách bài viết.",
  "contentHtml": "<p>Mở bài...</p><h2>Điều cần biết</h2><p>Nội dung...</p>",
  "coverImage": "https://cdn.example.com/travel.jpg",
  "coverAlt": "Phong cảnh tại điểm đến",
  "category": "Điểm đến Việt Nam",
  "tags": ["điểm đến", "kinh nghiệm"],
  "sourceUrl": "https://publisher.example.com/original-story",
  "sourceName": "Tên nguồn tham khảo",
  "authorName": "Ban biên tập",
  "seoTitle": "Khám phá điểm đến | Đi Đây Đó",
  "seoDescription": "Gợi ý những điều cần biết trước chuyến đi.",
  "featured": false
}
```

## Gửi một lô bài

Đặt các object bài viết trong mảng `posts`. Tối đa 100 bài trong một request.

```json
{ "posts": [ { "title": "Bài 1", "contentHtml": "<p>Nội dung 1</p>" }, { "title": "Bài 2", "contentHtml": "<p>Nội dung 2</p>" } ] }
```

## Ví dụ từ máy chạy crawler

```bash
curl -X POST "$SITE_URL/api/ingest/posts" \
  -H "Authorization: Bearer $INGEST_API_KEY" \
  -H "Content-Type: application/json" \
  --data-binary @article.json
```

PowerShell trên Windows (đặt `SITE_URL` và `INGEST_API_KEY` trong môi trường của tiến trình crawler trước khi chạy):

```powershell
$headers = @{ Authorization = "Bearer $env:INGEST_API_KEY" }
$body = Get-Content .\article.json -Raw
Invoke-RestMethod -Method Post -Uri "$env:SITE_URL/api/ingest/posts" -Headers $headers -ContentType "application/json" -Body $body
```

## Quy tắc đồng bộ

- Nếu `sourceUrl` đã tồn tại, API cập nhật bản ghi đó để tránh tạo bài trùng. Hãy gửi URL nguồn ổn định cho từng bài.
- Nếu thiếu `slug`, API tự tạo slug từ tiêu đề. Nếu slug bị trùng, API thêm hậu tố để tránh xung đột.
- Nên đặt `INGEST_AUTO_PUBLISH=false` để bài gửi từ crawler mặc định là bản nháp. Payload có `status: "draft"` luôn tạo bản nháp ngay cả khi biến toàn cục vô tình đặt `true`. Khi cập nhật bài đã có bằng `sourceUrl`, API giữ nguyên trạng thái hiện tại; API ingest không tự chuyển bài nháp thành published.
- HTML trong `contentHtml` được làm sạch; dùng các tag nội dung như `p`, `h2`, `h3`, `ul`, `ol`, `li`, `blockquote`, `a`, `figure`, `img`. Script và thuộc tính nguy hiểm bị loại bỏ.
- Chỉ gửi URL ảnh `https`. Ảnh nên có alt rõ ràng.
- Ghi lại response của API trong hệ thống crawl. Nếu response có `failed > 0`, xem `results` để xác định bài nào lỗi và chỉ gửi lại các bài thất bại.
- Không đặt `INGEST_API_KEY` trong code trình duyệt. Chỉ gọi API từ backend của crawler / workflow AI.


## Kết nối crawler có kiểm soát

- `GET /api/ingest/posts?health=1` (Bearer key) xác nhận API có hỗ trợ nhập bài ở trạng thái draft an toàn. Crawler sẽ không gửi bài nếu endpoint này chưa có phiên bản tương thích.
- `GET /api/ingest/posts?sourceUrl=<URL>` (Bearer key) trả trạng thái bài đã nhận để crawler nhận biết khi biên tập viên chuyển từ `draft` sang `published`.
- Bài mới từ crawler được gửi với `status: "draft"`; biên tập viên kiểm tra ở `/admin` rồi mới xuất bản.
- `INGEST_API_KEY` chỉ đặt trên server website; trong crawler, đặt cùng giá trị vào `SITE_INGEST_API_KEY`. Không để key trong frontend/repository công khai.
