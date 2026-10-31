"""Find SEO cover images from openly licensed libraries with strict location matching.

Only CC0/Public Domain and CC BY/CC BY-SA images are considered. Location-specific
matches require the place name in the image's own title, description, or tags. When
that cannot be established, the fallback is explicitly labelled as a generic topic
illustration and never claims to depict the destination.
"""
from __future__ import annotations

import html
import logging
import os
import re
import unicodedata
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

log = logging.getLogger("travel-content-bot.images")

COMMONS_API = "https://commons.wikimedia.org/w/api.php"
OPENVERSE_API = "https://api.openverse.org/v1/images/"
REQUEST_TIMEOUT = (5, 18)
MIN_WIDTH = 1200
MIN_HEIGHT = 600
MAX_RESULTS = 30

_USER_AGENT = os.getenv(
    "CRAWLER_USER_AGENT",
    "DiDayDoTravelCrawler/1.0 (https://didaydo.vercel.app/)",
).strip()


def _plain(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return " ".join(_plain(item) for item in value if item is not None)
    if isinstance(value, dict):
        return " ".join(_plain(item) for item in value.values() if item is not None)
    return re.sub(r"\s+", " ", str(value)).strip()


def _normalise(value: str) -> str:
    text = unicodedata.normalize("NFKD", _plain(value).casefold())
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.replace("đ", "d")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _contains_phrase(haystack: str, phrase: str) -> bool:
    haystack_norm = _normalise(haystack)
    phrase_norm = _normalise(phrase)
    if not haystack_norm or not phrase_norm:
        return False
    return bool(re.search(
        r"(?<![a-z0-9])" + re.escape(phrase_norm) + r"(?![a-z0-9])",
        haystack_norm,
    ))


def _clean_html(value: str) -> str:
    if not value:
        return ""
    soup = BeautifulSoup(str(value), "html.parser")
    return html.unescape(soup.get_text(" ", strip=True))


def is_license_allowed(license_name: str) -> bool:
    """Allow commercial-friendly CC0/PD/CC BY/CC BY-SA; reject NC and ND."""
    value = _normalise(license_name)
    if not value:
        return False
    if any(token in value.split() for token in ("nc", "nd", "noncommercial", "noderivatives")):
        return False
    if "public domain" in value or "public domain mark" in value or "cc0" in value or value == "pdm":
        return True
    return bool(re.search(r"\bcc by(?: sa)?\b", value))


def _license_allowed_code(code: str) -> bool:
    value = _normalise(code)
    return value in {"cc0", "pdm", "by", "by sa"}


def _destination_terms(article: dict) -> list[str]:
    city = _plain(article.get("destination_city") or article.get("destination") or "")
    if not city or _normalise(city) in {"world", "vietnam", "viet nam", "unclassified", "chua phan loai"}:
        return []
    terms = [city]
    normalized = _normalise(city)
    aliases = {
        "ha long": ["Ha Long Bay"],
        "hoi an": ["Hoi An Ancient Town"],
        "ho chi minh": ["Ho Chi Minh City", "Saigon"],
        "ho chi minh city": ["Saigon"],
        "da nang": ["Danang"],
    }
    terms.extend(aliases.get(normalized, []))
    # Longer phrases should win when ranking, but the city alias remains mandatory evidence.
    return list(dict.fromkeys(sorted(terms, key=len, reverse=True)))


def _country_terms(article: dict) -> list[str]:
    country = _plain(article.get("destination_country") or "")
    if not country or _normalise(country) in {"world", "world chua phan loai", "unclassified", "chua phan loai"}:
        return []
    aliases = {
        "vietnam": ["Vietnam", "Viet Nam"],
        "viet nam": ["Viet Nam", "Vietnam"],
        "united states": ["United States", "USA"],
        "united kingdom": ["United Kingdom", "UK"],
    }
    return list(dict.fromkeys([country] + aliases.get(_normalise(country), [])))


_TOPIC_CONFIG = {
    "food-and-drink": {
        "query": "local food cuisine dishes",
        "terms": ["food", "cuisine", "dish", "street food", "restaurant", "market", "noodles", "seafood", "coffee"],
        "label": "ẩm thực địa phương",
    },
    "hotel-review": {
        "query": "hotel resort accommodation",
        "terms": ["hotel", "resort", "accommodation", "guesthouse", "lodge", "room", "villa"],
        "label": "khách sạn và lưu trú",
    },
    "luxury-travel": {
        "query": "luxury hotel resort",
        "terms": ["luxury", "hotel", "resort", "spa", "cruise", "villa"],
        "label": "du lịch nghỉ dưỡng",
    },
    "beach-island": {
        "query": "beach island coast",
        "terms": ["beach", "island", "coast", "seaside", "bay", "ocean"],
        "label": "biển và đảo",
    },
    "outdoor-adventure": {
        "query": "nature mountain cave waterfall",
        "terms": ["mountain", "cave", "waterfall", "hiking", "trekking", "forest", "national park", "trail"],
        "label": "thiên nhiên và khám phá",
    },
    "things-to-do": {
        "query": "tourist attraction landmark",
        "terms": ["attraction", "landmark", "sightseeing", "temple", "museum", "park", "tour"],
        "label": "điểm tham quan",
    },
    "culture-local-life": {
        "query": "local culture traditional village",
        "terms": ["culture", "traditional", "village", "festival", "craft", "market", "local life"],
        "label": "văn hóa địa phương",
    },
    "transport": {
        "query": "travel transport train ferry",
        "terms": ["train", "railway", "ferry", "bus", "airport", "motorbike", "transport", "station"],
        "label": "di chuyển du lịch",
    },
    "budget-travel": {
        "query": "budget backpack travel",
        "terms": ["backpack", "hostel", "budget", "street food", "bus", "train", "travel"],
        "label": "du lịch tiết kiệm",
    },
    "family-travel": {
        "query": "family travel resort",
        "terms": ["family", "children", "kids", "resort", "park", "travel"],
        "label": "du lịch gia đình",
    },
    "sustainable-travel": {
        "query": "eco tourism nature conservation",
        "terms": ["eco", "nature", "conservation", "sustainable", "national park", "wildlife"],
        "label": "du lịch bền vững",
    },
    "itinerary": {
        "query": "travel destination landscape",
        "terms": ["travel", "destination", "landscape", "city", "route", "sightseeing"],
        "label": "hành trình du lịch",
    },
    "destination-news": {
        "query": "travel destination landscape",
        "terms": ["travel", "destination", "tourism", "landscape"],
        "label": "điểm đến du lịch",
    },
    "travel-tips": {
        "query": "travel planning destination",
        "terms": ["travel", "destination", "tourism", "journey", "backpack"],
        "label": "kinh nghiệm du lịch",
    },
    "travel-guide": {
        "query": "travel destination landscape",
        "terms": ["travel", "destination", "tourism", "landscape", "city"],
        "label": "du lịch",
    },
}


def _topic(article: dict) -> dict:
    slug = _plain(article.get("primary_category") or "travel-guide").casefold()
    return _TOPIC_CONFIG.get(slug, _TOPIC_CONFIG["travel-guide"])


def _metadata_text(*parts) -> str:
    return " ".join(_plain(part) for part in parts if part is not None)


def _matches_any(text: str, phrases: list[str]) -> list[str]:
    return [phrase for phrase in phrases if _contains_phrase(text, phrase)]


def _image_dimensions_ok(width, height) -> bool:
    try:
        width, height = int(width), int(height)
    except (TypeError, ValueError):
        return False
    ratio = width / max(1, height)
    return width >= MIN_WIDTH and height >= MIN_HEIGHT and 1.2 <= ratio <= 2.25


def verify_image_url(url: str) -> bool:
    """Check that the chosen file URL still serves an image; never download the full file."""
    if not str(url or "").startswith("https://"):
        return False
    try:
        response = requests.get(
            url,
            headers={"User-Agent": _USER_AGENT, "Range": "bytes=0-1023"},
            stream=True,
            allow_redirects=True,
            timeout=REQUEST_TIMEOUT,
        )
        try:
            if response.status_code not in (200, 206):
                return False
            content_type = (response.headers.get("Content-Type") or "").split(";", 1)[0].lower()
            return content_type.startswith("image/")
        finally:
            response.close()
    except requests.RequestException:
        return False


def _commons_artist(metadata: dict) -> tuple[str, str]:
    raw = metadata.get("Artist", {}).get("value", "") if isinstance(metadata.get("Artist"), dict) else ""
    soup = BeautifulSoup(str(raw), "html.parser")
    anchor = soup.find("a", href=True)
    creator_url = anchor.get("href", "") if anchor else ""
    creator = soup.get_text(" ", strip=True)
    return _plain(creator)[:180], creator_url if str(creator_url).startswith("https://") else ""


def _commons_candidates(query: str) -> list[dict]:
    params = {
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrsearch": query,
        "gsrnamespace": 6,
        "gsrlimit": MAX_RESULTS,
        "prop": "imageinfo|categories",
        "iiprop": "url|size|mime|extmetadata",
        "iiurlwidth": 1600,
        "cllimit": 30,
        "clshow": "!hidden",
    }
    response = requests.get(
        COMMONS_API, params=params, headers={"User-Agent": _USER_AGENT},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    data = response.json()
    pages = (data.get("query") or {}).get("pages") or {}
    output = []
    for page in pages.values():
        info_list = page.get("imageinfo") or []
        if not info_list:
            continue
        info = info_list[0]
        mime = _plain(info.get("mime")).lower()
        if not mime.startswith("image/") or mime in {"image/svg+xml", "image/gif"}:
            continue
        width, height = info.get("width"), info.get("height")
        if not _image_dimensions_ok(width, height):
            continue
        metadata = info.get("extmetadata") or {}
        license_name = _clean_html((metadata.get("LicenseShortName") or {}).get("value", ""))
        license_url = _plain((metadata.get("LicenseUrl") or {}).get("value", ""))
        usage_terms = _clean_html((metadata.get("UsageTerms") or {}).get("value", ""))
        if not is_license_allowed(license_name or usage_terms) or not license_url.startswith("https://"):
            continue
        creator, creator_url = _commons_artist(metadata)
        if _normalise(license_name).startswith(("cc by", "cc by sa")) and not creator:
            continue
        description = _clean_html((metadata.get("ImageDescription") or {}).get("value", ""))
        title = _plain(page.get("title", "")).removeprefix("File:")
        categories = [item.get("title", "") for item in (page.get("categories") or [])]
        category_text = " ".join(categories)
        landing_url = "https://commons.wikimedia.org/wiki/" + quote(page.get("title", "").replace(" ", "_"), safe=":_()")
        image_url = _plain(info.get("thumburl") or info.get("url"))
        output.append({
            "url": image_url,
            "title": title,
            "description": description,
            "tags_text": category_text,
            "creator": creator or "Không rõ tác giả",
            "creator_url": creator_url,
            "license": license_name or usage_terms,
            "license_url": license_url,
            "source_page_url": landing_url,
            "provider": "Wikimedia Commons",
            "width": width,
            "height": height,
        })
    return output


def _openverse_candidates(query: str) -> list[dict]:
    params = {
        "q": query,
        "license_type": "commercial",
        "filter_dead": "true",
        "category": "photograph",
        "aspect_ratio": "wide",
        "size": "large",
        "page_size": 20,
    }
    response = requests.get(
        OPENVERSE_API, params=params, headers={"User-Agent": _USER_AGENT},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    data = response.json()
    output = []
    for item in data.get("results") or []:
        width, height = item.get("width"), item.get("height")
        if not _image_dimensions_ok(width, height):
            continue
        license_code = _plain(item.get("license")).lower()
        if not _license_allowed_code(license_code):
            continue
        creator = _plain(item.get("creator"))[:180]
        if license_code in {"by", "by-sa"} and not creator:
            continue
        license_url = _plain(item.get("license_url"))
        landing_url = _plain(item.get("foreign_landing_url"))
        image_url = _plain(item.get("url"))
        if not all(value.startswith("https://") for value in (license_url, landing_url, image_url)):
            continue
        tags = item.get("tags") or []
        tags_text = " ".join(_plain(tag.get("name")) for tag in tags if isinstance(tag, dict))
        version = _plain(item.get("license_version"))
        license_label = {
            "cc0": "CC0" + (f" {version}" if version else ""),
            "pdm": "Public Domain Mark",
            "by": "CC BY" + (f" {version}" if version else ""),
            "by-sa": "CC BY-SA" + (f" {version}" if version else ""),
        }.get(license_code, license_code.upper())
        output.append({
            "url": image_url,
            "title": _plain(item.get("title")),
            "description": _plain(item.get("description")),
            "tags_text": tags_text,
            "creator": creator or "Không rõ tác giả",
            "creator_url": _plain(item.get("creator_url")),
            "license": license_label,
            "license_url": license_url,
            "source_page_url": landing_url,
            "provider": "Openverse",
            "width": width,
            "height": height,
        })
    return output


def _rank_candidates(candidates: list[dict], place_terms: list[str], country_terms: list[str],
                     topic_terms: list[str], *, require_place: bool, require_country: bool = False) -> list[dict]:
    ranked = []
    for candidate in candidates:
        metadata = _metadata_text(
            candidate.get("title"), candidate.get("description"), candidate.get("tags_text")
        )
        place_matches = _matches_any(metadata, place_terms)
        country_matches = _matches_any(metadata, country_terms)
        topic_matches = _matches_any(metadata, topic_terms)
        if require_place and not place_matches:
            continue
        if not require_place and not topic_matches:
            continue
        if require_country and country_terms and not country_matches:
            continue
        # Exact place evidence outranks broad country/topic matches.
        score = (100 if place_matches else 0) + (8 if country_matches else 0) + min(12, len(topic_matches) * 3)
        score += min(4, int(candidate.get("width", 0) or 0) // 1000)
        candidate = dict(candidate)
        candidate["_score"] = score
        candidate["_place_match"] = place_matches[0] if place_matches else ""
        candidate["_country_match"] = country_matches[0] if country_matches else ""
        ranked.append(candidate)
    return sorted(ranked, key=lambda item: item.get("_score", 0), reverse=True)


def _make_cover(candidate: dict, article: dict, scope: str) -> dict:
    city = _plain(article.get("destination_city") or "")
    country = _plain(article.get("destination_country") or "")
    topic = _topic(article)
    if scope == "exact_destination":
        label = ", ".join(part for part in (city, country) if part)
        alt = f"{label} – {candidate.get('title') or topic['label']}"[:300]
    elif scope == "country_topic":
        alt = f"Ảnh minh họa {topic['label']} tại {country}"[:300]
    else:
        alt = f"Ảnh minh họa {topic['label']}"[:300]
    return {
        "image_id": "COVER_LIBRARY",
        "url": candidate["url"],
        "alt": alt,
        "caption": _plain(candidate.get("title"))[:400],
        "credit": _plain(candidate.get("creator"))[:180],
        "credit_source": candidate.get("provider"),
        "source_name": candidate.get("provider"),
        "source_page_url": candidate.get("source_page_url"),
        "creator_url": candidate.get("creator_url"),
        "license": candidate.get("license"),
        "license_url": candidate.get("license_url"),
        "width": candidate.get("width"),
        "height": candidate.get("height"),
        "rights_status": "license_metadata_checked",
        "is_cover": True,
        "image_scope": scope,
        "place_evidence": candidate.get("_place_match") or None,
    }


def find_cover_image(article: dict) -> dict | None:
    """Return a verified-by-metadata cover, or None; never guess a specific location."""
    article = article or {}
    place_terms = _destination_terms(article)
    country_terms = _country_terms(article)
    topic = _topic(article)
    topic_terms = topic["terms"]
    country = _plain(article.get("destination_country") or "")

    place_queries = []
    if place_terms:
        primary_place = place_terms[0]
        place_queries = list(dict.fromkeys([
            f"{primary_place} {country}".strip(),
            primary_place,
        ]))

    for query in place_queries:
        for provider_name, search_fn in (
            ("Wikimedia Commons", _commons_candidates),
            ("Openverse", _openverse_candidates),
        ):
            try:
                ranked = _rank_candidates(
                    search_fn(query), place_terms, country_terms, topic_terms,
                    require_place=True,
                )
            except (requests.RequestException, ValueError, KeyError) as exc:
                log.warning("%s location image search failed (%s)", provider_name, type(exc).__name__)
                continue
            for candidate in ranked[:8]:
                if verify_image_url(candidate.get("url", "")):
                    cover = _make_cover(candidate, article, "exact_destination")
                    log.info("Cover image selected: provider=%s scope=exact_destination place=%s", provider_name, cover.get("place_evidence"))
                    return cover

    # Fallbacks are intentionally generic. The alt text never says this image depicts
    # the city when its own metadata cannot prove that exact place.
    generic_queries = []
    if country:
        generic_queries.append(f"{country} {topic['query']}")
    generic_queries.append(topic["query"])
    for query in list(dict.fromkeys(generic_queries)):
        require_country = bool(country_terms and query.startswith(country))
        for provider_name, search_fn in (
            ("Wikimedia Commons", _commons_candidates),
            ("Openverse", _openverse_candidates),
        ):
            try:
                ranked = _rank_candidates(
                    search_fn(query), [], country_terms, topic_terms,
                    require_place=False, require_country=require_country,
                )
            except (requests.RequestException, ValueError, KeyError) as exc:
                log.warning("%s topic image search failed (%s)", provider_name, type(exc).__name__)
                continue
            for candidate in ranked[:8]:
                if verify_image_url(candidate.get("url", "")):
                    scope = "country_topic" if require_country and candidate.get("_country_match") else "topic_generic"
                    cover = _make_cover(candidate, article, scope)
                    log.info("Cover image selected: provider=%s scope=%s", provider_name, scope)
                    return cover

    log.warning(
        "No reusable cover image found; article will not be auto-published without a cover: title=%s",
        _plain(article.get("source_title"))[:160],
    )
    return None
