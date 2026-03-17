/**
 * index.ts — Remotion entry point.
 *
 * Remotion discovers compositions by importing this file via
 * the `"remotion": "./src/index.ts"` field in package.json.
 */
import { registerRoot } from "remotion";
import { RemotionRoot } from "./Root";

registerRoot(RemotionRoot);
