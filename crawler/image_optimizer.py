"""Rights-first image processing for DiDayDo's crawler.

This module downloads only HTTPS images from public hosts, rejects obvious preview /
watermark hints in metadata, converts approved assets to WebP, creates SEO filenames,
and uploads the processed files to a public Vercel Blob store.

It intentionally does not remove visible watermarks. Images with visible marks must be
replaced with a clean licensed original or reviewed manually.
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import re
import unicodedata
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import requests
from PIL import Image, ImageOps, UnidentifiedImageError

log = logging.getLogger("travel-content-bot.image-optimizer")

USER_AGENT = os.getenv(
    "CRAWLER_USER_AGENT",
    "DiDayDoTravelCrawler/1.0 (https://didaydo.vercel.app/)",
).strip()

SOURCE_MAX_BYTES = 20 * 1024 * 1024
TARGET_MAX_BYTES = 100 * 1024
DEFAULT_COVER_WIDTH = 1200
DEFAULT_BODY_WIDTH = 800
DEFAULT_QUALITY_STEPS = (84, 78, 72, 66, 60, 54, 48, 42, 38)
DEFAULT_WIDTH_STEPS = (1200, 1100, 1000, 900, 800, 720, 640, 600)

VIETNAMESE_MARKS = set(
    "ăâđêôơư"
    "áàảãạấầẩẫậắằẳẵặ"
    "éèẻẽẹếềểễệ"
    "íìỉĩị"
    "óòỏõọốồổỗộớờởỡợ"
    "úùủũụứừửữự"
    "ýỳỷỹỵ"
)


class ImageProcessingError(RuntimeError):
    """The source image cannot safely be downloaded or converted."""


class BlobUploadError(RuntimeError):
    """A processed image could not be stored in Vercel Blob."""


def _plain(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return " ".join(_plain(item) for item in value if item is not None)
    if isinstance(value, dict):
        return " ".join(_plain(item) for item in value.values() if item is not None)
    return re.sub(r"\s+", " ", str(value)).strip()


def slugify_filename(value: str, max_length: int = 90) -> str:
    """Create a short, lowercase, unaccented, hyphen-separated filename stem."""
    text = unicodedata.normalize("NFKD", _plain(value).casefold())
    text = text.replace("đ", "d")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    text = re.sub(r"-{2,}", "-", text)
    return (text[:max_length].rstrip("-") or "anh-du-lich")


def build_vietnamese_alt_text(image_metadata: dict, article: dict) -> str:
    """Prefer a Vietnamese image description; otherwise use a truthful page-context alt."""
    candidate_alt = _plain(
        image_metadata.get("alt")
        or image_metadata.get("caption")
        or image_metadata.get("title")
    )
    article_title = _plain(
        article.get("visual_search_title")
        or article.get("seo_title")
        or article.get("source_title")
    )
    destination = _plain(article.get("destination_city") or article.get("destination"))
    country = _plain(article.get("destination_country"))
    location = ", ".join(part for part in (destination, country) if part)

    has_vietnamese = any(ch in VIETNAMESE_MARKS for ch in candidate_alt.casefold())
    if candidate_alt and has_vietnamese:
        alt = candidate_alt
    elif article_title:
        alt = f"Ảnh minh họa cho bài viết: {article_title}"
    elif candidate_alt:
        alt = f"Ảnh minh họa: {candidate_alt}"
    else:
        alt = "Ảnh minh họa cho bài viết du lịch"

    if location and location.casefold() not in alt.casefold():
        alt = f"{alt} tại {location}"
    return alt[:280].strip()


def _has_watermark_hint(metadata: dict, source_url: str) -> bool:
    """Reject explicit preview/watermark hints; this does not inspect pixels or erase marks."""
    text = " ".join(
        _plain(metadata.get(key))
        for key in ("title", "description", "caption", "alt", "tags_text", "provider", "creator")
    )
    text += " " + _plain(source_url)
    return bool(re.search(
        r"\b(watermarked|watermark|preview[- ]only|sample[- ]image|proof[- ]only|logo|brandmark|brand[- ]logo)\b",
        text,
        flags=re.IGNORECASE,
    ))


def _is_public_https_url(url: str) -> bool:
    from image_finder import _public_https_url
    return _public_https_url(url)


def _request_logo_review(preview_bytes: bytes) -> dict:
    """Ask Gemini Vision to reject photos containing a visible logo or watermark."""
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise ImageProcessingError(
            "Thiếu GEMINI_API_KEY để kiểm tra logo/watermark trong ảnh nguồn."
        )

    model = (
        os.getenv("IMAGE_REVIEW_GEMINI_MODEL")
        or os.getenv("GEMINI_MODEL")
        or "gemini-3.8-flash"
    ).strip()
    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=model,
            contents=[
                (
                    "Inspect this travel photo for visible logos or watermarks. "
                    "Return JSON with has_logo_or_watermark (boolean), confidence "
                    "(high, medium, or low), reason (short string), and marks (array). "
                    "For every visible logo/watermark, return one marks item with "
                    "bbox as [x_min,y_min,x_max,y_max] normalized from 0 to 1000, "
                    "where x is horizontal and y is vertical; also include kind "
                    "(logo, watermark, or text_mark). Box the smallest complete "
                    "visible mark, not the underlying object. Include every mark. "
                    "If none are visible, return marks as []. If uncertain about "
                    "presence or location, say so and use low confidence. Do not "
                    "judge copyright or image ownership."
                ),
                types.Part.from_bytes(data=preview_bytes, mime_type="image/jpeg"),
            ],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0,
                max_output_tokens=320,
            ),
        )
        raw = (response.text or "").strip()
        if not raw:
            raise ValueError("empty vision response")
        review = json.loads(raw)
        if not isinstance(review, dict):
            raise ValueError("invalid vision response")
        marks = []
        raw_marks = review.get("marks") if isinstance(review.get("marks"), list) else []
        for item in raw_marks[:8]:
            if not isinstance(item, dict):
                continue
            raw_box = item.get("bbox")
            if not isinstance(raw_box, (list, tuple)) or len(raw_box) != 4:
                continue
            try:
                x1, y1, x2, y2 = [max(0.0, min(1000.0, float(value))) for value in raw_box]
            except (TypeError, ValueError):
                continue
            if x2 <= x1 or y2 <= y1:
                continue
            marks.append({
                "bbox": [x1, y1, x2, y2],
                "kind": _plain(item.get("kind") or "logo")[:40],
            })
        return {
            "has_logo_or_watermark": review.get("has_logo_or_watermark"),
            "confidence": _plain(review.get("confidence")).casefold(),
            "reason": _plain(review.get("reason"))[:240],
            "marks": marks,
            "model": model,
        }
    except ImageProcessingError:
        raise
    except Exception as exc:
        raise ImageProcessingError(
            f"Không thể kiểm tra logo/watermark bằng AI ({type(exc).__name__})."
        ) from None


def verify_no_visible_logo(source_bytes: bytes) -> dict:
    """Fail closed unless image vision confidently reports no visible logo/watermark."""
    if not source_bytes:
        raise ImageProcessingError("Không có dữ liệu ảnh để kiểm tra logo.")

    try:
        with Image.open(io.BytesIO(source_bytes)) as opened:
            if opened.format not in {"JPEG", "PNG", "WEBP", "BMP", "TIFF"}:
                raise ImageProcessingError("Định dạng ảnh không được hỗ trợ để kiểm tra logo.")
            preview = ImageOps.exif_transpose(opened).convert("RGB")
            preview.thumbnail((768, 768), Image.Resampling.LANCZOS)
            output = io.BytesIO()
            preview.save(output, format="JPEG", quality=82, optimize=True)
            preview.close()
            preview_bytes = output.getvalue()
    except ImageProcessingError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise ImageProcessingError(
            f"Không tạo được ảnh xem xét logo ({type(exc).__name__})."
        ) from None

    review = _request_logo_review(preview_bytes)
    if review.get("has_logo_or_watermark") is not False:
        reason = _plain(review.get("reason")) or "Ảnh có dấu hiệu logo/watermark."
        raise ImageProcessingError(f"Loại ảnh có logo/watermark hoặc kết quả không rõ: {reason}")
    if review.get("confidence") != "high":
        reason = _plain(review.get("reason")) or "Không đủ độ tin cậy để xác nhận ảnh sạch logo."
        raise ImageProcessingError(f"Không xác nhận được ảnh sạch logo: {reason}")
    return {
        "status": "no_visible_logo",
        "confidence": "high",
        "model": _plain(review.get("model")),
        "reason": _plain(review.get("reason"))[:240],
    }


def _make_logo_review_preview(source_bytes: bytes) -> bytes:
    """Create the same bounded preview used for both initial and final visual checks."""
    try:
        with Image.open(io.BytesIO(source_bytes)) as opened:
            if opened.format not in {"JPEG", "PNG", "WEBP", "BMP", "TIFF"}:
                raise ImageProcessingError("Định dạng ảnh không được hỗ trợ để kiểm tra logo.")
            preview = ImageOps.exif_transpose(opened).convert("RGB")
            preview.thumbnail((768, 768), Image.Resampling.LANCZOS)
            output = io.BytesIO()
            preview.save(output, format="JPEG", quality=82, optimize=True)
            preview.close()
            return output.getvalue()
    except ImageProcessingError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise ImageProcessingError(
            f"Không tạo được ảnh xem xét logo ({type(exc).__name__})."
        ) from None


def _pixel_boxes(marks: list[dict], width: int, height: int) -> list[tuple[int, int, int, int]]:
    boxes = []
    for mark in marks:
        raw = mark.get("bbox") if isinstance(mark, dict) else None
        if not isinstance(raw, (list, tuple)) or len(raw) != 4:
            continue
        x1, y1, x2, y2 = raw
        box = (
            max(0, min(width - 1, round(float(x1) * width / 1000))),
            max(0, min(height - 1, round(float(y1) * height / 1000))),
            max(1, min(width, round(float(x2) * width / 1000))),
            max(1, min(height, round(float(y2) * height / 1000))),
        )
        if box[2] > box[0] and box[3] > box[1]:
            boxes.append(box)
    return boxes


def _crop_or_inpaint_logo_marks(source_bytes: bytes, marks: list[dict]) -> tuple[bytes, list[str]]:
    """Remove small visible marks by safe edge cropping or localized OpenCV inpainting."""
    try:
        import cv2
        import numpy as np
    except ImportError as exc:
        raise ImageProcessingError(
            "Thiếu OpenCV để xử lý logo/watermark; không thể tự ý đăng ảnh còn dấu."
        ) from exc

    try:
        with Image.open(io.BytesIO(source_bytes)) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGB")
            image.load()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise ImageProcessingError(
            f"Không giải mã được ảnh để xử lý logo ({type(exc).__name__})."
        ) from None

    boxes = _pixel_boxes(marks, image.width, image.height)
    if not boxes:
        image.close()
        raise ImageProcessingError("AI phát hiện logo nhưng không trả được vùng tọa độ hợp lệ.")

    actions: list[str] = []
    for original_box in boxes:
        width, height = image.size
        x1, y1, x2, y2 = original_box
        if x1 >= width or y1 >= height or x2 <= 0 or y2 <= 0:
            continue
        x1, x2 = max(0, x1), min(width, x2)
        y1, y2 = max(0, y1), min(height, y2)
        box_width, box_height = x2 - x1, y2 - y1
        if box_width <= 0 or box_height <= 0:
            continue

        padding = max(5, round(max(box_width, box_height) * 0.22))
        edge_crops = []
        if x1 <= width * 0.04:
            cut = min(width, x2 + padding)
            edge_crops.append(("crop_left", cut, cut / width))
        if x2 >= width * 0.96:
            cut = max(0, x1 - padding)
            edge_crops.append(("crop_right", width - cut, (width - cut) / width))
        if y1 <= height * 0.04:
            cut = min(height, y2 + padding)
            edge_crops.append(("crop_top", cut, cut / height))
        if y2 >= height * 0.96:
            cut = max(0, y1 - padding)
            edge_crops.append(("crop_bottom", height - cut, (height - cut) / height))

        safe_crops = [
            item for item in edge_crops
            if item[2] <= 0.14
            and (width - item[1] >= 300 if item[0] in {"crop_left", "crop_right"} else height - item[1] >= 200)
        ]
        if safe_crops:
            direction, cut, _ratio = min(safe_crops, key=lambda item: item[2])
            if direction == "crop_left":
                image = image.crop((cut, 0, width, height))
                boxes = [(a - cut, b, c - cut, d) for a, b, c, d in boxes]
            elif direction == "crop_right":
                image = image.crop((0, 0, width - cut, height))
                boxes = [(a, b, c, d) for a, b, c, d in boxes]
            elif direction == "crop_top":
                image = image.crop((0, cut, width, height))
                boxes = [(a, b - cut, c, d - cut) for a, b, c, d in boxes]
            else:
                image = image.crop((0, 0, width, height - cut))
                boxes = [(a, b, c, d) for a, b, c, d in boxes]
            actions.append(direction)
            continue

        # Inpainting is deliberately limited to small marks. Large or central
        # translucent watermarks are not reliably reconstructable without damage.
        if (
            box_width > width * 0.12
            or box_height > height * 0.12
            or (box_width * box_height) > (width * height * 0.018)
        ):
            image.close()
            raise ImageProcessingError(
                "Logo/watermark quá lớn hoặc nằm sâu trong ảnh; cắt/xóa tự động có thể làm hỏng ảnh."
            )

        left = max(0, x1 - padding)
        top = max(0, y1 - padding)
        right = min(width, x2 + padding)
        bottom = min(height, y2 + padding)
        rgb = np.asarray(image, dtype=np.uint8)
        mask = np.zeros((height, width), dtype=np.uint8)
        cv2.rectangle(mask, (left, top), (right - 1, bottom - 1), 255, thickness=-1)
        repaired = cv2.inpaint(rgb, mask, inpaintRadius=5, flags=cv2.INPAINT_TELEA)
        image.close()
        image = Image.fromarray(repaired, mode="RGB")
        actions.append("inpaint")

    if image.width < 300 or image.height < 200:
        image.close()
        raise ImageProcessingError("Cắt logo khiến ảnh còn lại quá nhỏ để xuất bản.")

    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    image.close()
    return output.getvalue(), actions


def clean_visible_logo_marks(source_bytes: bytes) -> tuple[bytes, dict]:
    """Crop edge logos or inpaint small internal marks, then visually verify the result."""
    if not source_bytes:
        raise ImageProcessingError("Không có dữ liệu ảnh để kiểm tra logo.")

    initial = _request_logo_review(_make_logo_review_preview(source_bytes))
    if initial.get("has_logo_or_watermark") is False:
        if initial.get("confidence") != "high":
            raise ImageProcessingError("Không đủ độ tin cậy để xác nhận ảnh sạch logo.")
        return source_bytes, {
            "status": "no_visible_logo",
            "confidence": "high",
            "model": _plain(initial.get("model")),
            "actions": [],
            "reason": _plain(initial.get("reason"))[:240],
        }

    if initial.get("has_logo_or_watermark") is not True:
        raise ImageProcessingError("AI không xác định rõ ảnh có logo/watermark hay không.")
    if initial.get("confidence") not in {"high", "medium"}:
        raise ImageProcessingError("AI chưa xác định đủ rõ vị trí logo/watermark để xử lý an toàn.")

    cleaned_bytes, actions = _crop_or_inpaint_logo_marks(
        source_bytes,
        initial.get("marks") or [],
    )
    final_review = _request_logo_review(_make_logo_review_preview(cleaned_bytes))
    if (
        final_review.get("has_logo_or_watermark") is not False
        or final_review.get("confidence") != "high"
    ):
        raise ImageProcessingError(
            "Ảnh vẫn có dấu logo/watermark hoặc kết quả kiểm tra sau xử lý chưa đủ chắc chắn."
        )

    return cleaned_bytes, {
        "status": "no_visible_logo",
        "confidence": "high",
        "model": _plain(final_review.get("model") or initial.get("model")),
        "actions": actions,
        "reason": _plain(final_review.get("reason"))[:240],
    }


def download_image_bytes(url: str, max_bytes: int = SOURCE_MAX_BYTES) -> bytes:
    """Download an image with bounded size, HTTPS-only redirects, and public-host checks."""
    current_url = _plain(url)
    if not _is_public_https_url(current_url):
        raise ImageProcessingError("Ảnh nguồn không phải URL HTTPS công khai hợp lệ.")

    for _ in range(5):
        try:
            response = requests.get(
                current_url,
                headers={"User-Agent": USER_AGENT},
                stream=True,
                allow_redirects=False,
                timeout=(6, 25),
            )
        except requests.RequestException as exc:
            raise ImageProcessingError(
                f"Không tải được ảnh nguồn ({type(exc).__name__})."
            ) from None

        if response.status_code in {301, 302, 303, 307, 308}:
            next_url = urljoin(current_url, response.headers.get("Location", ""))
            response.close()
            if not _is_public_https_url(next_url):
                raise ImageProcessingError("Ảnh nguồn chuyển hướng tới URL không an toàn.")
            current_url = next_url
            continue

        try:
            if response.status_code != 200:
                raise ImageProcessingError(
                    f"Máy chủ ảnh trả HTTP {response.status_code}."
                )
            content_type = (response.headers.get("Content-Type") or "").split(";", 1)[0].lower()
            if content_type and (
                not content_type.startswith("image/")
                or content_type in {"image/svg+xml", "image/gif"}
            ):
                raise ImageProcessingError("Nguồn không phải ảnh raster tĩnh được hỗ trợ.")

            declared_size = response.headers.get("Content-Length")
            if declared_size:
                try:
                    if int(declared_size) > max_bytes:
                        raise ImageProcessingError("Ảnh gốc vượt giới hạn tải xuống 20 MB.")
                except ValueError:
                    pass

            chunks = []
            total = 0
            for chunk in response.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                total += len(chunk)
                if total > max_bytes:
                    raise ImageProcessingError("Ảnh gốc vượt giới hạn tải xuống 20 MB.")
                chunks.append(chunk)
            payload = b"".join(chunks)
            if not payload:
                raise ImageProcessingError("Ảnh nguồn rỗng.")
            return payload
        finally:
            response.close()

    raise ImageProcessingError("Ảnh nguồn chuyển hướng quá nhiều lần.")


def optimize_image_bytes(
    source_bytes: bytes,
    *,
    max_width: int = DEFAULT_COVER_WIDTH,
    max_bytes: int = TARGET_MAX_BYTES,
) -> dict:
    """Normalize orientation, resize, strip EXIF, and encode a compact WebP."""
    if not source_bytes:
        raise ImageProcessingError("Dữ liệu ảnh rỗng.")
    try:
        with Image.open(io.BytesIO(source_bytes)) as opened:
            if opened.format not in {"JPEG", "PNG", "WEBP", "BMP", "TIFF"}:
                raise ImageProcessingError(
                    f"Định dạng ảnh không được hỗ trợ: {opened.format or 'unknown'}."
                )
            if getattr(opened, "is_animated", False) and getattr(opened, "n_frames", 1) > 1:
                raise ImageProcessingError("Không dùng ảnh động làm ảnh bìa.")
            width, height = opened.size
            if width < 300 or height < 200:
                raise ImageProcessingError("Ảnh nguồn có kích thước quá nhỏ.")
            if width * height > 40_000_000:
                raise ImageProcessingError("Ảnh nguồn vượt giới hạn 40 megapixel.")
            opened.load()
            icc_profile = opened.info.get("icc_profile")
            oriented = ImageOps.exif_transpose(opened)

            has_alpha = (
                "A" in oriented.getbands()
                and oriented.getchannel("A").getextrema()[0] < 255
            )
            base_mode = "RGBA" if has_alpha else "RGB"
            image = oriented.convert(base_mode)

    except ImageProcessingError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise ImageProcessingError(
            f"Không giải mã được ảnh nguồn ({type(exc).__name__})."
        ) from None

    max_width = max(320, min(int(max_width), 2400))
    max_bytes = max(20_000, min(int(max_bytes), 500_000))
    widths = []
    for width in DEFAULT_WIDTH_STEPS:
        candidate_width = min(max_width, width)
        if candidate_width not in widths:
            widths.append(candidate_width)
    if max_width not in widths:
        widths.insert(0, max_width)

    best = None
    for target_width in widths:
        working = image.copy()
        if working.width > target_width:
            target_height = max(1, round(working.height * target_width / working.width))
            working = working.resize(
                (target_width, target_height),
                Image.Resampling.LANCZOS,
            )

        for quality in DEFAULT_QUALITY_STEPS:
            output = io.BytesIO()
            save_options = {
                "format": "WEBP",
                "quality": quality,
                "method": 6,
            }
            if icc_profile:
                save_options["icc_profile"] = icc_profile
            try:
                working.save(output, **save_options)
            except (OSError, ValueError) as exc:
                raise ImageProcessingError(
                    f"Không mã hóa được WebP ({type(exc).__name__})."
                ) from None

            encoded = output.getvalue()
            candidate = {
                "data": encoded,
                "width": working.width,
                "height": working.height,
                "size_bytes": len(encoded),
                "quality": quality,
                "target_met": len(encoded) <= max_bytes,
            }
            if best is None or len(encoded) < best["size_bytes"]:
                best = candidate
            if len(encoded) <= max_bytes:
                image.close()
                working.close()
                return candidate
        working.close()

    image.close()
    if best is None:
        raise ImageProcessingError("Không tạo được ảnh WebP.")
    log.warning(
        "WebP vẫn vượt mục tiêu dung lượng: %s KB (mục tiêu %s KB).",
        round(best["size_bytes"] / 1024, 1),
        round(max_bytes / 1024, 1),
    )
    return best


def upload_webp_to_vercel_blob(data: bytes, filename: str) -> dict:
    """Send an optimized WebP to the authenticated Didaydo API; Vercel uploads via OIDC."""
    site_url = os.getenv("SITE_URL", os.getenv("NEXT_PUBLIC_SITE_URL", "")).strip().rstrip("/")
    api_key = os.getenv("SITE_INGEST_API_KEY", "").strip()
    if not site_url.startswith("https://"):
        raise BlobUploadError("SITE_URL phải là địa chỉ HTTPS của website.")
    if not api_key or len(api_key) < 24:
        raise BlobUploadError("SITE_INGEST_API_KEY chưa được cấu hình hợp lệ.")
    if len(data) > TARGET_MAX_BYTES * 5:
        raise BlobUploadError("Ảnh WebP vượt giới hạn 500 KB của endpoint upload.")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,89}-[a-f0-9]{12}\.webp", filename):
        raise BlobUploadError("Tên file WebP không đúng định dạng SEO đã chuẩn hóa.")

    try:
        timeout_seconds = max(5, min(int(os.getenv("SITE_API_TIMEOUT_SECONDS", "30")), 60))
    except ValueError:
        timeout_seconds = 30

    endpoint = f"{site_url}/api/internal/images"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "image/webp",
        "Accept": "application/json",
        "X-Image-Filename": filename,
        "User-Agent": "TravelContentBot/1.0",
    }
    try:
        response = requests.post(
            endpoint, headers=headers, data=data, timeout=(8, timeout_seconds)
        )
    except requests.RequestException as exc:
        raise BlobUploadError(
            f"Không kết nối được API lưu ảnh ({type(exc).__name__})."
        ) from None

    try:
        result = response.json()
    except ValueError:
        raise BlobUploadError("API lưu ảnh không trả JSON hợp lệ.") from None

    if not response.ok or not isinstance(result, dict) or result.get("ok") is not True:
        raise BlobUploadError(
            f"API lưu ảnh từ chối yêu cầu (HTTP {response.status_code})."
        )
    image_url = _plain(result.get("url"))
    pathname = _plain(result.get("pathname"))
    if not image_url.startswith("https://") or not pathname.startswith("images/covers/"):
        raise BlobUploadError("API lưu ảnh trả về URL hoặc pathname không hợp lệ.")

    return {"url": image_url, "pathname": pathname}


def process_and_upload_cover_image(
    candidate: dict,
    article: dict,
    *,
    max_width: int = DEFAULT_COVER_WIDTH,
    max_bytes: int = TARGET_MAX_BYTES,
) -> dict:
    """Download, optimize, name, alt, and upload one rights-checked cover candidate."""
    source_url = _plain(candidate.get("original_url") or candidate.get("url"))
    source_bytes = download_image_bytes(source_url)
    if _has_watermark_hint(candidate, source_url):
        log.info("Ảnh có metadata gợi ý logo/watermark; sẽ thử crop/inpainting rồi kiểm tra lại.")
    source_bytes, logo_review = clean_visible_logo_marks(source_bytes)
    optimized = optimize_image_bytes(
        source_bytes,
        max_width=max_width,
        max_bytes=max_bytes,
    )
    title = _plain(
        article.get("visual_search_title")
        or article.get("seo_title")
        or article.get("source_title")
        or candidate.get("title")
    )
    digest = hashlib.sha256(optimized["data"]).hexdigest()[:12]
    filename = f"{slugify_filename(title)}-{digest}.webp"
    uploaded = upload_webp_to_vercel_blob(optimized["data"], filename)

    result = dict(candidate)
    result.update({
        "original_url": source_url,
        "url": uploaded["url"],
        "asset_storage": "vercel_blob",
        "asset_pathname": uploaded["pathname"],
        "optimized_filename": filename,
        "processed_format": "webp",
        "width": optimized["width"],
        "height": optimized["height"],
        "file_size_bytes": optimized["size_bytes"],
        "compression_quality": optimized["quality"],
        "target_size_met": optimized["target_met"],
        "alt": build_vietnamese_alt_text(candidate, article),
        "watermark_policy": "cropped_or_inpainted_when_safe; final_vision_check_passed",
        "logo_review": logo_review,
    })
    log.info(
        "Cover image stored: file=%s size=%.1fKB dimensions=%sx%s target_met=%s",
        filename,
        optimized["size_bytes"] / 1024,
        optimized["width"],
        optimized["height"],
        optimized["target_met"],
    )
    return result


def optimize_local_image(
    source_path: str | Path,
    output_dir: str | Path,
    *,
    max_width: int = DEFAULT_BODY_WIDTH,
    max_bytes: int = TARGET_MAX_BYTES,
) -> dict:
    """Batch-tool helper for local files; does not upload or change the source file."""
    source = Path(source_path)
    payload = source.read_bytes()
    optimized = optimize_image_bytes(payload, max_width=max_width, max_bytes=max_bytes)
    digest = hashlib.sha256(optimized["data"]).hexdigest()[:12]
    filename = f"{slugify_filename(source.stem)}-{digest}.webp"
    output_path = Path(output_dir) / filename
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(optimized["data"])
    alt = build_vietnamese_alt_text(
        {"title": source.stem, "caption": source.stem},
        {"visual_search_title": source.stem},
    )
    return {
        "source": str(source),
        "output": str(output_path),
        "filename": filename,
        "alt": alt,
        "width": optimized["width"],
        "height": optimized["height"],
        "size_bytes": optimized["size_bytes"],
        "target_met": optimized["target_met"],
    }
