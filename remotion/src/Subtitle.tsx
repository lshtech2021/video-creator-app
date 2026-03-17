/**
 * Subtitle.tsx — Animated subtitle overlay component.
 *
 * Renders the segment subtitle text with a fade-in animation,
 * positioned at the bottom of the frame.
 */

import React from "react";
import { interpolate, useCurrentFrame, useVideoConfig } from "remotion";

interface SubtitleProps {
  text: string;
  /** Duration in frames for the fade-in animation */
  fadeInFrames?: number;
  /** Duration in frames for the fade-out animation */
  fadeOutFrames?: number;
  /** Total duration of this subtitle in frames */
  durationFrames: number;
}

export const Subtitle: React.FC<SubtitleProps> = ({
  text,
  fadeInFrames = 10,
  fadeOutFrames = 10,
  durationFrames,
}) => {
  const frame = useCurrentFrame();

  const opacity = interpolate(
    frame,
    [0, fadeInFrames, durationFrames - fadeOutFrames, durationFrames],
    [0, 1, 1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  return (
    <div
      style={{
        position: "absolute",
        bottom: 80,
        left: "10%",
        right: "10%",
        textAlign: "center",
        opacity,
        padding: "12px 24px",
        borderRadius: 8,
        background: "rgba(0,0,0,0.55)",
        backdropFilter: "blur(4px)",
      }}
    >
      <span
        style={{
          fontFamily: "'Inter', 'Helvetica Neue', Arial, sans-serif",
          fontSize: 38,
          fontWeight: 600,
          color: "#ffffff",
          textShadow: "0 2px 8px rgba(0,0,0,0.8)",
          letterSpacing: "0.01em",
          lineHeight: 1.4,
        }}
      >
        {text}
      </span>
    </div>
  );
};
