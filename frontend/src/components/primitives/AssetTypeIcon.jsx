/**
 * AssetTypeIcon — shared visual identity for every place the UI renders an asset.
 *
 * Used in Discovery result rows, Entity hero, Lineage nodes, and Governance
 * asset references. Keeps asset-type identity consistent across the product —
 * one look, one color palette, one recall.
 *
 * Pass either `asset` (any record where displayObjectType() resolves) or the
 * pre-resolved `type` string.
 */

import { displayObjectType } from "../../lib/assetPresentation";

/**
 * Each profile pairs a glyph with a single --ax-* accent token. On the dark
 * theme the chip is a low-alpha tint of that accent (color-mix → transparent,
 * matching the color-mix tint pattern used across the surface stylesheets) with
 * the glyph drawn in the full accent. This keeps per-type hue distinction while
 * honoring the repo rule: no hard-coded hex, no light surfaces. `accent` is a
 * CSS custom-property reference so the tint and glyph stay in lockstep.
 */
const TYPE_PROFILES = {
  "Delta Table": { accent: "var(--ax-bright-blue)", glyph: "disc" },
  "Streaming Table": { accent: "var(--ax-teal)", glyph: "waves" },
  "Materialized View": { accent: "var(--ax-success)", glyph: "layers" },
  "View": { accent: "var(--ax-gray)", glyph: "eye" },
  "External Table": { accent: "var(--ax-warning)", glyph: "cloud" },
  "Managed Table": { accent: "var(--ax-bright-blue)", glyph: "disc" },
  "Pipeline": { accent: "var(--ax-purple)", glyph: "branch" },
  "Notebook": { accent: "var(--ax-warning)", glyph: "notebook" },
  "Dashboard": { accent: "var(--ax-danger)", glyph: "chart" },
  "Volume": { accent: "var(--ax-light-blue)", glyph: "folder" },
  "Model": { accent: "var(--ax-danger)", glyph: "brain" },
  "Function": { accent: "var(--ax-purple)", glyph: "code" },
  __fallback: { accent: "var(--ax-gray)", glyph: "database" },
};

// Low-alpha tint of the profile accent, for the chip background on the dark
// theme. Shared helper so the ratio is defined once.
const tint = (accent) => `color-mix(in srgb, ${accent} 16%, transparent)`;

const GLYPH_PATHS = {
  // All 24x24, stroke-only.
  disc: (
    <>
      <ellipse cx="12" cy="6" rx="8" ry="2.5" />
      <path d="M4 6v5c0 1.4 3.6 2.5 8 2.5s8-1.1 8-2.5V6" />
      <path d="M4 11v5c0 1.4 3.6 2.5 8 2.5s8-1.1 8-2.5v-5" />
    </>
  ),
  waves: (
    <>
      <path d="M3 7c2-2 4-2 6 0s4 2 6 0 4-2 6 0" />
      <path d="M3 13c2-2 4-2 6 0s4 2 6 0 4-2 6 0" />
      <path d="M3 19c2-2 4-2 6 0s4 2 6 0 4-2 6 0" />
    </>
  ),
  layers: (
    <>
      <polygon points="12,3 3,8 12,13 21,8" />
      <polyline points="3,13 12,18 21,13" />
      <polyline points="3,18 12,23 21,18" />
    </>
  ),
  eye: (
    <>
      <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z" />
      <circle cx="12" cy="12" r="3" />
    </>
  ),
  cloud: (
    <path d="M17 18a4 4 0 0 0 0-8 6 6 0 0 0-11.5 1.5A4.5 4.5 0 0 0 6 18h11z" />
  ),
  branch: (
    <>
      <circle cx="6" cy="5" r="2" />
      <circle cx="6" cy="19" r="2" />
      <circle cx="18" cy="12" r="2" />
      <path d="M6 7v10" />
      <path d="M8 19c6 0 8-3 8-7" />
    </>
  ),
  notebook: (
    <>
      <rect x="5" y="4" width="14" height="16" rx="1.5" />
      <path d="M9 4v16" />
      <path d="M12 8h4M12 12h4M12 16h3" />
    </>
  ),
  chart: (
    <>
      <rect x="3" y="3" width="18" height="18" rx="2" />
      <path d="M7 16v-4M11 16V9M15 16v-6M19 16v-3" />
    </>
  ),
  folder: (
    <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7z" />
  ),
  brain: (
    <>
      <path d="M8 3a3 3 0 0 0-3 3v1a3 3 0 0 0-2 3v1a3 3 0 0 0 2 3v1a3 3 0 0 0 3 3" />
      <path d="M16 3a3 3 0 0 1 3 3v1a3 3 0 0 1 2 3v1a3 3 0 0 1-2 3v1a3 3 0 0 1-3 3" />
      <path d="M12 3v18" />
    </>
  ),
  code: (
    <>
      <polyline points="8,6 3,12 8,18" />
      <polyline points="16,6 21,12 16,18" />
      <path d="M14 4l-4 16" />
    </>
  ),
  database: (
    <>
      <ellipse cx="12" cy="5" rx="8" ry="2.5" />
      <path d="M4 5v7c0 1.4 3.6 2.5 8 2.5s8-1.1 8-2.5V5" />
      <path d="M4 12v7c0 1.4 3.6 2.5 8 2.5s8-1.1 8-2.5v-7" />
    </>
  ),
};

const SIZE_TO_PX = { sm: 16, md: 20, lg: 28, xl: 40 };

export function AssetTypeIcon({
  asset = null,
  type = "",
  size = "md",
  className = "",
  title = "",
}) {
  const resolved = type || displayObjectType(asset) || "";
  const profile = TYPE_PROFILES[resolved] || TYPE_PROFILES.__fallback;
  const px = SIZE_TO_PX[size] || SIZE_TO_PX.md;
  const glyphPx = Math.round(px * 0.6);
  const strokeWidth = px >= 40 ? 1.6 : px >= 28 ? 1.7 : 1.8;
  const label = title || resolved || "Asset";

  return (
    <span
      aria-label={label}
      className={`gh-asset-type-icon ${className}`.trim()}
      role="img"
      style={{
        alignItems: "center",
        background: tint(profile.accent),
        borderRadius: Math.round(px * 0.25),
        color: profile.accent,
        display: "inline-flex",
        flex: "0 0 auto",
        height: `${px}px`,
        justifyContent: "center",
        width: `${px}px`,
      }}
      title={label}
    >
      <svg
        aria-hidden="true"
        fill="none"
        height={glyphPx}
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={strokeWidth}
        viewBox="0 0 24 24"
        width={glyphPx}
      >
        {GLYPH_PATHS[profile.glyph] || GLYPH_PATHS.database}
      </svg>
    </span>
  );
}
