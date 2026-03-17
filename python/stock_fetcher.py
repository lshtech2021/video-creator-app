"""
stock_fetcher.py — B-roll asset fetcher for Pexels and Pixabay.

Usage
-----
    python stock_fetcher.py --edl samples/sample_edl.json \
                            --cache-dir cache \
                            [--max-per-segment 3] \
                            [--media-type photo|video|both]

Environment variables required
-------------------------------
    PEXELS_API_KEY   — API key from https://www.pexels.com/api/
    PIXABAY_API_KEY  — API key from https://pixabay.com/api/docs/

For each EDL segment the script:
  1. Searches Pexels and Pixabay with the segment keywords.
  2. Downloads preview assets (small images / short clips) into
     cache/assets/<segment_id>/.
  3. Writes a per-segment manifest JSON to
     cache/manifests/segment_<segment_id>.json.

The manifest format is documented in docs/manifest_schema.md.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PEXELS_PHOTO_URL = "https://api.pexels.com/v1/search"
PEXELS_VIDEO_URL = "https://api.pexels.com/videos/search"
PIXABAY_API_URL = "https://pixabay.com/api/"
PIXABAY_VIDEO_API_URL = "https://pixabay.com/api/videos/"

REQUEST_TIMEOUT = 30  # seconds
RETRY_ATTEMPTS = 3
RETRY_BACKOFF = 2.0  # seconds between retries


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _url_to_filename(url: str, ext: str = "") -> str:
    """Derive a stable filename from a URL using its SHA-1 hash."""
    digest = hashlib.sha1(url.encode()).hexdigest()[:16]
    return f"{digest}{ext}"


def _download_file(url: str, dest: Path, session: requests.Session) -> bool:
    """Download *url* to *dest*. Returns True on success."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        logger.debug("Cache hit: %s", dest)
        return True

    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            resp = session.get(url, timeout=REQUEST_TIMEOUT, stream=True)
            resp.raise_for_status()
            with dest.open("wb") as fh:
                for chunk in resp.iter_content(chunk_size=65536):
                    fh.write(chunk)
            logger.info("Downloaded %s → %s", url, dest)
            return True
        except requests.RequestException as exc:
            logger.warning(
                "Download attempt %d/%d failed for %s: %s",
                attempt,
                RETRY_ATTEMPTS,
                url,
                exc,
            )
            if attempt < RETRY_ATTEMPTS:
                time.sleep(RETRY_BACKOFF * attempt)
    return False


# ---------------------------------------------------------------------------
# Pexels
# ---------------------------------------------------------------------------


def _search_pexels_photos(
    query: str, api_key: str, session: requests.Session, per_page: int = 5
) -> list[dict[str, Any]]:
    headers = {"Authorization": api_key}
    params = {"query": query, "per_page": per_page, "size": "small"}
    try:
        resp = session.get(
            PEXELS_PHOTO_URL, headers=headers, params=params, timeout=REQUEST_TIMEOUT
        )
        resp.raise_for_status()
        return resp.json().get("photos", [])
    except requests.RequestException as exc:
        logger.warning("Pexels photo search failed for '%s': %s", query, exc)
        return []


def _search_pexels_videos(
    query: str, api_key: str, session: requests.Session, per_page: int = 3
) -> list[dict[str, Any]]:
    headers = {"Authorization": api_key}
    params = {"query": query, "per_page": per_page, "size": "small"}
    try:
        resp = session.get(
            PEXELS_VIDEO_URL, headers=headers, params=params, timeout=REQUEST_TIMEOUT
        )
        resp.raise_for_status()
        return resp.json().get("videos", [])
    except requests.RequestException as exc:
        logger.warning("Pexels video search failed for '%s': %s", query, exc)
        return []


# ---------------------------------------------------------------------------
# Pixabay
# ---------------------------------------------------------------------------


def _search_pixabay_photos(
    query: str, api_key: str, session: requests.Session, per_page: int = 5
) -> list[dict[str, Any]]:
    params = {
        "key": api_key,
        "q": query,
        "image_type": "photo",
        "per_page": per_page,
        "safesearch": "true",
    }
    try:
        resp = session.get(PIXABAY_API_URL, params=params, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp.json().get("hits", [])
    except requests.RequestException as exc:
        logger.warning("Pixabay photo search failed for '%s': %s", query, exc)
        return []


def _search_pixabay_videos(
    query: str, api_key: str, session: requests.Session, per_page: int = 3
) -> list[dict[str, Any]]:
    params = {
        "key": api_key,
        "q": query,
        "per_page": per_page,
        "safesearch": "true",
    }
    try:
        resp = session.get(PIXABAY_VIDEO_API_URL, params=params, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp.json().get("hits", [])
    except requests.RequestException as exc:
        logger.warning("Pixabay video search failed for '%s': %s", query, exc)
        return []


# ---------------------------------------------------------------------------
# Asset normalisation — convert provider-specific payloads to a flat record
# ---------------------------------------------------------------------------


def _normalise_pexels_photo(photo: dict[str, Any]) -> dict[str, Any]:
    src = photo.get("src", {})
    url = src.get("small") or src.get("medium") or src.get("original", "")
    return {
        "provider": "pexels",
        "type": "photo",
        "id": str(photo.get("id", "")),
        "url": url,
        "width": photo.get("width", 0),
        "height": photo.get("height", 0),
        "photographer": photo.get("photographer", ""),
        "page_url": photo.get("url", ""),
        "local_path": None,
    }


def _normalise_pexels_video(video: dict[str, Any]) -> dict[str, Any]:
    # Prefer the smallest available video file
    files = sorted(
        video.get("video_files", []),
        key=lambda f: f.get("width", 9999),
    )
    url = files[0]["link"] if files else ""
    return {
        "provider": "pexels",
        "type": "video",
        "id": str(video.get("id", "")),
        "url": url,
        "width": video.get("width", 0),
        "height": video.get("height", 0),
        "duration": video.get("duration", 0),
        "page_url": video.get("url", ""),
        "local_path": None,
    }


def _normalise_pixabay_photo(photo: dict[str, Any]) -> dict[str, Any]:
    url = photo.get("previewURL") or photo.get("webformatURL", "")
    return {
        "provider": "pixabay",
        "type": "photo",
        "id": str(photo.get("id", "")),
        "url": url,
        "width": photo.get("webformatWidth", 0),
        "height": photo.get("webformatHeight", 0),
        "tags": photo.get("tags", ""),
        "page_url": photo.get("pageURL", ""),
        "local_path": None,
    }


def _normalise_pixabay_video(video: dict[str, Any]) -> dict[str, Any]:
    # Prefer the "small" quality or the lowest-res available
    videos = video.get("videos", {})
    chosen = (
        videos.get("small")
        or videos.get("medium")
        or videos.get("tiny")
        or {}
    )
    url = chosen.get("url", "")
    return {
        "provider": "pixabay",
        "type": "video",
        "id": str(video.get("id", "")),
        "url": url,
        "width": chosen.get("width", 0),
        "height": chosen.get("height", 0),
        "duration": video.get("duration", 0),
        "tags": video.get("tags", ""),
        "page_url": video.get("pageURL", ""),
        "local_path": None,
    }


# ---------------------------------------------------------------------------
# Core fetcher
# ---------------------------------------------------------------------------


class StockFetcher:
    """Fetch stock assets for EDL segments from Pexels and Pixabay."""

    def __init__(
        self,
        cache_dir: Path,
        pexels_key: str = "",
        pixabay_key: str = "",
        max_per_segment: int = 3,
        media_type: str = "both",
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.assets_dir = self.cache_dir / "assets"
        self.manifests_dir = self.cache_dir / "manifests"
        self.pexels_key = pexels_key
        self.pixabay_key = pixabay_key
        self.max_per_segment = max_per_segment
        self.media_type = media_type  # "photo", "video", or "both"
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "video-creator-app/1.0"})

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process_edl(self, edl: dict[str, Any]) -> list[dict[str, Any]]:
        """Process all segments in an EDL and return list of manifests."""
        segments = edl.get("segments", [])
        manifests: list[dict[str, Any]] = []
        for seg in segments:
            manifest = self.process_segment(seg)
            manifests.append(manifest)
        return manifests

    def process_segment(self, segment: dict[str, Any]) -> dict[str, Any]:
        """Fetch assets for a single EDL segment and write its manifest."""
        seg_id = segment["id"]
        keywords = segment.get("keywords", [])
        query = " ".join(keywords)

        logger.info("Processing segment %s (query: '%s')", seg_id, query)

        assets: list[dict[str, Any]] = []

        # --- Pexels ---
        if self.pexels_key:
            if self.media_type in ("photo", "both"):
                photos = _search_pexels_photos(
                    query, self.pexels_key, self.session, per_page=self.max_per_segment
                )
                for p in photos[: self.max_per_segment]:
                    assets.append(_normalise_pexels_photo(p))
            if self.media_type in ("video", "both"):
                videos = _search_pexels_videos(
                    query, self.pexels_key, self.session, per_page=self.max_per_segment
                )
                for v in videos[: self.max_per_segment]:
                    assets.append(_normalise_pexels_video(v))
        else:
            logger.debug("PEXELS_API_KEY not set — skipping Pexels search.")

        # --- Pixabay ---
        if self.pixabay_key:
            if self.media_type in ("photo", "both"):
                photos = _search_pixabay_photos(
                    query, self.pixabay_key, self.session, per_page=self.max_per_segment
                )
                for p in photos[: self.max_per_segment]:
                    assets.append(_normalise_pixabay_photo(p))
            if self.media_type in ("video", "both"):
                videos = _search_pixabay_videos(
                    query, self.pixabay_key, self.session, per_page=self.max_per_segment
                )
                for v in videos[: self.max_per_segment]:
                    assets.append(_normalise_pixabay_video(v))
        else:
            logger.debug("PIXABAY_API_KEY not set — skipping Pixabay search.")

        # --- Download assets ---
        seg_assets_dir = self.assets_dir / seg_id
        for asset in assets:
            url = asset.get("url", "")
            if not url:
                continue
            ext = self._guess_extension(asset)
            filename = _url_to_filename(url, ext)
            dest = seg_assets_dir / filename
            success = _download_file(url, dest, self.session)
            if success:
                asset["local_path"] = str(dest.relative_to(self.cache_dir))

        # --- Write manifest ---
        manifest = self._build_manifest(segment, assets)
        self._write_manifest(seg_id, manifest)
        return manifest

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _guess_extension(self, asset: dict[str, Any]) -> str:
        t = asset.get("type", "photo")
        url = asset.get("url", "")
        if t == "video" or ".mp4" in url:
            return ".mp4"
        return ".jpg"

    def _build_manifest(
        self, segment: dict[str, Any], assets: list[dict[str, Any]]
    ) -> dict[str, Any]:
        return {
            "segment_id": segment["id"],
            "start": segment.get("start"),
            "end": segment.get("end"),
            "keywords": segment.get("keywords", []),
            "subtitle": segment.get("subtitle", ""),
            "transition_in": segment.get("transition_in", "fade"),
            "transition_out": segment.get("transition_out", "fade"),
            "voiceover_start": segment.get("voiceover_start"),
            "voiceover_end": segment.get("voiceover_end"),
            "assets": assets,
        }

    def _write_manifest(self, seg_id: str, manifest: dict[str, Any]) -> None:
        self.manifests_dir.mkdir(parents=True, exist_ok=True)
        path = self.manifests_dir / f"segment_{seg_id}.json"
        with path.open("w", encoding="utf-8") as fh:
            json.dump(manifest, fh, indent=2, ensure_ascii=False)
        logger.info("Manifest written → %s", path)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch stock B-roll assets for EDL segments."
    )
    parser.add_argument(
        "--edl",
        required=True,
        help="Path to the EDL JSON file (e.g. samples/sample_edl.json)",
    )
    parser.add_argument(
        "--cache-dir",
        default="cache",
        help="Root cache directory (default: cache)",
    )
    parser.add_argument(
        "--max-per-segment",
        type=int,
        default=3,
        help="Maximum assets to download per segment per provider (default: 3)",
    )
    parser.add_argument(
        "--media-type",
        choices=["photo", "video", "both"],
        default="both",
        help="Type of media to fetch (default: both)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Logging level (default: INFO)",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    pexels_key = os.environ.get("PEXELS_API_KEY", "")
    pixabay_key = os.environ.get("PIXABAY_API_KEY", "")

    if not pexels_key and not pixabay_key:
        logger.warning(
            "Neither PEXELS_API_KEY nor PIXABAY_API_KEY is set. "
            "No assets will be fetched. Set at least one key to download B-roll."
        )

    edl_path = Path(args.edl)
    with edl_path.open(encoding="utf-8") as fh:
        edl = json.load(fh)

    fetcher = StockFetcher(
        cache_dir=Path(args.cache_dir),
        pexels_key=pexels_key,
        pixabay_key=pixabay_key,
        max_per_segment=args.max_per_segment,
        media_type=args.media_type,
    )
    manifests = fetcher.process_edl(edl)
    logger.info(
        "Done — processed %d segment(s), manifests saved to %s/manifests/",
        len(manifests),
        args.cache_dir,
    )


if __name__ == "__main__":
    main()
