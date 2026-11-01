# Image SEO pipeline

## Quy tắc ưu tiên ảnh

1. **Ảnh trong bài nguồn được ưu tiên tuyệt đối:** crawler dùng các URL ảnh lấy từ phần thân bài. Nếu phần thân bài không có ảnh, crawler dùng `og:image` hoặc ảnh RSS nếu có. Chỉ khi không có bất kỳ URL ảnh nguồn hợp lệ nào mới tìm ảnh ngoài.
2. **Không xử lý lại ảnh nguồn:** không tải file ảnh về, không gọi Gemini Vision, không crop/inpaint, không giải mã, không chuyển WebP và không upload Blob. Crawler giữ nguyên path và query của URL CDN để tránh làm hỏng URL ký số; chỉ chuẩn hóa URL thành HTTPS, bỏ fragment và bổ sung metadata `alt`, `loading=lazy`, `decoding=async`.
3. **Ảnh ngoài là phương án cuối:** chỉ khi bài nguồn không có ảnh hợp lệ, crawler mới tìm ảnh khớp chủ đề/điểm đến qua nguồn có metadata giấy phép. Ảnh ngoài cũng được dùng bằng HTTPS URL trực tiếp, kèm tác giả, nhà cung cấp, trang nguồn và giấy phép; không chạy thêm AI Vision hoặc upload ảnh.
4. **Tối ưu phần trình bày:** crawler chọn ảnh nguồn đầu tiên làm cover, giữ thứ tự các ảnh inline, dùng alt tiếng Việt khi alt nguồn trống hoặc không phù hợp, và giữ link nguồn trong credit.

## Vì sao nhanh hơn

- Bỏ hai lượt gọi Gemini Vision cho mỗi ảnh.
- Bỏ tải ảnh gốc, decode/resize/encode WebP và ghi Blob cho ảnh đã có trong bài.
- Bỏ OpenCV/inpainting khỏi requirements và khỏi workflow.
- Bỏ bước rà ảnh bài cũ trong mỗi lượt chạy mặc định.
- Không chạy tìm ảnh bên ngoài khi nguồn đã cung cấp được ảnh hợp lệ.

## Ảnh ngoài và quyền sử dụng

Nhánh ảnh ngoài tiếp tục yêu cầu kết quả có độ liên quan theo bài/điểm đến và metadata giấy phép từ nguồn tìm kiếm. Credit hiển thị tác giả, nhà cung cấp, nguồn ảnh và URL giấy phép khi có. Quyền tái sử dụng ảnh nguồn được bật trong workflow theo xác nhận của người vận hành (`SOURCE_IMAGE_REUSE_AUTHORIZED=true`).

## URL và metadata

- URL ảnh gốc được giữ nguyên path và query string; chỉ chuyển `http` thành `https` để phù hợp với website và bỏ fragment.
- `alt` ưu tiên nội dung mô tả tiếng Việt của ảnh; nếu thiếu, dùng tiêu đề bài và địa điểm làm alt dự phòng.
- `srcset`/`sizes` được bỏ trên ảnh inline đã chuẩn hóa để trình duyệt không chọn một URL ảnh khác chưa được ánh xạ.
- Ảnh nguồn tiếp tục được tải trực tiếp từ máy chủ gốc khi người đọc mở bài. Không còn yêu cầu Vercel Blob cho luồng ảnh crawler thông thường.

## Công cụ WebP ngoại tuyến

Batch tool vẫn có thể chuyển các file do người vận hành cung cấp thành WebP khi cần:

```bash
python batch_optimize_images.py ./input-images ./optimized-images --max-width 800 --max-bytes 102400
```

Đây là công cụ chạy riêng, không nằm trong pipeline xuất bản hằng ngày.
