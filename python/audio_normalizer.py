"""
audio_normalizer.py — Normalize voiceover audio using FFmpeg loudnorm filter.

Usage
-----
    python audio_normalizer.py --input  samples/voiceover.wav \
                               --output cache/voiceover_normalized.wav \
                               [--target-lufs -16] \
                               [--true-peak -1.5] \
                               [--lra 11]

Requirements
------------
    FFmpeg must be installed and available on PATH.
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

# EBU R128 / streaming-platform recommended defaults
DEFAULT_TARGET_LUFS = -16.0  # integrated loudness
DEFAULT_TRUE_PEAK = -1.5      # maximum true peak (dBTP)
DEFAULT_LRA = 11.0            # loudness range


def _run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    """Run a subprocess command, streaming output to the logger."""
    logger.debug("Running: %s", " ".join(cmd))
    result = subprocess.run(
        cmd, capture_output=True, text=True
    )
    if check and result.returncode != 0:
        raise RuntimeError(
            f"Command failed (exit {result.returncode}):\n"
            f"  cmd : {' '.join(cmd)}\n"
            f"  stderr: {result.stderr}"
        )
    return result


def _measure_loudness(input_path: Path) -> dict:
    """
    First-pass loudnorm measurement.
    Returns the JSON stats dict produced by FFmpeg.
    """
    cmd = [
        "ffmpeg", "-hide_banner", "-y",
        "-i", str(input_path),
        "-af", "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json",
        "-vn",
        "-f", "null", "-",
    ]
    result = _run(cmd, check=False)  # FFmpeg exits 0 even on stderr JSON output

    # FFmpeg prints the loudnorm JSON to stderr
    stderr = result.stderr
    # Extract JSON block (starts with '{' and ends with '}')
    start = stderr.rfind("{")
    end = stderr.rfind("}") + 1
    if start == -1 or end == 0:
        raise RuntimeError(
            f"Could not parse loudnorm JSON from FFmpeg output.\nstderr:\n{stderr}"
        )
    return json.loads(stderr[start:end])


def normalize_audio(
    input_path: Path,
    output_path: Path,
    target_lufs: float = DEFAULT_TARGET_LUFS,
    true_peak: float = DEFAULT_TRUE_PEAK,
    lra: float = DEFAULT_LRA,
) -> Path:
    """
    Two-pass EBU R128 loudness normalization.

    1. Measure actual loudness with a first-pass loudnorm filter.
    2. Apply corrective normalization in the second pass.

    Returns the *output_path*.
    """
    input_path = Path(input_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    logger.info("Measuring loudness of %s …", input_path)
    stats = _measure_loudness(input_path)
    logger.debug("Loudnorm stats: %s", stats)

    # Build second-pass filter string using measured values
    af = (
        f"loudnorm="
        f"I={target_lufs}:"
        f"TP={true_peak}:"
        f"LRA={lra}:"
        f"measured_I={stats['input_i']}:"
        f"measured_TP={stats['input_tp']}:"
        f"measured_LRA={stats['input_lra']}:"
        f"measured_thresh={stats['input_thresh']}:"
        f"offset={stats['target_offset']}:"
        f"linear=true:"
        f"print_format=summary"
    )

    logger.info("Applying normalization → %s", output_path)
    _run([
        "ffmpeg", "-hide_banner", "-y",
        "-i", str(input_path),
        "-af", af,
        "-ar", "48000",
        "-c:a", "pcm_s16le",
        str(output_path),
    ])

    logger.info("Normalized audio saved to %s", output_path)
    return output_path


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="EBU R128 two-pass audio loudness normalization via FFmpeg."
    )
    parser.add_argument("--input", required=True, help="Input audio file path")
    parser.add_argument("--output", required=True, help="Output audio file path")
    parser.add_argument(
        "--target-lufs",
        type=float,
        default=DEFAULT_TARGET_LUFS,
        help=f"Target integrated loudness in LUFS (default: {DEFAULT_TARGET_LUFS})",
    )
    parser.add_argument(
        "--true-peak",
        type=float,
        default=DEFAULT_TRUE_PEAK,
        help=f"Maximum true peak in dBTP (default: {DEFAULT_TRUE_PEAK})",
    )
    parser.add_argument(
        "--lra",
        type=float,
        default=DEFAULT_LRA,
        help=f"Loudness range target (default: {DEFAULT_LRA})",
    )
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
    normalize_audio(
        input_path=Path(args.input),
        output_path=Path(args.output),
        target_lufs=args.target_lufs,
        true_peak=args.true_peak,
        lra=args.lra,
    )


if __name__ == "__main__":
    main()
