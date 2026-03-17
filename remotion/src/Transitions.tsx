/**
 * Transitions.tsx — Transition overlay components.
 *
 * Each component receives a `progress` value in [0, 1] and renders
 * the appropriate visual transition effect.
 *
 * Usage: place the component on top of the incoming clip during the
 * transition window and drive `progress` with `interpolate`.
 */

import React, { CSSProperties } from "react";

// ---------------------------------------------------------------------------
// Fade transition
// ---------------------------------------------------------------------------

interface FadeProps {
  /** 0 = fully transparent (incoming clip invisible), 1 = fully opaque */
  progress: number;
}

export const FadeTransition: React.FC<FadeProps> = ({ progress }) => (
  <div
    style={{
      position: "absolute",
      inset: 0,
      background: `rgba(0,0,0,${1 - progress})`,
      pointerEvents: "none",
    }}
  />
);

// ---------------------------------------------------------------------------
// Wipe transition (left-to-right reveal)
// ---------------------------------------------------------------------------

interface WipeProps {
  /** 0 = no reveal, 1 = fully revealed */
  progress: number;
}

export const WipeTransition: React.FC<WipeProps> = ({ progress }) => {
  const clipPath = `inset(0 ${(1 - progress) * 100}% 0 0)`;
  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        clipPath,
        background: "transparent",
        pointerEvents: "none",
      }}
    />
  );
};

// ---------------------------------------------------------------------------
// Dissolve transition (cross-fade between two layers)
// ---------------------------------------------------------------------------

interface DissolveProps {
  progress: number;
}

export const DissolveTransition: React.FC<DissolveProps> = ({ progress }) => (
  <div
    style={{
      position: "absolute",
      inset: 0,
      opacity: 1 - progress,
      background: "black",
      pointerEvents: "none",
    }}
  />
);

// ---------------------------------------------------------------------------
// Transition selector helper
// ---------------------------------------------------------------------------

export type TransitionType = "fade" | "wipe" | "dissolve" | "slide" | "zoom";

interface TransitionOverlayProps {
  type: TransitionType;
  /** 0 = start of transition, 1 = end of transition */
  progress: number;
}

/**
 * Renders the appropriate transition component for the given `type`.
 * Falls back to FadeTransition for unknown types.
 */
export const TransitionOverlay: React.FC<TransitionOverlayProps> = ({
  type,
  progress,
}) => {
  switch (type) {
    case "wipe":
      return <WipeTransition progress={progress} />;
    case "dissolve":
      return <DissolveTransition progress={progress} />;
    case "slide":
      // Slide is implemented as a wipe for the MVP; extend here later.
      return <WipeTransition progress={progress} />;
    case "zoom":
      // Zoom is implemented as a dissolve for the MVP; extend here later.
      return <DissolveTransition progress={progress} />;
    case "fade":
    default:
      return <FadeTransition progress={progress} />;
  }
};
