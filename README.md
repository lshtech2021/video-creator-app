# video-creator-app

Automated video-creation pipeline that fetches stock assets from
[Pexels](https://www.pexels.com/) and [Pixabay](https://pixabay.com/),
downloads low-resolution previews for offline editing, and produces
per-segment JSON manifests ready for downstream composition.

---

## Repository layout

```
video-creator-app/
├── python/
│   └── stock_fetcher.py   # MVP stock-media fetcher (search + download + manifests)
├── cache/
│   ├── assets/            # Downloaded preview files (git-ignored by content)
│   └── manifests/         # Generated segment_<n>.json manifests
└── README.md
```

---

## Quick start

### 1 – Prerequisites

* Python 3.9+
* A free [Pexels API key](https://www.pexels.com/api/)
* A free [Pixabay API key](https://pixabay.com/api/docs/)

### 2 – Environment variables

```bash
export PEXELS_API_KEY="your-pexels-key"
export PIXABAY_API_KEY="your-pixabay-key"
```

### 3 – Run the fetcher

```bash
# From the repository root
python python/stock_fetcher.py \
  --query "ocean sunset" \
  --segments 3 \
  --per-segment 2
```

This will:

1. Search Pexels and Pixabay for *"ocean sunset"* videos.
2. Download up to **6** (3 × 2) preview files to `cache/assets/`.
3. Write three manifests: `cache/manifests/segment_0.json`, `segment_1.json`, `segment_2.json`.

### CLI options

| Flag | Default | Description |
|------|---------|-------------|
| `--query` | *(required)* | Search term |
| `--segments N` | `3` | Number of video segments |
| `--per-segment N` | `2` | Assets per segment |
| `--media-type` | `video` | `video`, `photo`, or `both` |
| `--pexels-key` | env var | Pexels API key override |
| `--pixabay-key` | env var | Pixabay API key override |
| `--log-level` | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |

### Programmatic usage

```python
from python.stock_fetcher import run_pipeline

manifests = run_pipeline(
    query="mountain landscape",
    num_segments=5,
    assets_per_segment=3,
    media_type="video",
)
```

---

## Manifest format

Each `cache/manifests/segment_<n>.json` looks like:

```json
{
  "segment_index": 0,
  "query": "ocean sunset",
  "generated_at": "2024-01-15T12:00:00Z",
  "assets_per_segment": 2,
  "assets": [
    {
      "provider": "pexels",
      "type": "video",
      "id": "12345",
      "url": "https://...",
      "width": 640,
      "height": 360,
      "duration": 15,
      "thumbnail": "https://...",
      "source_page": "https://www.pexels.com/video/...",
      "license": "Pexels License",
      "local_path": "cache/assets/pexels_12345.mp4"
    }
  ]
}
```

---

## Notes

* Preview assets stored in `cache/assets/` are **not committed** to git
  (see `.gitignore`).  Only the generated manifests are tracked.
* Both API keys are optional individually; the fetcher will skip a provider
  whose key is absent and log a warning.
