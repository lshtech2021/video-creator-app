/**
 * Root.tsx — Remotion root: registers the VideoComposition.
 *
 * The default props here are used when previewing in Remotion Studio.
 * The pipeline passes real props via --props during CLI rendering.
 */

import React from "react";
import { Composition } from "remotion";
import { VideoComposition } from "./Composition";
import { RenderBundle } from "./types";

const DEFAULT_PROPS: RenderBundle = {
  fps: 30,
  width: 1920,
  height: 1080,
  edl: {
    title: "Preview",
    fps: 30,
    width: 1920,
    height: 1080,
    segments: [
      {
        id: "seg_001",
        start: 0,
        end: 5,
        keywords: ["sunrise", "nature"],
        subtitle: "Every journey begins with a single step.",
        transition_in: "fade",
        transition_out: "fade",
        voiceover_start: 0,
        voiceover_end: 5,
      },
    ],
  },
  manifests: [],
};

export const RemotionRoot: React.FC = () => {
  return (
    <Composition
      id="VideoComposition"
      component={VideoComposition}
      durationInFrames={150}
      fps={DEFAULT_PROPS.fps}
      width={DEFAULT_PROPS.width}
      height={DEFAULT_PROPS.height}
      defaultProps={DEFAULT_PROPS}
      calculateMetadata={({ props }) => {
        // Compute total duration from the EDL
        const totalSec = props.edl.segments.reduce(
          (acc, seg) => acc + (seg.end - seg.start),
          0
        );
        return {
          durationInFrames: Math.max(1, Math.round(totalSec * props.fps)),
          fps: props.fps,
          width: props.width,
          height: props.height,
        };
      }}
    />
  );
};
