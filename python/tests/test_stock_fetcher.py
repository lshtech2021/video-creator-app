"""Unit tests for stock_fetcher.py (no live network calls required)."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure the python package directory is importable regardless of working dir
sys.path.insert(0, str(Path(__file__).parent.parent))

import stock_fetcher as sf  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# load_edl
# ---------------------------------------------------------------------------


class TestLoadEdl:
    def test_valid_edl(self, tmp_path):
        edl = [
            {"id": "seg_001", "keywords": ["mountain", "nature"], "duration": 5.0},
            {"id": "seg_002", "keywords": ["city", "night"]},
        ]
        p = tmp_path / "test.json"
        p.write_text(json.dumps(edl))
        result = sf.load_edl(p)
        assert len(result) == 2
        assert result[0]["id"] == "seg_001"

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            sf.load_edl(tmp_path / "nonexistent.json")

    def test_not_a_list_raises(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text(json.dumps({"id": "seg_001", "keywords": []}))
        with pytest.raises(ValueError, match="JSON array"):
            sf.load_edl(p)

    def test_segment_missing_id_raises(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text(json.dumps([{"keywords": ["sky"]}]))
        with pytest.raises(ValueError, match="missing required field 'id'"):
            sf.load_edl(p)

    def test_segment_missing_keywords_raises(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text(json.dumps([{"id": "seg_001"}]))
        with pytest.raises(ValueError, match="keywords"):
            sf.load_edl(p)

    def test_keywords_must_be_list(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text(json.dumps([{"id": "seg_001", "keywords": "mountain"}]))
        with pytest.raises(ValueError, match="keywords"):
            sf.load_edl(p)


# ---------------------------------------------------------------------------
# SHA-256 helpers
# ---------------------------------------------------------------------------


class TestSha256:
    def test_bytes(self):
        data = b"hello world"
        assert sf._sha256_of_bytes(data) == _sha256(data)

    def test_file(self, tmp_path):
        data = b"test content"
        f = tmp_path / "file.bin"
        f.write_bytes(data)
        assert sf._sha256_of_file(f) == _sha256(data)


# ---------------------------------------------------------------------------
# download_asset – deduplication
# ---------------------------------------------------------------------------


class TestDownloadAsset:
    def test_new_asset_is_saved(self, tmp_path):
        data = b"fake image bytes"
        sha = _sha256(data)
        url = "https://example.com/image.jpg"
        seen: dict[str, Path] = {}

        with patch.object(sf, "_http_get", return_value=data):
            path, returned_sha = sf.download_asset(url, tmp_path, seen)

        assert returned_sha == sha
        assert path is not None
        assert path.exists()
        assert path.read_bytes() == data
        assert sha in seen

    def test_duplicate_returns_existing_path_without_redownload(self, tmp_path):
        """download_asset downloads first then deduplicates by SHA-256.
        If the hash already exists in seen_hashes, the existing cached file
        is returned and no new file is written to disk.
        """
        data = b"fake image bytes"
        sha = _sha256(data)
        existing = tmp_path / f"{sha}.jpg"
        existing.write_bytes(data)
        seen: dict[str, Path] = {sha: existing}

        url = "https://example.com/image.jpg"
        # _http_get IS called (download always happens), but no new file is written
        with patch.object(sf, "_http_get", return_value=data):
            path, returned_sha = sf.download_asset(url, tmp_path, seen)

        assert returned_sha == sha
        # Should return the pre-existing cached path
        assert path == existing
        # No additional files should have been created
        new_files = [f for f in tmp_path.iterdir() if f != existing]
        assert new_files == [], f"Unexpected new files: {new_files}"

    def test_download_failure_returns_none(self, tmp_path):
        url = "https://example.com/image.jpg"
        seen: dict[str, Path] = {}

        with patch.object(sf, "_http_get", side_effect=RuntimeError("network error")):
            path, sha = sf.download_asset(url, tmp_path, seen)

        assert path is None
        assert sha == ""

    def test_extension_guessing(self, tmp_path):
        data = b"fake mp4"
        url = "https://cdn.example.com/clip.mp4?token=abc"
        seen: dict[str, Path] = {}

        with patch.object(sf, "_http_get", return_value=data):
            path, _ = sf.download_asset(url, tmp_path, seen)

        assert path is not None
        assert path.suffix == ".mp4"


# ---------------------------------------------------------------------------
# _ext_for_url
# ---------------------------------------------------------------------------


class TestExtForUrl:
    def test_jpg(self):
        assert sf._ext_for_url("https://example.com/photo.jpg") == ".jpg"

    def test_mp4_with_query_string(self):
        assert sf._ext_for_url("https://cdn.example.com/video.mp4?token=xyz") == ".mp4"

    def test_unknown_extension_returns_bin(self):
        assert sf._ext_for_url("https://example.com/file.xyz") == ".bin"


# ---------------------------------------------------------------------------
# process_segment
# ---------------------------------------------------------------------------


class TestProcessSegment:
    def _make_pexels_image_response(self, asset_id: str = "1") -> bytes:
        payload = {
            "photos": [
                {
                    "id": int(asset_id),
                    "src": {"small": "https://images.pexels.com/small.jpg"},
                    "width": 640,
                    "height": 480,
                    "photographer": "Test",
                    "url": "https://www.pexels.com/photo/1/",
                }
            ]
        }
        return json.dumps(payload).encode()

    def _make_pexels_video_response(self) -> bytes:
        payload = {"videos": []}
        return json.dumps(payload).encode()

    def _make_pixabay_image_response(self, asset_id: str = "10") -> bytes:
        payload = {
            "hits": [
                {
                    "id": int(asset_id),
                    "previewURL": "https://pixabay.com/preview.jpg",
                    "imageWidth": 640,
                    "imageHeight": 480,
                    "user": "pixuser",
                    "pageURL": "https://pixabay.com/images/10/",
                }
            ]
        }
        return json.dumps(payload).encode()

    def _make_pixabay_video_response(self) -> bytes:
        payload = {"hits": []}
        return json.dumps(payload).encode()

    def test_manifest_is_written(self, tmp_path):
        assets_dir = tmp_path / "assets"
        manifests_dir = tmp_path / "manifests"
        assets_dir.mkdir()
        manifests_dir.mkdir()

        segment = {"id": "seg_001", "keywords": ["mountain"], "duration": 3.0}
        seen: dict[str, Path] = {}

        fake_image_data = b"fake jpg bytes for pexels"
        fake_px_image_data = b"fake jpg bytes for pixabay"

        call_count = {"n": 0}

        def fake_http_get(url, headers=None):
            call_count["n"] += 1
            if "pexels.com/v1/search" in url:
                return self._make_pexels_image_response()
            if "pexels.com/videos/search" in url:
                return self._make_pexels_video_response()
            if "pixabay.com/api/videos" in url:
                return self._make_pixabay_video_response()
            if "pixabay.com/api" in url:
                return self._make_pixabay_image_response()
            # Asset download
            if "pexels" in url:
                return fake_image_data
            if "pixabay" in url:
                return fake_px_image_data
            return b"generic bytes"

        with patch.object(sf, "_http_get", side_effect=fake_http_get):
            with patch("time.sleep"):
                manifest = sf.process_segment(
                    segment,
                    assets_dir=assets_dir,
                    manifests_dir=manifests_dir,
                    pexels_key="fake_pexels",
                    pixabay_key="fake_pixabay",
                    seen_hashes=seen,
                )

        manifest_file = manifests_dir / "segment_seg_001.json"
        assert manifest_file.exists()
        written = json.loads(manifest_file.read_text())
        assert written["segment_id"] == "seg_001"
        assert written["keywords"] == ["mountain"]
        assert len(written["assets"]) > 0
        for asset in written["assets"]:
            assert "sha256" in asset
            assert "local_file" in asset
            assert "source" in asset
            assert "type" in asset

    def test_no_api_keys_returns_empty_assets(self, tmp_path):
        assets_dir = tmp_path / "assets"
        manifests_dir = tmp_path / "manifests"
        assets_dir.mkdir()
        manifests_dir.mkdir()

        segment = {"id": "seg_002", "keywords": ["ocean"]}
        seen: dict[str, Path] = {}

        manifest = sf.process_segment(
            segment,
            assets_dir=assets_dir,
            manifests_dir=manifests_dir,
            pexels_key=None,
            pixabay_key=None,
            seen_hashes=seen,
        )
        assert manifest["assets"] == []
        assert (manifests_dir / "segment_seg_002.json").exists()


# ---------------------------------------------------------------------------
# main – argument parsing and missing keys
# ---------------------------------------------------------------------------


class TestMain:
    def test_missing_edl_exits_nonzero(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            sf.main([])
        assert exc_info.value.code != 0

    def test_no_api_keys_returns_1(self, tmp_path, monkeypatch):
        edl = [{"id": "seg_001", "keywords": ["sky"]}]
        edl_file = tmp_path / "edl.json"
        edl_file.write_text(json.dumps(edl))

        monkeypatch.delenv("PEXELS_API_KEY", raising=False)
        monkeypatch.delenv("PIXABAY_API_KEY", raising=False)

        result = sf.main([str(edl_file), "--cache-dir", str(tmp_path / "cache")])
        assert result == 1

    def test_successful_run_returns_0(self, tmp_path, monkeypatch):
        edl = [{"id": "seg_001", "keywords": ["sky"]}]
        edl_file = tmp_path / "edl.json"
        edl_file.write_text(json.dumps(edl))

        monkeypatch.setenv("PEXELS_API_KEY", "fake_key")
        monkeypatch.delenv("PIXABAY_API_KEY", raising=False)

        empty_pexels_images = json.dumps({"photos": []}).encode()
        empty_pexels_videos = json.dumps({"videos": []}).encode()

        def fake_http_get(url, headers=None):
            if "pexels.com/v1" in url:
                return empty_pexels_images
            if "pexels.com/videos" in url:
                return empty_pexels_videos
            return b"{}"

        with patch.object(sf, "_http_get", side_effect=fake_http_get):
            with patch("time.sleep"):
                result = sf.main(
                    [str(edl_file), "--cache-dir", str(tmp_path / "cache")]
                )
        assert result == 0
