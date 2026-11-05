"""Find SEO cover images from openly licensed libraries with strict location matching.

Only CC0/Public Domain and CC BY images are considered. Original article images
are used as visual-search references, never copied as reusable files. There is no
generic-category fallback: unmatched articles are held for review.
"""
from __future__ import annotations

import html
import ipaddress
import json
import logging
import os
import re
import socket
import unicodedata
from urllib.parse import quote, urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

log = logging.getLogger("travel-content-bot.images")

COMMONS_API = "https://commons.wikimedia.org/w/api.php"
OPENVERSE_API = "https://api.openverse.org/v1/images/"
SERPAPI_API = "https://serpapi.com/search.json"
REQUEST_TIMEOUT = (5, 18)
MIN_WIDTH = 1200
MIN_HEIGHT = 600
MAX_RESULTS = 30
GOOGLE_RESULTS_LIMIT = 8
SERPAPI_API_KEY = os.getenv("SERPAPI_API_KEY", "").strip()

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
    """Allow CC0/PD/CC BY; reject NC, ND, and ShareAlike pending compatible terms."""
    value = _normalise(license_name)
    if not value:
        return False
    if re.search(r"\b(nc|nd|non ?commercial|no derivatives|noderivatives)\b", value):
        return False
    if re.search(r"\bcc by sa\b", value):
        # ShareAlike derivatives must be distributed under compatible terms.
        # The publication workflow is not currently licensed that way.
        return False
    if "public domain" in value or "public domain mark" in value or "cc0" in value or value == "pdm":
        return True
    return bool(re.search(r"\bcc by\b", value))


def _license_allowed_code(code: str) -> bool:
    value = _normalise(code)
    # CC BY-SA is excluded until the site's derivative assets can be distributed
    # under compatible ShareAlike terms.
    return value in {"cc0", "pdm", "by"}


def _destination_terms(article: dict) -> list[str]:
    city = _plain(article.get("destination_city") or article.get("destination") or "")
    if not city or _normalise(city) in {"world", "vietnam", "viet nam", "unclassified", "chua phan loai"}:
        return []
    terms = [city]
    normalized = _normalise(city)
    aliases = {
        "ha long": ["Ha Long Bay"],
        "vinh ha long": ["Ha Long Bay", "Ha Long"],
        "halong": ["Ha Long Bay", "Ha Long"],
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
        "terms": ["travel", "destination", "tourism", "landscape", "bay", "beach", "island", "coast", "mountain", "forest", "attraction", "landmark"],
        "label": "điểm đến du lịch",
    },
    "travel-tips": {
        "query": "travel planning destination",
        "terms": ["travel", "destination", "tourism", "journey", "backpack"],
        "label": "kinh nghiệm du lịch",
    },
    "travel-guide": {
        "query": "travel destination landscape",
        "terms": ["travel", "destination", "tourism", "landscape", "city", "bay", "beach", "island", "coast", "mountain", "cave", "waterfall", "forest", "temple", "market", "attraction", "landmark"],
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


_CONTEXT_STOPWORDS = {
    "the", "and", "for", "with", "from", "this", "that", "your", "you", "are",
    "best", "top", "guide", "travel", "travelling", "traveling", "trip", "journey",
    "destination", "tourism", "tourist", "vacation", "holiday", "things", "explore",
    "discover", "visit", "experience", "experiences", "place", "places", "near",
    "what", "where", "when", "how", "why", "into", "over", "under", "about",
    "du", "lich", "di", "den", "cam", "nang", "kinh", "nghiem", "hanh", "trinh",
    "diem", "noi", "tieng", "dep", "nhat", "nhung", "cac", "mot", "cho", "voi",
    "tai", "trong", "ngoai", "tren", "duoi", "ngay", "thang", "vietnam", "viet",
    "nam", "world", "unclassified", "chua", "phan", "loai",
}


def _source_visual_context(article: dict) -> tuple[list[str], list[str]]:
    """Return image captions/headings and alt text from the original article."""
    phrases: list[str] = []
    alt_parts: list[str] = []
    images = article.get("source_images") or []
    if not isinstance(images, list):
        return phrases, alt_parts
    for item in images[:20]:
        if not isinstance(item, dict):
            continue
        if item.get("placement_source") in {"og:image_fallback", "rss_image_fallback"} or item.get("is_cover") is True or item.get("image_id") == "COVER_LIBRARY":
            continue
        caption = _plain(item.get("caption"))
        heading = _plain(item.get("nearby_heading"))
        alt = _plain(item.get("alt"))
        for value in (caption, heading):
            if value and len(value) >= 5 and value.casefold() not in {x.casefold() for x in phrases}:
                phrases.append(value[:180])
        if alt:
            alt_parts.append(alt[:180])
    return phrases[:8], alt_parts[:8]


def _article_context_terms(article: dict) -> list[str]:
    source_phrases, alt_parts = _source_visual_context(article)
    raw = _metadata_text(
        article.get("visual_search_title"), article.get("source_title"), article.get("seo_title"),
        article.get("visual_search_summary"), article.get("source_summary"), article.get("seo_description"),
        article.get("visual_search_body"), article.get("source_meta_keywords"), article.get("visual_search_keywords"),
        *source_phrases, *alt_parts,
    )
    location_terms = set(_normalise(_metadata_text(*_destination_terms(article), *_country_terms(article))).split())
    terms = []
    for word in _normalise(raw).split():
        if len(word) < 3 or word in _CONTEXT_STOPWORDS or word in location_terms or word.isdigit():
            continue
        if word not in terms:
            terms.append(word)
        if len(terms) >= 28:
            break
    return terms


def _article_context_phrases(article: dict) -> list[str]:
    source_phrases, alt_parts = _source_visual_context(article)
    title = _plain(article.get("visual_search_title") or article.get("source_title") or article.get("seo_title"))
    output = []
    for value in source_phrases + alt_parts + ([title] if title else []):
        tokens = [word for word in _normalise(value).split() if len(word) >= 3 and word not in _CONTEXT_STOPWORDS]
        phrase = " ".join(tokens[:8])
        if len(tokens) >= 2 and phrase and phrase not in output:
            output.append(phrase)
    return output[:6]


def _best_original_image(article: dict) -> dict | None:
    """Choose a descriptive photo from the source article for Google Lens."""
    images = article.get("source_images") or []
    if not isinstance(images, list):
        return None
    title_terms = set(_article_context_terms(article))
    choices = []
    for item in images[:20]:
        if not isinstance(item, dict):
            continue
        if item.get("placement_source") in {"og:image_fallback", "rss_image_fallback"} or item.get("is_cover") is True or item.get("image_id") == "COVER_LIBRARY":
            continue
        if not _plain(item.get("url")).startswith("https://"):
            continue
        context = _normalise(" ".join((
            _plain(item.get("caption")), _plain(item.get("nearby_heading")), _plain(item.get("alt")),
        )))
        overlap = sum(1 for term in title_terms if term in context.split())
        score = overlap * 10 + (12 if item.get("caption") else 0) + (8 if item.get("nearby_heading") else 0)
        choices.append((score, item))
    if not choices:
        return None
    choices.sort(key=lambda pair: pair[0], reverse=True)
    return choices[0][1]


def _public_https_url(value: str) -> bool:
    """Reject local/private destinations before fetching a Google result's license page."""
    try:
        parsed = urlsplit(_plain(value))
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            return False
        host = parsed.hostname.rstrip(".").lower()
        if host in {"localhost", "localhost.localdomain"} or host.endswith((".local", ".internal")):
            return False
        try:
            addresses = [ipaddress.ip_address(host)]
        except ValueError:
            addresses = [ipaddress.ip_address(info[4][0]) for info in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)]
        return bool(addresses) and all(address.is_global for address in addresses)
    except (ValueError, OSError):
        return False


def _license_from_landing_page(page_url: str) -> dict | None:
    """Require image-specific license and creator evidence on a Google-discovered result page."""
    if not _public_https_url(page_url):
        return None
    try:
        response = requests.get(
            page_url,
            headers={"User-Agent": _USER_AGENT, "Range": "bytes=0-524287"},
            stream=True, allow_redirects=False, timeout=REQUEST_TIMEOUT,
        )
        try:
            if response.status_code in {301, 302, 303, 307, 308}:
                location = urljoin(page_url, response.headers.get("Location", ""))
                if not _public_https_url(location):
                    return None
                response.close()
                response = requests.get(
                    location,
                    headers={"User-Agent": _USER_AGENT, "Range": "bytes=0-524287"},
                    stream=True, allow_redirects=False, timeout=REQUEST_TIMEOUT,
                )
            if response.status_code != 200 or "html" not in (response.headers.get("Content-Type") or "").lower():
                return None
            chunks, total = [], 0
            for chunk in response.iter_content(chunk_size=16384):
                if not chunk:
                    continue
                chunks.append(chunk)
                total += len(chunk)
                if total >= 524288:
                    break
            raw_html = b"".join(chunks).decode(response.encoding or "utf-8", errors="replace")
        finally:
            response.close()
    except requests.RequestException:
        return None

    soup = BeautifulSoup(raw_html, "html.parser")
    license_values: list[tuple[str, str]] = []
    creator = ""

    # Only image-specific metadata is accepted. A page-wide copyright notice or
    # the article's author is not evidence of the photographer's license.
    for tag in soup.find_all("meta"):
        key = _normalise(tag.get("name") or tag.get("property") or "")
        value = _plain(tag.get("content"))
        if not value:
            continue
        if key in {"image license", "photo license", "image rights", "photo rights", "og image license"}:
            license_values.append((value, value if value.startswith("https://") else ""))
        if key in {"image creator", "photo creator", "photographer", "image photographer", "photo credit"} and not creator:
            creator = value[:180]

    def visit_jsonld(node):
        nonlocal creator
        if isinstance(node, list):
            for child in node:
                visit_jsonld(child)
        elif isinstance(node, dict):
            raw_type = node.get("@type") or []
            types = {str(value).casefold().rsplit("/", 1)[-1].rsplit("#", 1)[-1] for value in (raw_type if isinstance(raw_type, list) else [raw_type])}
            is_image_object = "imageobject" in types
            if is_image_object:
                license_value = node.get("license")
                if isinstance(license_value, str):
                    license_values.append((license_value, license_value if license_value.startswith("https://") else ""))
                elif isinstance(license_value, dict):
                    url = _plain(license_value.get("@id") or license_value.get("url"))
                    name = _plain(license_value.get("name") or url)
                    if url or name:
                        license_values.append((name, url if url.startswith("https://") else ""))
                creator_value = node.get("creator")
                if not creator:
                    if isinstance(creator_value, dict):
                        creator = _plain(creator_value.get("name"))[:180]
                    elif isinstance(creator_value, list):
                        creator = ", ".join(_plain(item.get("name")) for item in creator_value if isinstance(item, dict))[:180]
                    elif isinstance(creator_value, str):
                        creator = _plain(creator_value)[:180]
            for key in ("@graph", "mainEntity", "mainEntityOfPage", "image", "associatedMedia", "primaryImageOfPage"):
                if key in node:
                    visit_jsonld(node[key])

    for script in soup.select('script[type="application/ld+json"]'):
        try:
            visit_jsonld(json.loads(script.string or script.get_text()))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue

    for label, url in license_values:
        combined = _normalise(label)
        url_norm = _normalise(url)
        if re.search(r"\b(nc|nd|non commercial|no derivatives)\b", combined + " " + url_norm):
            continue
        license_name = ""
        if "publicdomain zero" in url_norm or "cc0" in combined:
            license_name = "CC0"
        elif "publicdomain mark" in url_norm or "public domain mark" in combined:
            license_name = "Public Domain Mark"
        else:
            version = re.search(r"(1 0|2 0|2 5|3 0|4 0)", url_norm + " " + combined)
            version_text = version.group(1).replace(" ", ".") if version else ""
            is_by_sa = (
                "creativecommons org licenses by sa" in url_norm
                or re.search(r"\bcc by sa\b", combined)
                or "creative commons attribution share alike" in combined
            )
            is_by = (
                "creativecommons org licenses by" in url_norm
                or re.search(r"\bcc by\b", combined)
                or "creative commons attribution" in combined
            )
            if version_text and is_by_sa:
                license_name = "CC BY-SA " + version_text
            elif version_text and is_by:
                license_name = "CC BY " + version_text
        if not license_name or not is_license_allowed(license_name):
            continue
        if license_name.startswith(("CC BY", "CC BY-SA")) and not creator:
            continue
        canonical_url = {
            "CC0": "https://creativecommons.org/publicdomain/zero/1.0/",
            "Public Domain Mark": "https://creativecommons.org/publicdomain/mark/1.0/",
        }.get(license_name)
        if license_name.startswith("CC BY-SA "):
            canonical_url = "https://creativecommons.org/licenses/by-sa/" + license_name.removeprefix("CC BY-SA ") + "/"
        elif license_name.startswith("CC BY "):
            canonical_url = "https://creativecommons.org/licenses/by/" + license_name.removeprefix("CC BY ") + "/"
        if canonical_url:
            return {"license": license_name, "license_url": canonical_url, "creator": creator or "Public domain"}
    return None


def _google_visual_candidates(article: dict, query: str) -> list[dict]:
    """Use Google Lens through SerpApi; every visual match still needs explicit license proof."""
    if not SERPAPI_API_KEY:
        return []
    reference = _best_original_image(article)
    params = {
        "engine": "google_lens" if reference else "google_images",
        "api_key": SERPAPI_API_KEY,
        "hl": "vi",
        "q": query,
    }
    if reference:
        params["url"] = _plain(reference.get("url"))
        params["type"] = "visual_matches"
    else:
        params["tbs"] = "itp:photo,sur:cl,isz:l"
    try:
        response = requests.get(SERPAPI_API, params=params, headers={"User-Agent": _USER_AGENT}, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError) as exc:
        log.warning("Google visual search unavailable (%s)", type(exc).__name__)
        return []

    results = data.get("visual_matches") if reference else data.get("images_results")
    output = []
    for item in (results or [])[:GOOGLE_RESULTS_LIMIT]:
        landing_url = _plain(item.get("link"))
        image_url = _plain(item.get("image") or item.get("original"))
        if not _public_https_url(landing_url) or not _public_https_url(image_url):
            continue
        width = item.get("image_width") or item.get("original_width") or 0
        height = item.get("image_height") or item.get("original_height") or 0
        if width and height and not _image_dimensions_ok(width, height):
            continue
        rights = _license_from_landing_page(landing_url)
        if not rights:
            continue
        output.append({
            "visual_reference_match": bool(reference),
            "url": image_url, "title": _plain(item.get("title")),
            "description": _plain(item.get("source") or item.get("title")),
            "tags_text": _plain(item.get("source") or ""),
            "creator": rights["creator"], "creator_url": "",
            "license": rights["license"], "license_url": rights["license_url"],
            "source_page_url": landing_url,
            "provider": "Google Lens / SerpApi" if reference else "Google Images / SerpApi",
            "width": width, "height": height,
        })
    return output


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


def _ext_value(metadata: dict, key: str) -> str:
    value = metadata.get(key, "")
    if isinstance(value, dict):
        value = value.get("value", "")
    return _plain(value)


def _commons_artist(metadata: dict) -> tuple[str, str]:
    raw = _ext_value(metadata, "Artist")
    soup = BeautifulSoup(raw, "html.parser")
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
        license_name = _clean_html(_ext_value(metadata, "LicenseShortName"))
        license_url = _plain(_ext_value(metadata, "LicenseUrl"))
        usage_terms = _clean_html(_ext_value(metadata, "UsageTerms"))
        if not is_license_allowed(license_name or usage_terms) or not license_url.startswith("https://"):
            continue
        creator, creator_url = _commons_artist(metadata)
        if _normalise(license_name).startswith(("cc by", "cc by sa")) and not creator:
            continue
        description = _clean_html(_ext_value(metadata, "ImageDescription"))
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


def _looks_like_ad_or_bad_image(candidate: dict) -> bool:
    """Reject animated GIFs and obvious promotional creatives from image providers."""
    parsed = urlsplit(_plain(candidate.get("url")))
    path = (parsed.path or "").casefold()
    if path.endswith((".gif", ".svg", ".ico")):
        return True
    descriptive = _normalise(" ".join((
        _plain(candidate.get("title")),
        _plain(candidate.get("description")),
        _plain(candidate.get("tags_text")),
        path,
    )))
    blocked = (
        "advertisement", "advertising", "sponsored", "sponsor content",
        "promotion banner", "promotional banner", "banner ad", "ad banner",
        "web banner", "logo", "site icon", "tracking pixel",
    )
    return any(term in descriptive for term in blocked)


def _rank_candidates(candidates: list[dict], place_terms: list[str], country_terms: list[str],
                     topic_terms: list[str], *, require_place: bool, require_country: bool = False,
                     context_terms: list[str] | None = None,
                     context_phrases: list[str] | None = None,
                     require_context: bool = False) -> list[dict]:
    ranked = []
    context_terms = context_terms or []
    context_phrases = context_phrases or []
    for candidate in candidates:
        if _looks_like_ad_or_bad_image(candidate):
            continue
        metadata = _metadata_text(candidate.get("title"), candidate.get("description"), candidate.get("tags_text"))
        place_matches = _matches_any(metadata, place_terms)
        country_matches = _matches_any(metadata, country_terms)
        topic_matches = _matches_any(metadata, topic_terms)
        context_matches = [term for term in context_terms if _contains_phrase(metadata, term)]
        phrase_matches = [phrase for phrase in context_phrases if _contains_phrase(metadata, phrase)]
        visual_reference_match = bool(candidate.get("visual_reference_match"))
        context_ok = bool(phrase_matches or len(context_matches) >= 2 or (visual_reference_match and len(context_matches) >= 1))
        if require_context and not context_ok:
            continue
        if require_place and not place_matches and not (visual_reference_match and context_ok):
            continue
        if require_country and country_terms and not country_matches and not (visual_reference_match and context_ok):
            continue
        if topic_terms and not topic_matches and not context_ok:
            continue
        score = (100 if place_matches else 0) + (10 if country_matches else 0)
        score += min(16, len(topic_matches) * 3) + min(40, len(context_matches) * 8)
        score += 60 if phrase_matches else 0
        score += min(4, int(candidate.get("width", 0) or 0) // 1000)
        candidate = dict(candidate)
        candidate["_score"] = score
        candidate["_place_match"] = place_matches[0] if place_matches else ""
        candidate["_country_match"] = country_matches[0] if country_matches else ""
        candidate["_context_matches"] = context_matches[:8]
        candidate["_context_phrase_match"] = phrase_matches[0] if phrase_matches else ""
        ranked.append(candidate)
    return sorted(ranked, key=lambda item: item.get("_score", 0), reverse=True)


def _make_cover(candidate: dict, article: dict, scope: str) -> dict:
    city = _plain(article.get("destination_city") or "")
    country = _plain(article.get("destination_country") or "")
    topic = _topic(article)
    image_title = _plain(candidate.get("title") or "")
    if scope == "exact_destination":
        label = ", ".join(part for part in (city, country) if part)
        alt = f"{label} – {image_title or topic['label']}"[:300]
    else:
        alt = image_title or _plain(article.get("visual_search_title") or article.get("source_title"))[:300]
    return {
        "image_id": "COVER_LIBRARY",
        "url": candidate["url"],
        "alt": alt,
        "caption": image_title[:400],
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
        "relevance_verified": True,
        "matched_context_terms": candidate.get("_context_matches") or [],
        "matched_context_phrase": candidate.get("_context_phrase_match") or None,
        "search_method": candidate.get("provider"),
        "is_cover": True,
        "image_scope": scope,
        "place_evidence": candidate.get("_place_match") or None,
    }


def _image_key(url: str) -> str:
    """Canonicalize image URLs so query-string variants count as the same image."""
    try:
        parsed = urlsplit(_plain(url))
        host = (parsed.hostname or "").lower()
        path = re.sub(r"/+", "/", parsed.path or "").rstrip("/")
        return f"{host}{path}".casefold()
    except ValueError:
        return _plain(url).casefold()

def _matches_excluded_domain(url: str, domains: set[str] | list[str] | None) -> bool:
    host = (urlsplit(_plain(url)).hostname or "").lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    for domain in domains or []:
        blocked = _plain(domain).lower().rstrip(".")
        if blocked.startswith("www."):
            blocked = blocked[4:]
        if blocked and (host == blocked or host.endswith("." + blocked)):
            return True
    return False


def find_cover_image(article: dict, exclude_urls: set[str] | None = None, exclude_domains: set[str] | list[str] | None = None) -> dict | None:
    """Find a licensed photo that matches the original article subject and image context."""
    article = article or {}
    place_terms = _destination_terms(article)
    country_terms = _country_terms(article)
    topic = _topic(article)
    context_terms = _article_context_terms(article)
    context_phrases = _article_context_phrases(article)
    excluded = {_image_key(url) for url in (exclude_urls or set()) if url}
    if len(context_terms) < 2:
        log.warning("Insufficient article-specific context; refusing generic cover: %s",
                    _plain(article.get("source_title"))[:150])
        return None

    place = " ".join([place_terms[0] if place_terms else "", country_terms[0] if country_terms else ""]).strip()
    query_phrases = []
    for phrase in context_phrases:
        query_phrases.append(" ".join(part for part in (place, phrase) if part))
    if not query_phrases:
        title = _plain(article.get("visual_search_title") or article.get("source_title"))
        summary = _plain(article.get("visual_search_summary") or article.get("source_summary"))
        query_phrases = [" ".join(part for part in (place, title, summary[:100]) if part)]
    queries = list(dict.fromkeys(value for value in query_phrases if value))[:3]

    if SERPAPI_API_KEY and queries:
        google_candidates = _google_visual_candidates(article, queries[0])
        ranked_google = _rank_candidates(
            google_candidates, place_terms, country_terms, topic["terms"],
            require_place=bool(place_terms), require_country=bool(country_terms),
            context_terms=context_terms, context_phrases=context_phrases,
            require_context=True,
        )
        for candidate in ranked_google:
            if _image_key(candidate.get("url", "")) in excluded or _matches_excluded_domain(candidate.get("url", ""), exclude_domains):
                continue
            if verify_image_url(candidate.get("url", "")):
                scope = "exact_destination" if candidate.get("_place_match") else "topic_specific"
                cover = _make_cover(candidate, article, scope)
                log.info("Google visual-search cover selected: scope=%s title=%s", scope, _plain(candidate.get("title"))[:100])
                return cover

    # Commons/Openverse remain a fallback, but only for article-specific, licensed matches.
    # There is deliberately no generic category-only search.
    for query in queries:
        for provider_name, search_fn in (
            ("Wikimedia Commons", _commons_candidates),
            ("Openverse", _openverse_candidates),
        ):
            try:
                ranked = _rank_candidates(
                    search_fn(query), place_terms, country_terms, topic["terms"],
                    require_place=bool(place_terms), require_country=bool(country_terms),
                    context_terms=context_terms, context_phrases=context_phrases,
                    require_context=True,
                )
            except (requests.RequestException, ValueError, KeyError) as exc:
                log.warning("%s article-specific image search failed (%s)", provider_name, type(exc).__name__)
                continue
            for candidate in ranked:
                if _image_key(candidate.get("url", "")) in excluded or _matches_excluded_domain(candidate.get("url", ""), exclude_domains):
                    continue
                if verify_image_url(candidate.get("url", "")):
                    scope = "exact_destination" if candidate.get("_place_match") else "topic_specific"
                    cover = _make_cover(candidate, article, scope)
                    log.info("Cover selected: provider=%s scope=%s context=%s", provider_name, scope,
                             ",".join(candidate.get("_context_matches", [])[:4]))
                    return cover

    log.warning("No sufficiently relevant and licensed cover found; article held: %s",
                _plain(article.get("source_title"))[:160])
    return None

