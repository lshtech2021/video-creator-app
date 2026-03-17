"""
stock_fetcher.py – MVP stock-asset fetcher for the video-creator pipeline.

Usage:
    python stock_fetcher.py <edl.json>
    python stock_fetcher.py --edl <edl.json> [--cache-dir <path>]

EDL JSON format (array of segments):
    [
      {
        "id": "seg_001",
        "keywords": ["sunrise", "mountain", "nature"],
        "duration": 5.0
      },
      ...
    ]

Environment variables required:
    PEXELS_API_KEY   – Pexels API key
    PIXABAY_API_KEY  – Pixabay API key

Outputs:
    cache/assets/          – downloaded preview files (images + short clips)
    cache/manifests/       – per-segment JSON manifests (segment_<id>.json)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PEXELS_IMAGE_SEARCH = "https://api.pexels.com/v1/search"
PEXELS_VIDEO_SEARCH = "https://api.pexels.com/videos/search"
PIXABAY_IMAGE_SEARCH = "https://pixabay.com/api/"
PIXABAY_VIDEO_SEARCH = "https://pixabay.com/api/videos/"

# Maximum results per keyword per provider (preview quality – small pages)
MAX_RESULTS_PER_QUERY = 5
# Seconds to wait between HTTP requests to stay within rate limits
REQUEST_DELAY = 0.3
# Maximum number of retry attempts for transient HTTP errors
MAX_RETRIES = 3

# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def _http_get(url: str, headers: dict[str, str] | None = None) -> bytes:
    """Perform a GET request and return the raw response body."""
    req = Request(url, headers=headers or {})
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            with urlopen(req, timeout=30) as resp:
                return resp.read()
        except HTTPError as exc:
            if exc.code == 429:
                wait = 2 ** attempt
                log.warning("Rate-limited (429). Waiting %ss before retry %d/%d.", wait, attempt, MAX_RETRIES)
                time.sleep(wait)
            elif exc.code in (500, 502, 503, 504):
                log.warning("Server error %s. Retry %d/%d.", exc.code, attempt, MAX_RETRIES)
                time.sleep(2 ** attempt)
            else:
                raise
        except URLError as exc:
            log.warning("Network error: %s. Retry %d/%d.", exc.reason, attempt, MAX_RETRIES)
            time.sleep(2 ** attempt)
    raise RuntimeError(f"Failed to GET {url} after {MAX_RETRIES} retries.")


def _json_get(url: str, headers: dict[str, str] | None = None) -> Any:
    return json.loads(_http_get(url, headers))


# ---------------------------------------------------------------------------
# SHA-256 deduplication
# ---------------------------------------------------------------------------


def _sha256_of_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Pexels helpers
# ---------------------------------------------------------------------------


def _pexels_search_images(query: str, api_key: str, per_page: int = MAX_RESULTS_PER_QUERY) -> list[dict]:
    """Return Pexels image search results for *query*."""
    params = urlencode({"query": query, "per_page": per_page, "size": "small"})
    url = f"{PEXELS_IMAGE_SEARCH}?{params}"
    headers = {"Authorization": api_key}
    data = _json_get(url, headers)
    photos = data.get("photos", [])
    results = []
    for p in photos:
        src = p.get("src", {})
        preview_url = src.get("small") or src.get("medium") or src.get("original")
        if not preview_url:
            continue
        results.append({
            "source": "pexels",
            "type": "image",
            "asset_id": str(p["id"]),
            "preview_url": preview_url,
            "width": p.get("width"),
            "height": p.get("height"),
            "photographer": p.get("photographer"),
            "page_url": p.get("url"),
        })
    return results


def _pexels_search_videos(query: str, api_key: str, per_page: int = MAX_RESULTS_PER_QUERY) -> list[dict]:
    """Return Pexels video search results for *query*."""
    params = urlencode({"query": query, "per_page": per_page, "size": "small"})
    url = f"{PEXELS_VIDEO_SEARCH}?{params}"
    headers = {"Authorization": api_key}
    data = _json_get(url, headers)
    videos = data.get("videos", [])
    results = []
    for v in videos:
        # Pick the smallest available file (preview quality)
        files = sorted(
            [f for f in v.get("video_files", []) if f.get("link")],
            key=lambda f: f.get("width", 9999),
        )
        if not files:
            continue
        preview_file = files[0]
        results.append({
            "source": "pexels",
            "type": "video",
            "asset_id": str(v["id"]),
            "preview_url": preview_file["link"],
            "width": preview_file.get("width"),
            "height": preview_file.get("height"),
            "duration": v.get("duration"),
            "page_url": v.get("url"),
        })
    return results


# ---------------------------------------------------------------------------
# Pixabay helpers
# ---------------------------------------------------------------------------


def _pixabay_search_images(query: str, api_key: str, per_page: int = MAX_RESULTS_PER_QUERY) -> list[dict]:
    """Return Pixabay image search results for *query*."""
    params = urlencode({
        "key": api_key,
        "q": query,
        "per_page": per_page,
        "image_type": "all",
        "safesearch": "true",
    })
    url = f"{PIXABAY_IMAGE_SEARCH}?{params}"
    data = _json_get(url)
    results = []
    for hit in data.get("hits", []):
        preview_url = hit.get("previewURL") or hit.get("webformatURL")
        if not preview_url:
            continue
        results.append({
            "source": "pixabay",
            "type": "image",
            "asset_id": str(hit["id"]),
            "preview_url": preview_url,
            "width": hit.get("imageWidth"),
            "height": hit.get("imageHeight"),
            "user": hit.get("user"),
            "page_url": hit.get("pageURL"),
        })
    return results


def _pixabay_search_videos(query: str, api_key: str, per_page: int = MAX_RESULTS_PER_QUERY) -> list[dict]:
    """Return Pixabay video search results for *query*."""
    params = urlencode({
        "key": api_key,
        "q": query,
        "per_page": per_page,
        "safesearch": "true",
    })
    url = f"{PIXABAY_VIDEO_SEARCH}?{params}"
    data = _json_get(url)
    results = []
    for hit in data.get("hits", []):
        videos = hit.get("videos", {})
        # Prefer "tiny" or "small" preview quality
        preview = videos.get("tiny") or videos.get("small") or videos.get("medium") or videos.get("large")
        if not preview or not preview.get("url"):
            continue
        results.append({
            "source": "pixabay",
            "type": "video",
            "asset_id": str(hit["id"]),
            "preview_url": preview["url"],
            "width": preview.get("width"),
            "height": preview.get("height"),
            "duration": hit.get("duration"),
            "user": hit.get("user"),
            "page_url": hit.get("pageURL"),
        })
    return results


# ---------------------------------------------------------------------------
# Asset downloader
# ---------------------------------------------------------------------------


def _ext_for_url(url: str) -> str:
    """Guess a file extension from a URL."""
    path = url.split("?")[0].split("#")[0]
    suffix = Path(path).suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".mp4", ".mov", ".webm", ".avi"}:
        return suffix
    return ".bin"


def download_asset(url: str, assets_dir: Path, seen_hashes: dict[str, Path]) -> tuple[Path | None, str]:
    """
    Download *url* into *assets_dir*, skip if a duplicate (by SHA-256) already
    exists.

    Returns ``(local_path, sha256_hex)``.  If the asset was a duplicate,
    ``local_path`` is the *existing* file.
    """
    log.debug("Downloading %s", url)
    try:
        data = _http_get(url)
    except Exception as exc:  # noqa: BLE001
        log.warning("Failed to download %s: %s", url, exc)
        return None, ""

    sha = _sha256_of_bytes(data)
    if sha in seen_hashes:
        log.debug("Duplicate asset (sha256=%s), skipping download.", sha[:12])
        return seen_hashes[sha], sha

    ext = _ext_for_url(url)
    dest = assets_dir / f"{sha}{ext}"
    dest.write_bytes(data)
    seen_hashes[sha] = dest
    log.debug("Saved %s → %s", url, dest.name)
    return dest, sha


# ---------------------------------------------------------------------------
# Per-segment search + download
# ---------------------------------------------------------------------------


def process_segment(
    segment: dict,
    assets_dir: Path,
    manifests_dir: Path,
    pexels_key: str | None,
    pixabay_key: str | None,
    seen_hashes: dict[str, Path],
) -> dict:
    """
    Search, download, and manifest a single EDL segment.

    Returns the manifest dict.
    """
    seg_id = segment.get("id", "unknown")
    keywords: list[str] = segment.get("keywords", [])
    log.info("Processing segment '%s' with keywords: %s", seg_id, keywords)

    candidates: list[dict] = []

    for kw in keywords:
        query = kw.strip()
        if not query:
            continue

        if pexels_key:
            try:
                time.sleep(REQUEST_DELAY)
                candidates.extend(_pexels_search_images(query, pexels_key))
                time.sleep(REQUEST_DELAY)
                candidates.extend(_pexels_search_videos(query, pexels_key))
            except Exception as exc:  # noqa: BLE001
                log.warning("Pexels search failed for keyword '%s': %s", query, exc)

        if pixabay_key:
            try:
                time.sleep(REQUEST_DELAY)
                candidates.extend(_pixabay_search_images(query, pixabay_key))
                time.sleep(REQUEST_DELAY)
                candidates.extend(_pixabay_search_videos(query, pixabay_key))
            except Exception as exc:  # noqa: BLE001
                log.warning("Pixabay search failed for keyword '%s': %s", query, exc)

    log.info("  Found %d candidate assets for segment '%s'.", len(candidates), seg_id)

    assets: list[dict] = []
    for candidate in candidates:
        local_path, sha = download_asset(candidate["preview_url"], assets_dir, seen_hashes)
        if local_path is None:
            continue
        entry = {**candidate, "local_file": str(local_path), "sha256": sha}
        assets.append(entry)

    manifest = {
        "segment_id": seg_id,
        "keywords": keywords,
        "duration": segment.get("duration"),
        "assets": assets,
    }

    manifest_path = manifests_dir / f"segment_{seg_id}.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    log.info("  Manifest written: %s (%d assets).", manifest_path.name, len(assets))
    return manifest


# ---------------------------------------------------------------------------
# EDL loader
# ---------------------------------------------------------------------------


def load_edl(edl_path: str | Path) -> list[dict]:
    """Load and validate an EDL JSON file."""
    path = Path(edl_path)
    if not path.exists():
        raise FileNotFoundError(f"EDL file not found: {path}")
    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, list):
        raise ValueError("EDL file must contain a JSON array of segment objects.")
    for i, seg in enumerate(data):
        if not isinstance(seg, dict):
            raise ValueError(f"Segment {i} must be a JSON object.")
        if "id" not in seg:
            raise ValueError(f"Segment {i} is missing required field 'id'.")
        if "keywords" not in seg or not isinstance(seg["keywords"], list):
            raise ValueError(f"Segment '{seg.get('id', i)}' is missing required field 'keywords' (list).")
    return data


# ---------------------------------------------------------------------------
# Main entry-point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fetch stock assets for each segment in an EDL JSON file.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "edl",
        nargs="?",
        metavar="EDL_JSON",
        help="Path to the EDL JSON file.",
    )
    parser.add_argument(
        "--edl",
        dest="edl_flag",
        metavar="EDL_JSON",
        help="Path to the EDL JSON file (alternative flag form).",
    )
    parser.add_argument(
        "--cache-dir",
        default="cache",
        metavar="DIR",
        help="Root cache directory (default: cache).",
    )
    args = parser.parse_args(argv)

    edl_path = args.edl or args.edl_flag
    if not edl_path:
        parser.error("Please provide an EDL JSON file path.")

    # API keys from environment
    pexels_key = os.environ.get("PEXELS_API_KEY")
    pixabay_key = os.environ.get("PIXABAY_API_KEY")
    if not pexels_key and not pixabay_key:
        log.error(
            "Neither PEXELS_API_KEY nor PIXABAY_API_KEY is set. "
            "Set at least one to fetch assets."
        )
        return 1
    if not pexels_key:
        log.warning("PEXELS_API_KEY not set – skipping Pexels searches.")
    if not pixabay_key:
        log.warning("PIXABAY_API_KEY not set – skipping Pixabay searches.")

    # Prepare cache directories
    cache_root = Path(args.cache_dir)
    assets_dir = cache_root / "assets"
    manifests_dir = cache_root / "manifests"
    assets_dir.mkdir(parents=True, exist_ok=True)
    manifests_dir.mkdir(parents=True, exist_ok=True)

    # Load EDL
    try:
        segments = load_edl(edl_path)
    except (FileNotFoundError, ValueError) as exc:
        log.error("EDL load error: %s", exc)
        return 1

    log.info("Loaded %d segment(s) from '%s'.", len(segments), edl_path)

    # Shared deduplication map: sha256 → local path
    seen_hashes: dict[str, Path] = {}

    # Seed seen_hashes with already-cached assets so cross-run deduplication works
    for existing in assets_dir.iterdir():
        if existing.is_file():
            try:
                seen_hashes[_sha256_of_file(existing)] = existing
            except OSError:
                pass

    # Process each segment
    all_manifests = []
    for segment in segments:
        manifest = process_segment(
            segment,
            assets_dir=assets_dir,
            manifests_dir=manifests_dir,
            pexels_key=pexels_key,
            pixabay_key=pixabay_key,
            seen_hashes=seen_hashes,
        )
        all_manifests.append(manifest)

    total_assets = sum(len(m["assets"]) for m in all_manifests)
    unique_files = len({a["sha256"] for m in all_manifests for a in m["assets"] if a.get("sha256")})
    log.info(
        "Done. %d segment(s) processed, %d asset references, %d unique files in cache.",
        len(all_manifests),
        total_assets,
        unique_files,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
