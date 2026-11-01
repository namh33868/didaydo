"""Lightweight image metadata and optional WebP utilities for DiDayDo.

Normal article publishing keeps source image URLs unchanged and never downloads source
photos. The optional local/WebP utilities remain available for explicit offline jobs.
"""
from __future__ import annotations

import hashlib
import io
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
    """Return whether metadata suggests a mark; visual review decides whether to edit or reject."""
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
    if _has_watermark_hint(candidate, source_url):
        raise ImageProcessingError(
            "Metadata ảnh cho biết đây là watermark/preview; bỏ ứng viên thay vì xử lý ảnh."
        )
    source_bytes = download_image_bytes(source_url)
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
        "watermark_policy": "metadata_hints_checked_only",
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
