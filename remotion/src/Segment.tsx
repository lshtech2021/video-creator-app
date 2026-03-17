/**
 * Segment.tsx — Renders a single EDL segment: B-roll asset + subtitle.
 *
 * The component:
 *  1. Displays the best available asset (prefers video, falls back to image,
 *     falls back to a colour placeholder when no assets are present).
 *  2. Overlays the animated subtitle.
 *  3. Renders the transition-in and transition-out overlays.
 */

import React from "react";
import { Img, Video, interpolate, useCurrentFrame } from "remotion";
import { Subtitle } from "./Subtitle";
import { TransitionOverlay, TransitionType } from "./Transitions";
import { AssetRecord, SegmentManifest } from "./types";

const TRANSITION_FRAMES = 15; // number of frames for each transition

interface SegmentProps {
  manifest: SegmentManifest;
  /** Total duration of this segment in frames */
  durationFrames: number;
  fps: number;
  /** Base URL for cached assets. Defaults to "/cache". Override in deployments. */
  cacheDir?: string;
}

/** Pick the best asset from the manifest (prefer video, then photo). */
function pickAsset(assets: AssetRecord[]): AssetRecord | null {
  if (!assets || assets.length === 0) return null;
  // Prefer video assets with a local_path
  const localVideo = assets.find(
    (a) => a.type === "video" && a.local_path
  );
  if (localVideo) return localVideo;
  // Then any video
  const anyVideo = assets.find((a) => a.type === "video");
  if (anyVideo) return anyVideo;
  // Then local photo
  const localPhoto = assets.find(
    (a) => a.type === "photo" && a.local_path
  );
  if (localPhoto) return localPhoto;
  // Then any photo
  return assets[0] ?? null;
}

/** Resolve asset URL: prefer local cache path, fall back to remote URL. */
function resolveUrl(asset: AssetRecord, cacheDir = "/cache"): string {
  if (asset.local_path) {
    // local_path is relative to cache root; serve via the Remotion dev server
    return `${cacheDir}/${asset.local_path}`;
  }
  return asset.url;
}

export const SegmentScene: React.FC<SegmentProps> = ({
  manifest,
  durationFrames,
  fps,
  cacheDir = "/cache",
}) => {
  const frame = useCurrentFrame();
  const asset = pickAsset(manifest.assets);

  // Transition-in: progress goes 0→1 over the first TRANSITION_FRAMES
  const transitionInProgress = interpolate(
    frame,
    [0, TRANSITION_FRAMES],
    [0, 1],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  // Transition-out: progress goes 0→1 over the last TRANSITION_FRAMES
  const transitionOutOpacity = interpolate(
    frame,
    [durationFrames - TRANSITION_FRAMES, durationFrames],
    [0, 1],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  const containerStyle: React.CSSProperties = {
    position: "relative",
    width: "100%",
    height: "100%",
    background: "#111",
    overflow: "hidden",
  };

  const mediaStyle: React.CSSProperties = {
    position: "absolute",
    inset: 0,
    width: "100%",
    height: "100%",
    objectFit: "cover",
  };

  return (
    <div style={containerStyle}>
      {/* B-roll media layer */}
      {asset ? (
        asset.type === "video" ? (
          <Video
            src={resolveUrl(asset, cacheDir)}
            style={mediaStyle}
            muted
            loop
          />
        ) : (
          <Img
            src={resolveUrl(asset, cacheDir)}
            style={{
              ...mediaStyle,
              // Subtle Ken Burns zoom for static images
              transform: `scale(${1 + frame * 0.0003})`,
              transformOrigin: "center",
            }}
          />
        )
      ) : (
        /* Placeholder gradient when no asset is available */
        <div
          style={{
            ...mediaStyle,
            background:
              "linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%)",
          }}
        />
      )}

      {/* Transition-in overlay */}
      <TransitionOverlay
        type={manifest.transition_in as TransitionType}
        progress={transitionInProgress}
      />

      {/* Subtitle */}
      {manifest.subtitle && (
        <Subtitle
          text={manifest.subtitle}
          durationFrames={durationFrames}
          fadeInFrames={12}
          fadeOutFrames={12}
        />
      )}

      {/* Transition-out overlay */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          background: `rgba(0,0,0,${transitionOutOpacity})`,
          pointerEvents: "none",
        }}
      />
    </div>
  );
};
