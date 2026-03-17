/**
 * Composition.tsx — Main Remotion composition: sequences all EDL segments.
 *
 * The component reads the `RenderBundle` from Remotion's `inputProps` and
 * renders each segment in order using the `<Sequence>` primitive.
 */

import React from "react";
import { Sequence, useVideoConfig } from "remotion";
import { SegmentScene } from "./Segment";
import { RenderBundle, SegmentManifest } from "./types";

interface CompositionProps extends RenderBundle {}

export const VideoComposition: React.FC<CompositionProps> = ({
  edl,
  manifests,
  fps,
  cacheDir,
}) => {
  const { fps: videoFps } = useVideoConfig();
  const activeFps = fps ?? videoFps;

  // Build a lookup map from segment_id → manifest
  const manifestMap = new Map<string, SegmentManifest>(
    manifests.map((m) => [m.segment_id, m])
  );

  let cursor = 0;

  return (
    <>
      {edl.segments.map((segment) => {
        const manifest = manifestMap.get(segment.id) ?? {
          segment_id: segment.id,
          start: segment.start,
          end: segment.end,
          keywords: segment.keywords,
          subtitle: segment.subtitle,
          transition_in: segment.transition_in,
          transition_out: segment.transition_out,
          voiceover_start: segment.voiceover_start,
          voiceover_end: segment.voiceover_end,
          assets: [],
        };

        const durationSec = segment.end - segment.start;
        const durationFrames = Math.round(durationSec * activeFps);
        const from = cursor;
        cursor += durationFrames;

        return (
          <Sequence
            key={segment.id}
            from={from}
            durationInFrames={durationFrames}
          >
            <SegmentScene
              manifest={manifest}
              durationFrames={durationFrames}
              fps={activeFps}
              cacheDir={cacheDir}
            />
          </Sequence>
        );
      })}
    </>
  );
};
