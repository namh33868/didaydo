"""Batch rename and optimize local image files into SEO-friendly WebP assets."""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from image_optimizer import ImageProcessingError, optimize_local_image

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
SUPPORTED_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Batch convert images to WebP, resize, compress, and rename for SEO."
    )
    parser.add_argument("input_dir", type=Path, help="Folder containing source images.")
    parser.add_argument("output_dir", type=Path, help="Folder for optimized WebP files.")
    parser.add_argument("--max-width", type=int, default=800, help="Default 800px for article/body images.")
    parser.add_argument("--max-bytes", type=int, default=102400, help="Target output size; default 100 KB.")
    args = parser.parse_args()

    if not args.input_dir.is_dir():
        parser.error(f"Input directory does not exist: {args.input_dir}")

    files = sorted(
        path for path in args.input_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest = []
    failures = 0

    for source in files:
        try:
            result = optimize_local_image(
                source,
                args.output_dir,
                max_width=args.max_width,
                max_bytes=args.max_bytes,
            )
            manifest.append(result)
            logging.info(
                "%s -> %s | %.1f KB | %sx%s | target_met=%s",
                source.name,
                result["filename"],
                result["size_bytes"] / 1024,
                result["width"],
                result["height"],
                result["target_met"],
            )
        except (OSError, ImageProcessingError) as exc:
            failures += 1
            logging.warning("Bỏ qua %s (%s)", source.name, exc)

    manifest_path = args.output_dir / "image-manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logging.info(
        "Hoàn tất: %s ảnh xử lý, %s lỗi. Manifest: %s",
        len(manifest),
        failures,
        manifest_path,
    )
    return 1 if failures and not manifest else 0


if __name__ == "__main__":
    raise SystemExit(main())
