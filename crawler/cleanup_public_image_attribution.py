"""One-time authenticated cleanup for legacy public image-attribution captions."""
from __future__ import annotations

import os
import sys

import requests


def main() -> int:
    site_url = os.getenv("SITE_URL", "").strip().rstrip("/")
    api_key = os.getenv("SITE_INGEST_API_KEY", "").strip()
    if not site_url.startswith(("https://", "http://")):
        print("SITE_URL is missing or invalid.", file=sys.stderr)
        return 2
    if len(api_key) < 24:
        print("SITE_INGEST_API_KEY is missing or invalid.", file=sys.stderr)
        return 2

    endpoint = f"{site_url}/api/ingest/posts"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "User-Agent": "Didaydo-Legacy-Image-Attribution-Cleanup/1.0",
    }
    cursor: str | None = None
    scanned = updated = captions_removed = batches = 0

    while True:
        params: dict[str, str | int] = {
            "cleanupImageAttribution": "1",
            "limit": 250,
        }
        if cursor:
            params["after"] = cursor
        try:
            response = requests.get(endpoint, headers=headers, params=params, timeout=(10, 60))
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            print(f"Cleanup request failed: {type(exc).__name__}", file=sys.stderr)
            return 1

        if payload.get("success") is not True:
            print("Cleanup API returned an unexpected response.", file=sys.stderr)
            return 1

        batch_scanned = int(payload.get("scanned", 0) or 0)
        batch_updated = int(payload.get("updated", 0) or 0)
        batch_removed = int(payload.get("captionsRemoved", 0) or 0)
        next_cursor = payload.get("nextCursor")

        scanned += batch_scanned
        updated += batch_updated
        captions_removed += batch_removed
        batches += 1
        print(
            f"Batch {batches}: scanned={batch_scanned}, "
            f"posts_updated={batch_updated}, captions_removed={batch_removed}"
        )

        if not next_cursor:
            break
        if not isinstance(next_cursor, str) or next_cursor == cursor:
            print("Cleanup cursor did not advance; stopping safely.", file=sys.stderr)
            return 1
        cursor = next_cursor

    print(
        "Legacy image attribution cleanup completed: "
        f"scanned={scanned}, posts_updated={updated}, captions_removed={captions_removed}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
