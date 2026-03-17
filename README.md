# video-creator-app

An automated, end-to-end video-creation pipeline that converts a voiceover
audio file + an EDL (Edit Decision List) JSON into a rendered MP4.

```
EDL JSON + voiceover.wav
        │
        ▼
  ┌─────────────┐   PEXELS_API_KEY
  │  1. Fetch   │◄──PIXABAY_API_KEY
  │  B-roll     │
  └──────┬──────┘
         │ cache/manifests/segment_*.json
         │ cache/assets/<seg_id>/
         ▼
  ┌─────────────────┐
  │ 2. Normalize    │  EBU R128 loudnorm (FFmpeg)
  │   voiceover     │
  └──────┬──────────┘
         │ cache/voiceover_normalized.wav
         ▼
  ┌────────────────┐
  │  3. Render     │  Remotion → silent MP4
  │  (Remotion)    │
  └──────┬─────────┘
         │ cache/render_output.mp4
         ▼
  ┌────────────────┐
  │  4. Mux        │  FFmpeg: merge audio + video
  └──────┬─────────┘
         │
         ▼
     output/final.mp4
```

---

## Repository layout

```
video-creator-app/
├── python/
│   ├── stock_fetcher.py      # B-roll asset fetcher (Pexels + Pixabay)
│   ├── audio_normalizer.py   # EBU R128 loudness normalization
│   ├── ai_fallback.py        # AI fallback stubs (keyword expansion, scoring …)
│   ├── pipeline.py           # End-to-end orchestrator with resume-from-stage
│   ├── requirements.txt
│   └── tests/
│       └── test_pipeline.py
├── remotion/
│   ├── src/
│   │   ├── index.ts          # Remotion entry point
│   │   ├── Root.tsx          # Composition registry
│   │   ├── Composition.tsx   # Main video composition
│   │   ├── Segment.tsx       # Per-segment B-roll + subtitle scene
│   │   ├── Subtitle.tsx      # Animated subtitle overlay
│   │   ├── Transitions.tsx   # Fade / wipe / dissolve transition overlays
│   │   └── types.ts          # Shared TypeScript types
│   ├── package.json
│   ├── tsconfig.json
│   └── remotion.config.ts
├── samples/
│   └── sample_edl.json       # Example 30-second EDL
├── cache/                    # Runtime-generated (gitignored except .gitkeep)
│   ├── assets/               # Downloaded stock images & clips
│   ├── manifests/            # Per-segment manifest JSONs
│   └── stages/               # Stage-completion sentinels
├── .gitignore
└── README.md
```

---

## Requirements

| Tool | Version | Notes |
|------|---------|-------|
| Python | ≥ 3.9 | pipeline + asset fetcher |
| Node.js | ≥ 18 | Remotion renderer |
| FFmpeg | ≥ 5 | normalization + mux |

### API keys (environment variables)

| Variable | Service | Where to get it |
|----------|---------|-----------------|
| `PEXELS_API_KEY` | [Pexels](https://www.pexels.com/api/) | Free registration |
| `PIXABAY_API_KEY` | [Pixabay](https://pixabay.com/api/docs/) | Free registration |

At least one key must be set for B-roll assets to be downloaded.
The pipeline will still run without keys; segments will simply render with a
colour-gradient placeholder instead of real footage.

---

## Quick start

### 1 — Install Python dependencies

```bash
cd python
pip install -r requirements.txt
```

### 2 — Install Remotion dependencies

```bash
cd remotion
npm install
```

### 3 — Export API keys

```bash
export PEXELS_API_KEY="your_pexels_key_here"
export PIXABAY_API_KEY="your_pixabay_key_here"
```

### 4 — Prepare a voiceover file

Place your voiceover WAV/MP3 at `samples/voiceover.wav` (or any path; pass it
with `--audio`).

### 5 — Run the full pipeline

```bash
cd /path/to/video-creator-app

python python/pipeline.py \
    --edl    samples/sample_edl.json \
    --audio  samples/voiceover.wav \
    --output output/final.mp4
```

The pipeline prints progress for each stage.  On success, the final video is
written to `output/final.mp4`.

---

## Running individual stages

### Stock fetcher only

```bash
python python/stock_fetcher.py \
    --edl            samples/sample_edl.json \
    --cache-dir      cache \
    --max-per-segment 3 \
    --media-type     both
```

Manifests are written to `cache/manifests/segment_<id>.json`.

### Audio normalization only

```bash
python python/audio_normalizer.py \
    --input  samples/voiceover.wav \
    --output cache/voiceover_normalized.wav
```

### Remotion Studio (preview in browser)

```bash
cd remotion
npm start
```

### Remotion CLI render

```bash
cd remotion
npx remotion render src/index.ts VideoComposition \
    --props ../cache/render_bundle.json \
    --output ../cache/render_output.mp4
```

---

## Resume-from-stage caching

The pipeline writes a sentinel file `cache/stages/<stage>.done` after each
successful stage.  Re-running the pipeline will skip completed stages.

To restart from a specific stage (and all later stages):

```bash
python python/pipeline.py \
    --edl   samples/sample_edl.json \
    --audio samples/voiceover.wav \
    --from-stage render     # re-runs render + mux, skips fetch + normalize
```

Available stages (in order): `fetch` → `normalize` → `render` → `mux`.

---

## EDL JSON schema

```jsonc
{
  "title": "My Video",
  "fps": 30,
  "width": 1920,
  "height": 1080,
  "segments": [
    {
      "id": "seg_001",          // unique identifier
      "start": 0.0,             // segment start time in seconds
      "end": 5.0,               // segment end time in seconds
      "keywords": ["sunset"],   // B-roll search keywords
      "subtitle": "Hello!",     // on-screen caption
      "transition_in": "fade",  // fade | wipe | dissolve | slide | zoom
      "transition_out": "fade",
      "voiceover_start": 0.0,   // voiceover timestamp range
      "voiceover_end": 5.0
    }
    // … more segments
  ]
}
```

See `samples/sample_edl.json` for a complete 5-segment, 30-second example.

---

## Per-segment manifest schema

Each manifest is written to `cache/manifests/segment_<id>.json`:

```jsonc
{
  "segment_id": "seg_001",
  "start": 0.0,
  "end": 5.0,
  "keywords": ["sunrise", "nature"],
  "subtitle": "Every journey begins with a single step.",
  "transition_in": "fade",
  "transition_out": "fade",
  "voiceover_start": 0.0,
  "voiceover_end": 5.0,
  "assets": [
    {
      "provider": "pexels",       // "pexels" | "pixabay"
      "type": "photo",            // "photo" | "video"
      "id": "12345",
      "url": "https://…",         // remote URL (fallback)
      "width": 800,
      "height": 600,
      "local_path": "assets/seg_001/abc123def456.jpg",  // relative to cache/
      "photographer": "Alice"
    }
    // … more assets
  ]
}
```

---

## AI fallback stubs

`python/ai_fallback.py` provides lightweight stubs that are called when
automated stock searches return too few results:

| Function | Stub behaviour | Production replacement |
|----------|---------------|------------------------|
| `expand_keywords` | Hand-coded synonym map | LLM keyword brainstorming |
| `score_asset_relevance` | Keyword overlap scoring | CLIP visual similarity |
| `generate_subtitle` | Truncates existing text | Whisper transcription / LLM |
| `select_transition` | Uses `transition_out` from EDL | Mood-based visual model |

All stubs accept an `enabled=False` flag for easy testing.

---

## Running the tests

```bash
pip install pytest
cd python
python -m pytest tests/ -v
```

---

## Extending the pipeline

| Phase | What to build | Where |
|-------|--------------|-------|
| Production stock sourcing | Replace stub calls with real Pexels/Pixabay pagination + deduplication | `python/stock_fetcher.py` |
| Real AI scoring | Swap `ai_fallback.score_asset_relevance` for a CLIP model | `python/ai_fallback.py` |
| Real subtitles | Replace `ai_fallback.generate_subtitle` with Whisper | `python/ai_fallback.py` |
| Advanced transitions | Implement `slide` / `zoom` in `Transitions.tsx` | `remotion/src/Transitions.tsx` |
| Audio ducking | Add a ducking pass to `audio_normalizer.py` | `python/audio_normalizer.py` |
| Parallel fetch | Parallelize segment processing with `concurrent.futures` | `python/stock_fetcher.py` |
