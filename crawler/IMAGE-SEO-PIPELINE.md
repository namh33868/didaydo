# Image SEO pipeline

## Ảnh dùng cho bài viết mới

1. **Dùng ảnh ngay trong bài nguồn:** crawler lấy ảnh được nhúng trong phần thân bài gốc theo đúng thứ tự và vị trí. Ảnh đại diện Open Graph/RSS chỉ là phương án dự phòng khi trang không có ảnh trong thân bài; không chạy tìm ảnh stock thay thế khi không có ảnh phù hợp.
2. **Tải và kiểm tra:** tải ảnh qua HTTPS từ máy chủ công khai, kiểm tra định dạng/kích thước và gửi ảnh xem trước cho Gemini Vision để nhận diện vị trí logo hoặc watermark.
3. **Xử lý dấu trên ảnh:** nếu logo sát mép và có thể cắt mà vẫn giữ ảnh đủ lớn, crawler crop phần mép đó. Nếu logo nhỏ nằm bên trong ảnh, crawler thử inpainting cục bộ. Mỗi ảnh sau xử lý đều được Gemini Vision kiểm tra lại. Logo lớn, watermark phủ rộng, vị trí không rõ hoặc ảnh sau xử lý vẫn còn dấu sẽ bị loại; crawler không đăng ảnh chưa đạt.
4. **Tối ưu và tự lưu trữ:** ảnh đạt yêu cầu được chuẩn hóa hướng, chuyển sang WebP, đặt tên file SEO, tạo alt tiếng Việt và tải lên Vercel Blob qua API nội bộ. Bài đăng dùng URL Blob, không hotlink URL ảnh từ trang nguồn.
5. **Nội dung ảnh:** URL ảnh trong thân bài được thay bằng URL WebP đã lưu trữ. Ảnh bị loại khỏi bộ HTML để tránh làm lộ lại URL ảnh chưa xử lý.

Quyền tái sử dụng ảnh nguồn được bật trong workflow theo xác nhận của người vận hành (SOURCE_IMAGE_REUSE_AUTHORIZED=true). Việc chỉnh kích thước/đổi URL không tự tạo ra quyền sử dụng; cấu hình này chỉ nên giữ khi quyền từ các nguồn đã được người vận hành giải quyết.

## Giới hạn xử lý logo/watermark

- Crop chỉ được thử khi dấu nằm sát mép và phần cắt không vượt quá 14% kích thước cạnh, đồng thời ảnh còn lại tối thiểu 300×200 px.
- Inpainting chỉ được dùng cho dấu nhỏ (tối đa 12% chiều rộng, 12% chiều cao và 1,8% diện tích ảnh). Dấu lớn hoặc watermark trải rộng sẽ bị loại để tránh phá hỏng nội dung hình.
- AI phải trả bounding box hợp lệ và ảnh sau xử lý phải vượt qua lần kiểm tra cuối với độ tin cậy cao. Khi Gemini/OpenCV lỗi hoặc kết quả không rõ, ảnh bị loại theo hướng an toàn.
- OpenCV headless được cài từ crawler/requirements.txt; không cần GUI.

## Upload architecture

- GitHub Actions does not need BLOB_READ_WRITE_TOKEN.
- The crawler sends each optimized WebP to POST /api/internal/images using SITE_INGEST_API_KEY.
- The Next.js route verifies that key, checks the WebP signature and file size, then uploads to images/covers/ using @vercel/blob.
- Vercel obtains the platform-managed OIDC credential when the Blob store is connected with OIDC. No OIDC token is copied into GitHub or browser code.

Create a Public Blob store in Vercel because article images must be readable by website visitors. Connect the store to the Didaydo project. The workflow's Blob API preflight verifies real access.

The only GitHub secrets required for this image upload path are SITE_URL and SITE_INGEST_API_KEY. Keep the ingest key private and do not commit it to the repository.

## Batch tool for local images

Run from the crawler folder:

```bash
python batch_optimize_images.py ./input-images ./optimized-images --max-width 800 --max-bytes 102400
```

The tool creates SEO-friendly WebP files and an image-manifest.json. It does not overwrite source files or upload the output folder.
