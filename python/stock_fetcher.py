"""
stock_fetcher.py – MVP stock-media fetcher for video-creator-app.

Responsibilities:
  1. Search Pexels and Pixabay for video/image assets matching a query.
  2. Download preview (low-resolution) assets into cache/assets/.
  3. Write a per-segment JSON manifest into cache/manifests/segment_<n>.json.

Environment variables
---------------------
PEXELS_API_KEY   – your Pexels v1 API key
PIXABAY_API_KEY  – your Pixabay API key

Usage (CLI)
-----------
python stock_fetcher.py --query "ocean sunset" --segments 3 --per-segment 2

This will:
  • search both providers for "ocean sunset"
  • download up to (segments * per_segment) preview files
  • write cache/manifests/segment_0.json … segment_N.json
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants / defaults
# ---------------------------------------------------------------------------

CACHE_ASSETS_DIR = Path(__file__).resolve().parent.parent / "cache" / "assets"
CACHE_MANIFESTS_DIR = Path(__file__).resolve().parent.parent / "cache" / "manifests"

PEXELS_VIDEO_SEARCH_URL = "https://api.pexels.com/videos/search"
PEXELS_PHOTO_SEARCH_URL = "https://api.pexels.com/v1/search"
PIXABAY_API_URL = "https://pixabay.com/api/"
PIXABAY_VIDEO_API_URL = "https://pixabay.com/api/videos/"

DEFAULT_PER_PAGE = 10
REQUEST_TIMEOUT = 30  # seconds

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ensure_dirs() -> None:
    CACHE_ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_MANIFESTS_DIR.mkdir(parents=True, exist_ok=True)


def _get(url: str, headers: dict[str, str] | None = None) -> Any:
    """Perform a simple HTTP GET and return parsed JSON."""
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
        return json.loads(resp.read().decode())


def _download_file(url: str, dest: Path) -> Path:
    """Download *url* to *dest*, skipping if it already exists."""
    if dest.exists():
        logger.debug("Cache hit: %s", dest)
        return dest
    logger.info("Downloading %s -> %s", url, dest)
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
        dest.write_bytes(resp.read())
    return dest


def _safe_filename(url: str) -> str:
    """Derive a safe local filename from a URL."""
    parsed = urllib.parse.urlparse(url)
    name = Path(parsed.path).name
    # strip query-string artefacts and keep only safe characters
    name = "".join(c for c in name if c.isalnum() or c in (".", "-", "_"))
    return name or "asset"


# ---------------------------------------------------------------------------
# Pexels
# ---------------------------------------------------------------------------


def search_pexels_videos(
    query: str,
    api_key: str,
    per_page: int = DEFAULT_PER_PAGE,
    page: int = 1,
) -> list[dict[str, Any]]:
    """Return a list of Pexels video result dicts."""
    params = urllib.parse.urlencode(
        {"query": query, "per_page": per_page, "page": page}
    )
    url = f"{PEXELS_VIDEO_SEARCH_URL}?{params}"
    data = _get(url, headers={"Authorization": api_key})
    results = []
    for video in data.get("videos", []):
        # prefer the smallest video file for preview
        video_files = sorted(
            video.get("video_files", []),
            key=lambda f: f.get("width", 0),
        )
        preview_url = video_files[0]["link"] if video_files else None
        if not preview_url:
            continue
        results.append(
            {
                "provider": "pexels",
                "type": "video",
                "id": str(video["id"]),
                "url": preview_url,
                "width": video_files[0].get("width"),
                "height": video_files[0].get("height"),
                "duration": video.get("duration"),
                "thumbnail": video.get("image"),
                "source_page": video.get("url"),
                "license": "Pexels License",
            }
        )
    return results


def search_pexels_photos(
    query: str,
    api_key: str,
    per_page: int = DEFAULT_PER_PAGE,
    page: int = 1,
) -> list[dict[str, Any]]:
    """Return a list of Pexels photo result dicts."""
    params = urllib.parse.urlencode(
        {"query": query, "per_page": per_page, "page": page}
    )
    url = f"{PEXELS_PHOTO_SEARCH_URL}?{params}"
    data = _get(url, headers={"Authorization": api_key})
    results = []
    for photo in data.get("photos", []):
        src = photo.get("src", {})
        preview_url = src.get("medium") or src.get("original")
        if not preview_url:
            continue
        results.append(
            {
                "provider": "pexels",
                "type": "photo",
                "id": str(photo["id"]),
                "url": preview_url,
                "width": photo.get("width"),
                "height": photo.get("height"),
                "thumbnail": src.get("tiny"),
                "source_page": photo.get("url"),
                "license": "Pexels License",
            }
        )
    return results


# ---------------------------------------------------------------------------
# Pixabay
# ---------------------------------------------------------------------------


def search_pixabay_videos(
    query: str,
    api_key: str,
    per_page: int = DEFAULT_PER_PAGE,
    page: int = 1,
) -> list[dict[str, Any]]:
    """Return a list of Pixabay video result dicts."""
    params = urllib.parse.urlencode(
        {"key": api_key, "q": query, "per_page": per_page, "page": page}
    )
    url = f"{PIXABAY_VIDEO_API_URL}?{params}"
    data = _get(url)
    results = []
    for hit in data.get("hits", []):
        videos = hit.get("videos", {})
        # prefer "tiny" or "small" for preview
        preview = (
            videos.get("tiny") or videos.get("small") or videos.get("medium")
        )
        if not preview:
            continue
        results.append(
            {
                "provider": "pixabay",
                "type": "video",
                "id": str(hit["id"]),
                "url": preview["url"],
                "width": preview.get("width"),
                "height": preview.get("height"),
                "duration": hit.get("duration"),
                "thumbnail": hit.get("userImageURL"),
                "source_page": hit.get("pageURL"),
                "license": "Pixabay License",
            }
        )
    return results


def search_pixabay_photos(
    query: str,
    api_key: str,
    per_page: int = DEFAULT_PER_PAGE,
    page: int = 1,
) -> list[dict[str, Any]]:
    """Return a list of Pixabay photo result dicts."""
    params = urllib.parse.urlencode(
        {"key": api_key, "q": query, "per_page": per_page, "page": page}
    )
    url = f"{PIXABAY_API_URL}?{params}"
    data = _get(url)
    results = []
    for hit in data.get("hits", []):
        preview_url = hit.get("previewURL") or hit.get("webformatURL")
        if not preview_url:
            continue
        results.append(
            {
                "provider": "pixabay",
                "type": "photo",
                "id": str(hit["id"]),
                "url": preview_url,
                "width": hit.get("webformatWidth"),
                "height": hit.get("webformatHeight"),
                "thumbnail": hit.get("previewURL"),
                "source_page": hit.get("pageURL"),
                "license": "Pixabay License",
            }
        )
    return results


# ---------------------------------------------------------------------------
# Search aggregator
# ---------------------------------------------------------------------------


def search_all(
    query: str,
    pexels_api_key: str | None = None,
    pixabay_api_key: str | None = None,
    per_page: int = DEFAULT_PER_PAGE,
    media_type: str = "video",
) -> list[dict[str, Any]]:
    """
    Search Pexels and/or Pixabay for *query*.

    Parameters
    ----------
    query          : search term
    pexels_api_key : Pexels API key (falls back to PEXELS_API_KEY env var)
    pixabay_api_key: Pixabay API key (falls back to PIXABAY_API_KEY env var)
    per_page       : results per provider
    media_type     : "video", "photo", or "both"

    Returns a combined, deduplicated list of asset dicts.
    """
    pexels_key = pexels_api_key or os.environ.get("PEXELS_API_KEY", "")
    pixabay_key = pixabay_api_key or os.environ.get("PIXABAY_API_KEY", "")

    results: list[dict[str, Any]] = []

    if pexels_key:
        try:
            if media_type in ("video", "both"):
                results += search_pexels_videos(query, pexels_key, per_page)
            if media_type in ("photo", "both"):
                results += search_pexels_photos(query, pexels_key, per_page)
        except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, KeyError, ValueError) as exc:
            logger.warning("Pexels search failed: %s", exc)
    else:
        logger.warning("PEXELS_API_KEY not set – skipping Pexels.")

    if pixabay_key:
        try:
            if media_type in ("video", "both"):
                results += search_pixabay_videos(query, pixabay_key, per_page)
            if media_type in ("photo", "both"):
                results += search_pixabay_photos(query, pixabay_key, per_page)
        except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, KeyError, ValueError) as exc:
            logger.warning("Pixabay search failed: %s", exc)
    else:
        logger.warning("PIXABAY_API_KEY not set – skipping Pixabay.")

    return results


# ---------------------------------------------------------------------------
# Download assets
# ---------------------------------------------------------------------------


def download_assets(
    assets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Download preview files for *assets* into CACHE_ASSETS_DIR.

    Each asset dict is updated in-place with a ``local_path`` key pointing to
    the downloaded file (relative to the project root).

    Returns the updated list (same objects, mutated).
    """
    _ensure_dirs()
    for asset in assets:
        url = asset.get("url", "")
        if not url:
            continue
        provider = asset.get("provider", "unknown")
        asset_id = asset.get("id", "")
        suffix = Path(urllib.parse.urlparse(url).path).suffix or ".mp4"
        filename = f"{provider}_{asset_id}{suffix}"
        dest = CACHE_ASSETS_DIR / filename
        try:
            _download_file(url, dest)
            asset["local_path"] = str(dest.relative_to(Path(__file__).resolve().parent.parent))
        except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
            logger.error("Failed to download %s: %s", url, exc)
            asset["local_path"] = None
    return assets


# ---------------------------------------------------------------------------
# Manifest generation
# ---------------------------------------------------------------------------


def build_segment_manifests(
    assets: list[dict[str, Any]],
    num_segments: int,
    assets_per_segment: int,
    query: str = "",
    timestamp: str | None = None,
) -> list[Path]:
    """
    Split *assets* into *num_segments* groups and write one JSON manifest per
    segment at CACHE_MANIFESTS_DIR/segment_<n>.json.

    Returns a list of written manifest Paths.
    """
    _ensure_dirs()
    if timestamp is None:
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    written: list[Path] = []
    for seg_idx in range(num_segments):
        start = seg_idx * assets_per_segment
        segment_assets = assets[start : start + assets_per_segment]

        manifest = {
            "segment_index": seg_idx,
            "query": query,
            "generated_at": timestamp,
            "assets_per_segment": assets_per_segment,
            "assets": segment_assets,
        }

        manifest_path = CACHE_MANIFESTS_DIR / f"segment_{seg_idx}.json"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        logger.info("Wrote manifest: %s", manifest_path)
        written.append(manifest_path)

    return written


# ---------------------------------------------------------------------------
# High-level pipeline entry point
# ---------------------------------------------------------------------------


def run_pipeline(
    query: str,
    num_segments: int = 3,
    assets_per_segment: int = 2,
    media_type: str = "video",
    pexels_api_key: str | None = None,
    pixabay_api_key: str | None = None,
) -> list[Path]:
    """
    End-to-end: search → download previews → write manifests.

    Parameters
    ----------
    query             : search term passed to both providers
    num_segments      : number of video segments (one manifest per segment)
    assets_per_segment: assets allocated to each segment
    media_type        : "video", "photo", or "both"
    pexels_api_key    : override PEXELS_API_KEY env var
    pixabay_api_key   : override PIXABAY_API_KEY env var

    Returns list of manifest Paths that were written.
    """
    total_needed = num_segments * assets_per_segment

    logger.info(
        "Fetching %d assets for query=%r (segments=%d, per_segment=%d)",
        total_needed,
        query,
        num_segments,
        assets_per_segment,
    )

    assets = search_all(
        query,
        pexels_api_key=pexels_api_key,
        pixabay_api_key=pixabay_api_key,
        per_page=min(total_needed, 80),
        media_type=media_type,
    )

    logger.info("Found %d raw results.", len(assets))

    # Trim to exactly what we need
    assets = assets[:total_needed]

    download_assets(assets)

    manifests = build_segment_manifests(
        assets,
        num_segments=num_segments,
        assets_per_segment=assets_per_segment,
        query=query,
    )

    return manifests


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fetch stock assets and build segment manifests."
    )
    parser.add_argument("--query", required=True, help="Search query string")
    parser.add_argument(
        "--segments",
        type=int,
        default=3,
        metavar="N",
        help="Number of video segments (default: 3)",
    )
    parser.add_argument(
        "--per-segment",
        type=int,
        default=2,
        metavar="N",
        dest="per_segment",
        help="Assets per segment (default: 2)",
    )
    parser.add_argument(
        "--media-type",
        choices=["video", "photo", "both"],
        default="video",
        dest="media_type",
        help="Type of media to fetch (default: video)",
    )
    parser.add_argument(
        "--pexels-key",
        default=None,
        dest="pexels_key",
        help="Pexels API key (overrides PEXELS_API_KEY env var)",
    )
    parser.add_argument(
        "--pixabay-key",
        default=None,
        dest="pixabay_key",
        help="Pixabay API key (overrides PIXABAY_API_KEY env var)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        dest="log_level",
        help="Logging verbosity (default: INFO)",
    )
    return parser


def main() -> None:
    parser = _build_arg_parser()
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)-8s %(message)s",
    )

    manifests = run_pipeline(
        query=args.query,
        num_segments=args.segments,
        assets_per_segment=args.per_segment,
        media_type=args.media_type,
        pexels_api_key=args.pexels_key,
        pixabay_api_key=args.pixabay_key,
    )

    print(f"\nDone. {len(manifests)} manifest(s) written:")
    for m in manifests:
        print(f"  {m}")


if __name__ == "__main__":
    main()
