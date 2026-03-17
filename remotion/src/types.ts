/**
 * types.ts — Shared TypeScript types for the Remotion composition.
 *
 * These mirror the JSON structures produced by the Python pipeline
 * (stock_fetcher.py and pipeline.py).
 */

export interface AssetRecord {
  provider: "pexels" | "pixabay";
  type: "photo" | "video";
  id: string;
  url: string;
  width: number;
  height: number;
  local_path: string | null;
  /** Additional provider-specific fields */
  [key: string]: unknown;
}

export interface SegmentManifest {
  segment_id: string;
  start: number;
  end: number;
  keywords: string[];
  subtitle: string;
  transition_in: TransitionType;
  transition_out: TransitionType;
  voiceover_start: number | null;
  voiceover_end: number | null;
  assets: AssetRecord[];
}

export type TransitionType = "fade" | "wipe" | "dissolve" | "slide" | "zoom";

export interface EdlSegment {
  id: string;
  start: number;
  end: number;
  keywords: string[];
  subtitle: string;
  transition_in: TransitionType;
  transition_out: TransitionType;
  voiceover_start: number;
  voiceover_end: number;
}

export interface Edl {
  title: string;
  fps: number;
  width: number;
  height: number;
  segments: EdlSegment[];
}

export interface RenderBundle {
  edl: Edl;
  manifests: SegmentManifest[];
  fps: number;
  width: number;
  height: number;
  /** Base URL used to serve cached assets (default: "/cache"). */
  cacheDir?: string;
}
