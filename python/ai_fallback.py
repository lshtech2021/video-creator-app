"""
ai_fallback.py — Lightweight AI fallback stubs for the video-creator pipeline.

When automated stock searches return too few results (or none), these stubs
provide a graceful degradation path.  Each function is designed as a drop-in
replacement that can later be swapped for a real model call without changing
the calling interface.

Stub behaviour
--------------
All functions are fully functional stubs:
  • They log what they *would* do.
  • They return sensible, deterministic default values.
  • They accept the same arguments a production implementation would.
  • Where applicable, they expose an ``enabled`` parameter so tests can
    selectively disable AI without monkey-patching.
"""

from __future__ import annotations

import logging
import random
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Keyword expansion stub
# ---------------------------------------------------------------------------


def expand_keywords(
    keywords: list[str],
    *,
    n: int = 3,
    enabled: bool = True,
) -> list[str]:
    """
    Return *n* additional search terms derived from *keywords*.

    Production replacement: call an LLM (e.g. GPT-4o) to brainstorm
    semantically related B-roll search terms.

    Stub behaviour: applies simple hand-coded synonym rules and returns at
    most *n* extra terms.
    """
    if not enabled or not keywords:
        return []

    synonym_map: dict[str, list[str]] = {
        "nature": ["outdoor", "landscape", "wildlife"],
        "sunrise": ["dawn", "golden hour", "morning light"],
        "sunset": ["dusk", "twilight", "evening glow"],
        "ocean": ["sea", "waves", "coast", "shoreline"],
        "forest": ["woods", "trees", "canopy", "jungle"],
        "mountain": ["peak", "summit", "alpine", "highland"],
        "city": ["urban", "skyline", "downtown", "street"],
        "people": ["crowd", "community", "portrait", "team"],
        "technology": ["tech", "digital", "innovation", "device"],
    }

    extras: list[str] = []
    for kw in keywords:
        for key, synonyms in synonym_map.items():
            if key in kw.lower():
                extras.extend(s for s in synonyms if s not in keywords)
    # Shuffle for variety and cap at n
    random.shuffle(extras)
    result = list(dict.fromkeys(extras))[:n]  # deduplicate, preserve order
    logger.debug(
        "AI keyword expansion (stub): %s → +%s", keywords, result
    )
    return result


# ---------------------------------------------------------------------------
# Asset relevance scorer stub
# ---------------------------------------------------------------------------


def score_asset_relevance(
    asset: dict[str, Any],
    segment: dict[str, Any],
    *,
    enabled: bool = True,
) -> float:
    """
    Return a float in [0, 1] representing how relevant *asset* is for *segment*.

    Production replacement: use a CLIP-style model or an LLM-based vision
    classifier to score image/video thumbnails against the segment's keywords
    and subtitle text.

    Stub behaviour: assigns a score based on naive keyword overlap between the
    asset's ``tags`` / ``photographer`` fields and the segment keywords.
    Falls back to 0.5 when no metadata is available.
    """
    if not enabled:
        return 0.5

    keywords = [k.lower() for k in segment.get("keywords", [])]
    subtitle_words = segment.get("subtitle", "").lower().split()
    target_words = set(keywords + subtitle_words)

    # Collect searchable text from the asset record
    asset_text = " ".join(
        filter(None, [
            asset.get("tags", ""),
            asset.get("photographer", ""),
            str(asset.get("id", "")),
        ])
    ).lower()

    if not target_words or not asset_text:
        return 0.5

    matches = sum(1 for w in target_words if w in asset_text)
    score = min(1.0, matches / max(len(target_words), 1))
    logger.debug(
        "AI relevance score (stub): asset=%s segment=%s score=%.2f",
        asset.get("id"),
        segment.get("id"),
        score,
    )
    return score


# ---------------------------------------------------------------------------
# Subtitle generation stub
# ---------------------------------------------------------------------------


def generate_subtitle(
    segment: dict[str, Any],
    *,
    max_chars: int = 120,
    enabled: bool = True,
) -> str:
    """
    Generate (or refine) the subtitle text for a segment.

    Production replacement: call Whisper to transcribe the voiceover audio
    slice, or an LLM to write a concise on-screen caption.

    Stub behaviour: returns the existing ``subtitle`` field, truncated to
    *max_chars*.  If the field is absent or empty it returns an empty string.
    """
    if not enabled:
        return segment.get("subtitle", "")

    text = segment.get("subtitle", "")
    if len(text) > max_chars:
        text = text[:max_chars].rsplit(" ", 1)[0] + "…"
        logger.debug(
            "AI subtitle generation (stub): truncated to %d chars for segment %s",
            max_chars,
            segment.get("id"),
        )
    return text


# ---------------------------------------------------------------------------
# Transition selector stub
# ---------------------------------------------------------------------------

AVAILABLE_TRANSITIONS = ["fade", "wipe", "dissolve", "slide", "zoom"]


def select_transition(
    segment_a: dict[str, Any],
    segment_b: dict[str, Any],
    *,
    enabled: bool = True,
) -> str:
    """
    Select the best transition between two consecutive segments.

    Production replacement: use a visual similarity model to choose a
    transition that matches the mood shift between consecutive clips.

    Stub behaviour: returns the ``transition_out`` value of *segment_a* if
    present, otherwise defaults to ``"fade"``.
    """
    if not enabled:
        return "fade"

    transition = segment_a.get("transition_out", "fade")
    if transition not in AVAILABLE_TRANSITIONS:
        logger.warning(
            "Unknown transition '%s' in segment %s; defaulting to 'fade'.",
            transition,
            segment_a.get("id"),
        )
        transition = "fade"
    logger.debug(
        "AI transition selection (stub): %s → %s = %s",
        segment_a.get("id"),
        segment_b.get("id"),
        transition,
    )
    return transition
