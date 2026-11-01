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
        for key in ("title", "description", "caption", "tags_text", "provider")
    )
    text += " " + _plain(source_url)
    return bool(re.search(
        r"\b(watermarked|watermark|preview[- ]only|sample[- ]image|proof[- ]only)\b",
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
    """Upload an already optimized WebP to a public Vercel Blob store."""
    if not os.getenv("BLOB_READ_WRITE_TOKEN", "").strip():
        raise BlobUploadError(
            "Thiếu GitHub Actions secret BLOB_READ_WRITE_TOKEN cho Vercel Blob."
        )
    try:
        from vercel.blob.sync import put_blob
    except ImportError as exc:
        raise BlobUploadError(
            "Thiếu package vercel-blob; cài dependencies từ crawler/requirements.txt."
        ) from exc

    pathname = f"images/covers/{filename}"
    try:
        uploaded = put_blob(
            pathname,
            data,
            access="public",
            content_type="image/webp",
            add_random_suffix=False,
            allow_overwrite=True,
            cache_control_max_age=31_536_000,
        )
    except Exception as exc:
        raise BlobUploadError(
            f"Không tải được ảnh lên Vercel Blob ({type(exc).__name__})."
        ) from None
    return {"url": uploaded.url, "pathname": uploaded.pathname}


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
            "Metadata ảnh có dấu hiệu watermark/preview; loại ứng viên, không xóa watermark."
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
        "watermark_policy": "not_removed; metadata_hints_checked",
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
