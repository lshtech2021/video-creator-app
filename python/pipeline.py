"""
pipeline.py — End-to-end video-creation pipeline with resume-from-stage caching.

Stages
------
  1. fetch   — Download B-roll assets and write per-segment manifests
               (python/stock_fetcher.py).
  2. normalize — EBU R128 loudness normalization of the voiceover
               (python/audio_normalizer.py).
  3. render  — Render the Remotion composition to a ProRes/MP4 intermediate.
  4. mux     — Mix normalized audio + video with FFmpeg into the final MP4.

Resume-from-stage caching
--------------------------
Each stage writes a sentinel file  cache/stages/<stage>.done  on completion.
Re-running the pipeline skips any stage whose sentinel exists.
Pass ``--from-stage <name>`` to force restart from a specific stage,
which clears all sentinel files from that stage onward.

Usage
-----
    python pipeline.py \\
        --edl    samples/sample_edl.json \\
        --audio  samples/voiceover.wav \\
        --output output/final.mp4 \\
        [--cache-dir cache] \\
        [--from-stage fetch|normalize|render|mux] \\
        [--max-per-segment 3] \\
        [--media-type photo|video|both] \\
        [--fps 30] \\
        [--width 1920 --height 1080]

Environment variables
---------------------
    PEXELS_API_KEY   — API key for the Pexels stock service
    PIXABAY_API_KEY  — API key for the Pixabay stock service
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Local module imports (same package)
# ---------------------------------------------------------------------------
# Allow running from the repo root or from within python/
_HERE = Path(__file__).parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from stock_fetcher import StockFetcher                          # noqa: E402
from audio_normalizer import normalize_audio                    # noqa: E402

logger = logging.getLogger(__name__)

STAGES = ["fetch", "normalize", "render", "mux"]


# ---------------------------------------------------------------------------
# Stage sentinel helpers
# ---------------------------------------------------------------------------


def _sentinel(stages_dir: Path, stage: str) -> Path:
    return stages_dir / f"{stage}.done"


def _is_done(stages_dir: Path, stage: str) -> bool:
    return _sentinel(stages_dir, stage).exists()


def _mark_done(stages_dir: Path, stage: str) -> None:
    stages_dir.mkdir(parents=True, exist_ok=True)
    _sentinel(stages_dir, stage).touch()
    logger.debug("Stage '%s' marked as complete.", stage)


def _clear_from(stages_dir: Path, from_stage: str) -> None:
    """Remove sentinel files for *from_stage* and all subsequent stages."""
    idx = STAGES.index(from_stage)
    for stage in STAGES[idx:]:
        s = _sentinel(stages_dir, stage)
        if s.exists():
            s.unlink()
            logger.info("Cleared cached stage: %s", stage)


# ---------------------------------------------------------------------------
# Individual stage implementations
# ---------------------------------------------------------------------------


def stage_fetch(
    edl: dict,
    cache_dir: Path,
    pexels_key: str,
    pixabay_key: str,
    max_per_segment: int,
    media_type: str,
) -> list[dict]:
    """Stage 1 — Download B-roll assets and generate per-segment manifests."""
    logger.info("=== Stage: fetch ===")
    fetcher = StockFetcher(
        cache_dir=cache_dir,
        pexels_key=pexels_key,
        pixabay_key=pixabay_key,
        max_per_segment=max_per_segment,
        media_type=media_type,
    )
    manifests = fetcher.process_edl(edl)
    logger.info("Fetched assets for %d segment(s).", len(manifests))
    return manifests


def stage_normalize(
    audio_input: Path,
    cache_dir: Path,
) -> Path:
    """Stage 2 — EBU R128 loudness normalization of voiceover audio."""
    logger.info("=== Stage: normalize ===")
    output = cache_dir / "voiceover_normalized.wav"
    normalize_audio(audio_input, output)
    return output


def stage_render(
    edl: dict,
    cache_dir: Path,
    output_dir: Path,
    fps: int,
    width: int,
    height: int,
) -> Path:
    """
    Stage 3 — Render the Remotion composition.

    Requires Node.js and the Remotion project to be installed
    (see remotion/README.md).  The rendered silent video is saved to
    cache/render_output.mp4.
    """
    logger.info("=== Stage: render ===")

    # Write the full EDL + manifests bundle that Remotion reads
    bundle_path = cache_dir / "render_bundle.json"
    segments = edl.get("segments", [])
    bundle = {
        "edl": edl,
        "manifests": [],
        "fps": fps,
        "width": width,
        "height": height,
    }
    manifests_dir = cache_dir / "manifests"
    for seg in segments:
        seg_id = seg["id"]
        manifest_path = manifests_dir / f"segment_{seg_id}.json"
        if manifest_path.exists():
            with manifest_path.open(encoding="utf-8") as fh:
                bundle["manifests"].append(json.load(fh))
        else:
            logger.warning("Manifest not found for segment %s; skipping.", seg_id)

    with bundle_path.open("w", encoding="utf-8") as fh:
        json.dump(bundle, fh, indent=2)
    logger.debug("Render bundle written to %s", bundle_path)

    # Determine total duration from EDL
    total_duration = max(
        (seg.get("end", 0) for seg in segments), default=0
    )
    total_frames = int(total_duration * fps)

    render_output = cache_dir / "render_output.mp4"
    remotion_dir = Path(__file__).parent.parent / "remotion"

    if not remotion_dir.exists():
        raise FileNotFoundError(
            f"Remotion project not found at {remotion_dir}. "
            "Run 'npm install' inside the remotion/ directory first."
        )

    # Check that node_modules exist
    if not (remotion_dir / "node_modules").exists():
        logger.info("Installing Remotion dependencies …")
        subprocess.run(
            ["npm", "install"],
            cwd=str(remotion_dir),
            check=True,
        )

    cmd = [
        "npx", "remotion", "render",
        "VideoComposition",
        "--props", str(bundle_path.resolve()),
        "--output", str(render_output.resolve()),
        "--frames", f"0-{total_frames - 1}",
        "--fps", str(fps),
        "--width", str(width),
        "--height", str(height),
        "--codec", "h264",
        "--log", "verbose",
    ]
    logger.info("Running Remotion renderer …")
    subprocess.run(cmd, cwd=str(remotion_dir), check=True)
    logger.info("Render complete → %s", render_output)
    return render_output


def stage_mux(
    video_path: Path,
    audio_path: Path,
    output_path: Path,
) -> Path:
    """Stage 4 — Mux rendered video + normalized audio with FFmpeg."""
    logger.info("=== Stage: mux ===")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg", "-hide_banner", "-y",
        "-i", str(video_path),
        "-i", str(audio_path),
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",
        str(output_path),
    ]
    logger.info("Muxing video + audio …")
    subprocess.run(cmd, check=True)
    logger.info("Final video → %s", output_path)
    return output_path


# ---------------------------------------------------------------------------
# Pipeline orchestrator
# ---------------------------------------------------------------------------


def run_pipeline(args: argparse.Namespace) -> None:
    cache_dir = Path(args.cache_dir)
    stages_dir = cache_dir / "stages"
    output_path = Path(args.output)

    pexels_key = os.environ.get("PEXELS_API_KEY", "")
    pixabay_key = os.environ.get("PIXABAY_API_KEY", "")

    # Load EDL
    edl_path = Path(args.edl)
    with edl_path.open(encoding="utf-8") as fh:
        edl = json.load(fh)

    # Clear stages if --from-stage was specified
    if args.from_stage:
        if args.from_stage not in STAGES:
            logger.error("Unknown stage '%s'. Choose from: %s", args.from_stage, STAGES)
            sys.exit(1)
        _clear_from(stages_dir, args.from_stage)

    # ---- Stage 1: fetch ----
    if _is_done(stages_dir, "fetch"):
        logger.info("Skipping 'fetch' (already done). Pass --from-stage fetch to redo.")
    else:
        stage_fetch(
            edl=edl,
            cache_dir=cache_dir,
            pexels_key=pexels_key,
            pixabay_key=pixabay_key,
            max_per_segment=args.max_per_segment,
            media_type=args.media_type,
        )
        _mark_done(stages_dir, "fetch")

    # ---- Stage 2: normalize ----
    normalized_audio = cache_dir / "voiceover_normalized.wav"
    if _is_done(stages_dir, "normalize"):
        logger.info("Skipping 'normalize' (already done). Pass --from-stage normalize to redo.")
    else:
        audio_path = Path(args.audio)
        if not audio_path.exists():
            logger.warning(
                "Audio file not found: %s — skipping normalization.", audio_path
            )
            normalized_audio = audio_path  # fall back to original (if it exists later)
        else:
            normalized_audio = stage_normalize(audio_path, cache_dir)
            _mark_done(stages_dir, "normalize")

    # ---- Stage 3: render ----
    render_output = cache_dir / "render_output.mp4"
    if _is_done(stages_dir, "render"):
        logger.info("Skipping 'render' (already done). Pass --from-stage render to redo.")
    else:
        try:
            render_output = stage_render(
                edl=edl,
                cache_dir=cache_dir,
                output_dir=output_path.parent,
                fps=args.fps,
                width=args.width,
                height=args.height,
            )
            _mark_done(stages_dir, "render")
        except Exception as exc:
            logger.error("Render stage failed: %s", exc)
            logger.info(
                "Tip: make sure Node.js is installed and run 'npm install' "
                "inside the remotion/ directory."
            )
            sys.exit(1)

    # ---- Stage 4: mux ----
    if _is_done(stages_dir, "mux"):
        logger.info("Skipping 'mux' (already done). Pass --from-stage mux to redo.")
    else:
        if not normalized_audio.exists():
            logger.error(
                "Normalized audio not found at %s — cannot mux.", normalized_audio
            )
            sys.exit(1)
        stage_mux(
            video_path=render_output,
            audio_path=normalized_audio,
            output_path=output_path,
        )
        _mark_done(stages_dir, "mux")

    logger.info("Pipeline complete. Output: %s", output_path)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="End-to-end video-creation pipeline."
    )
    parser.add_argument(
        "--edl", required=True, help="Path to the EDL JSON file"
    )
    parser.add_argument(
        "--audio", required=True, help="Path to the voiceover audio file"
    )
    parser.add_argument(
        "--output", default="output/final.mp4", help="Output video path"
    )
    parser.add_argument(
        "--cache-dir", default="cache", help="Root cache directory (default: cache)"
    )
    parser.add_argument(
        "--from-stage",
        choices=STAGES,
        default=None,
        help="Force re-run from this stage (clears later sentinels)",
    )
    parser.add_argument(
        "--max-per-segment", type=int, default=3,
        help="Max assets per segment per provider (default: 3)"
    )
    parser.add_argument(
        "--media-type", choices=["photo", "video", "both"], default="both",
        help="Media type to fetch (default: both)"
    )
    parser.add_argument("--fps", type=int, default=30, help="Output FPS (default: 30)")
    parser.add_argument("--width", type=int, default=1920, help="Output width (default: 1920)")
    parser.add_argument("--height", type=int, default=1080, help="Output height (default: 1080)")
    parser.add_argument(
        "--log-level", default="INFO", help="Logging level (default: INFO)"
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    run_pipeline(args)


if __name__ == "__main__":
    main()
