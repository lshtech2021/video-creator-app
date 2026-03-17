"""
Tests for the video-creator-app Python pipeline modules.

Run with:
    cd python && python -m pytest tests/ -v
or from the repo root:
    python -m pytest python/tests/ -v
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Ensure python/ is importable regardless of cwd
# ---------------------------------------------------------------------------
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from stock_fetcher import (
    StockFetcher,
    _url_to_filename,
    _normalise_pexels_photo,
    _normalise_pexels_video,
    _normalise_pixabay_photo,
    _normalise_pixabay_video,
)
from ai_fallback import (
    expand_keywords,
    score_asset_relevance,
    generate_subtitle,
    select_transition,
)


# ===========================================================================
# Fixtures
# ===========================================================================

SAMPLE_SEGMENT = {
    "id": "seg_001",
    "start": 0.0,
    "end": 5.0,
    "keywords": ["sunrise", "nature"],
    "subtitle": "Every journey begins with a single step.",
    "transition_in": "fade",
    "transition_out": "wipe",
    "voiceover_start": 0.0,
    "voiceover_end": 5.0,
}

SAMPLE_EDL = {
    "title": "Test Video",
    "fps": 30,
    "width": 1920,
    "height": 1080,
    "segments": [SAMPLE_SEGMENT],
}


# ===========================================================================
# stock_fetcher helpers
# ===========================================================================


class TestUrlToFilename:
    def test_deterministic(self):
        assert _url_to_filename("https://example.com/a.jpg") == _url_to_filename(
            "https://example.com/a.jpg"
        )

    def test_different_urls_give_different_names(self):
        assert _url_to_filename("https://a.com/x.jpg") != _url_to_filename(
            "https://b.com/y.jpg"
        )

    def test_extension_appended(self):
        name = _url_to_filename("https://example.com/img", ".png")
        assert name.endswith(".png")

    def test_length(self):
        name = _url_to_filename("https://example.com/test", ".jpg")
        assert len(name) == 20  # 16 hex chars + 4 for ".jpg"


class TestNormalisers:
    def test_pexels_photo(self):
        raw = {
            "id": 123,
            "src": {"small": "https://p.com/s.jpg", "original": "https://p.com/o.jpg"},
            "width": 800,
            "height": 600,
            "photographer": "Alice",
            "url": "https://pexels.com/photo/123",
        }
        result = _normalise_pexels_photo(raw)
        assert result["provider"] == "pexels"
        assert result["type"] == "photo"
        assert result["url"] == "https://p.com/s.jpg"
        assert result["photographer"] == "Alice"
        assert result["local_path"] is None

    def test_pexels_video_selects_smallest(self):
        raw = {
            "id": 42,
            "width": 1920,
            "height": 1080,
            "duration": 10,
            "url": "https://pexels.com/video/42",
            "video_files": [
                {"width": 1920, "link": "https://p.com/hd.mp4"},
                {"width": 640, "link": "https://p.com/sd.mp4"},
                {"width": 320, "link": "https://p.com/tiny.mp4"},
            ],
        }
        result = _normalise_pexels_video(raw)
        assert result["url"] == "https://p.com/tiny.mp4"
        assert result["type"] == "video"

    def test_pixabay_photo(self):
        raw = {
            "id": 99,
            "previewURL": "https://cdn.pixabay.com/photo/preview.jpg",
            "webformatWidth": 640,
            "webformatHeight": 480,
            "tags": "nature, sunset",
            "pageURL": "https://pixabay.com/photos/99",
        }
        result = _normalise_pixabay_photo(raw)
        assert result["provider"] == "pixabay"
        assert result["type"] == "photo"
        assert result["tags"] == "nature, sunset"

    def test_pixabay_video(self):
        raw = {
            "id": 77,
            "duration": 15,
            "tags": "ocean, waves",
            "pageURL": "https://pixabay.com/videos/77",
            "videos": {
                "small": {"url": "https://cdn.pixabay.com/video/small.mp4", "width": 640, "height": 360},
                "medium": {"url": "https://cdn.pixabay.com/video/medium.mp4", "width": 1280, "height": 720},
            },
        }
        result = _normalise_pixabay_video(raw)
        assert result["url"] == "https://cdn.pixabay.com/video/small.mp4"
        assert result["type"] == "video"


# ===========================================================================
# StockFetcher integration (mocked HTTP)
# ===========================================================================


class TestStockFetcherManifest:
    def _make_fetcher(self, tmp_path: Path, **kwargs) -> StockFetcher:
        return StockFetcher(
            cache_dir=tmp_path,
            pexels_key="fake_pexels",
            pixabay_key="fake_pixabay",
            max_per_segment=2,
            media_type="photo",
            **kwargs,
        )

    @patch("stock_fetcher._search_pexels_photos")
    @patch("stock_fetcher._search_pixabay_photos")
    @patch("stock_fetcher._download_file")
    def test_manifest_written(
        self, mock_dl, mock_pixabay, mock_pexels, tmp_path
    ):
        mock_pexels.return_value = [
            {
                "id": 1,
                "src": {"small": "https://p.com/s.jpg"},
                "width": 800,
                "height": 600,
                "photographer": "Bob",
                "url": "https://pexels.com/photo/1",
            }
        ]
        mock_pixabay.return_value = []
        mock_dl.return_value = True

        fetcher = self._make_fetcher(tmp_path)
        manifest = fetcher.process_segment(SAMPLE_SEGMENT)

        # Manifest should exist on disk
        manifest_path = tmp_path / "manifests" / "segment_seg_001.json"
        assert manifest_path.exists()

        with manifest_path.open() as fh:
            on_disk = json.load(fh)

        assert on_disk["segment_id"] == "seg_001"
        assert len(on_disk["assets"]) == 1
        assert on_disk["assets"][0]["provider"] == "pexels"

    @patch("stock_fetcher._search_pexels_photos")
    @patch("stock_fetcher._search_pixabay_photos")
    @patch("stock_fetcher._download_file")
    def test_process_edl_returns_all_manifests(
        self, mock_dl, mock_pixabay, mock_pexels, tmp_path
    ):
        mock_pexels.return_value = []
        mock_pixabay.return_value = []
        mock_dl.return_value = False

        edl = {
            "title": "Multi",
            "segments": [
                {**SAMPLE_SEGMENT, "id": "seg_001"},
                {**SAMPLE_SEGMENT, "id": "seg_002"},
            ],
        }
        fetcher = self._make_fetcher(tmp_path)
        manifests = fetcher.process_edl(edl)

        assert len(manifests) == 2
        assert {m["segment_id"] for m in manifests} == {"seg_001", "seg_002"}

    @patch("stock_fetcher._search_pexels_photos")
    @patch("stock_fetcher._search_pixabay_photos")
    @patch("stock_fetcher._download_file")
    def test_no_keys_produces_empty_assets(
        self, mock_dl, mock_pixabay, mock_pexels, tmp_path
    ):
        fetcher = StockFetcher(
            cache_dir=tmp_path,
            pexels_key="",
            pixabay_key="",
            max_per_segment=3,
            media_type="both",
        )
        manifest = fetcher.process_segment(SAMPLE_SEGMENT)
        assert manifest["assets"] == []
        # Neither search function should have been called
        mock_pexels.assert_not_called()
        mock_pixabay.assert_not_called()


# ===========================================================================
# ai_fallback
# ===========================================================================


class TestExpandKeywords:
    def test_returns_list(self):
        result = expand_keywords(["nature", "sunrise"])
        assert isinstance(result, list)

    def test_no_duplicates_with_input(self):
        result = expand_keywords(["nature"])
        for kw in result:
            assert kw not in ["nature"]

    def test_respects_n(self):
        result = expand_keywords(["nature", "ocean", "city"], n=2)
        assert len(result) <= 2

    def test_disabled_returns_empty(self):
        assert expand_keywords(["nature"], enabled=False) == []

    def test_empty_input(self):
        assert expand_keywords([]) == []


class TestScoreAssetRelevance:
    def test_exact_tag_match_scores_higher_than_no_match(self):
        seg = {"id": "s1", "keywords": ["ocean"], "subtitle": "blue waves"}
        asset_match = {"tags": "ocean sea waves", "id": "1"}
        asset_no_match = {"tags": "city urban street", "id": "2"}
        assert score_asset_relevance(asset_match, seg) > score_asset_relevance(
            asset_no_match, seg
        )

    def test_disabled_returns_half(self):
        seg = {"id": "s1", "keywords": ["x"], "subtitle": ""}
        asset = {"tags": "x y z"}
        assert score_asset_relevance(asset, seg, enabled=False) == 0.5

    def test_empty_metadata_returns_half(self):
        seg = {"id": "s1", "keywords": ["ocean"], "subtitle": ""}
        asset = {}
        assert score_asset_relevance(asset, seg) == 0.5


class TestGenerateSubtitle:
    def test_returns_existing_subtitle(self):
        seg = {**SAMPLE_SEGMENT}
        result = generate_subtitle(seg)
        assert result == SAMPLE_SEGMENT["subtitle"]

    def test_truncates_long_subtitle(self):
        long_text = "word " * 50
        seg = {"subtitle": long_text}
        result = generate_subtitle(seg, max_chars=30)
        assert len(result) <= 31  # allow for trailing ellipsis char
        assert result.endswith("…")

    def test_disabled_returns_as_is(self):
        seg = {"subtitle": "x " * 100}
        result = generate_subtitle(seg, max_chars=10, enabled=False)
        assert result == seg["subtitle"]


class TestSelectTransition:
    def test_uses_transition_out(self):
        seg_a = {"id": "a", "transition_out": "wipe"}
        seg_b = {"id": "b"}
        assert select_transition(seg_a, seg_b) == "wipe"

    def test_defaults_to_fade(self):
        seg_a = {"id": "a"}
        seg_b = {"id": "b"}
        assert select_transition(seg_a, seg_b) == "fade"

    def test_unknown_transition_falls_back_to_fade(self):
        seg_a = {"id": "a", "transition_out": "unknown_effect"}
        seg_b = {"id": "b"}
        assert select_transition(seg_a, seg_b) == "fade"

    def test_disabled_returns_fade(self):
        seg_a = {"id": "a", "transition_out": "wipe"}
        seg_b = {"id": "b"}
        assert select_transition(seg_a, seg_b, enabled=False) == "fade"


# ===========================================================================
# pipeline stage sentinels
# ===========================================================================


class TestStageSentinels:
    """Test the resume-from-stage caching logic in pipeline.py."""

    def test_sentinel_lifecycle(self, tmp_path):
        from pipeline import _is_done, _mark_done, _sentinel, _clear_from

        stages_dir = tmp_path / "stages"

        assert not _is_done(stages_dir, "fetch")
        _mark_done(stages_dir, "fetch")
        assert _is_done(stages_dir, "fetch")

    def test_clear_from_removes_later_stages(self, tmp_path):
        from pipeline import _is_done, _mark_done, _clear_from

        stages_dir = tmp_path / "stages"
        for stage in ["fetch", "normalize", "render", "mux"]:
            _mark_done(stages_dir, stage)

        _clear_from(stages_dir, "render")

        assert _is_done(stages_dir, "fetch")
        assert _is_done(stages_dir, "normalize")
        assert not _is_done(stages_dir, "render")
        assert not _is_done(stages_dir, "mux")
