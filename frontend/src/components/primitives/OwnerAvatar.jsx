/**
 * OwnerAvatar — tiny circular chip showing the owner initials with a
 * deterministic color per email. Matches OpenMetadata's owner glyph
 * density so a row of owners reads as recognizable humans rather than
 * a blob of text.
 */

// Deterministic per-owner hue, chosen from --ax-* accent tokens. The circle is
// a low-alpha tint of the accent (color-mix → transparent) with the initials in
// the full accent — distinct color per owner, but on the dark theme rather than
// the old light pastels. No hard-coded hex, no light surfaces (repo rule).
const ACCENTS = [
  "var(--ax-bright-blue)",
  "var(--ax-teal)",
  "var(--ax-success)",
  "var(--ax-warning)",
  "var(--ax-purple)",
  "var(--ax-danger)",
  "var(--ax-light-blue)",
  "var(--ax-gray)",
];

// Slightly stronger tint than the type icons: the circle carries text, so it
// needs a touch more presence to read against the dark surface behind it.
const tint = (accent) => `color-mix(in srgb, ${accent} 18%, transparent)`;

function hashString(s) {
  let h = 0;
  const str = String(s || "");
  for (let i = 0; i < str.length; i += 1) {
    h = (h << 5) - h + str.charCodeAt(i);
    h |= 0;
  }
  return Math.abs(h);
}

function ownerInitials(label) {
  const raw = String(label || "").trim();
  if (!raw) return "—";
  const local = raw.includes("@") ? raw.split("@")[0] : raw;
  const parts = local.split(/[\s._+-]+/).filter(Boolean);
  if (parts.length >= 2) return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
  if (parts.length === 1) return parts[0][0].toUpperCase();
  return raw[0]?.toUpperCase() || "—";
}

export function OwnerAvatar({ owner = "", size = 22, className = "", imageUrl = "" }) {
  const accent = ACCENTS[hashString(owner) % ACCENTS.length];
  const initials = ownerInitials(owner);
  const normalizedImageUrl = String(imageUrl || "").trim();
  return (
    <span
      aria-label={owner || "No owner"}
      className={`ax-owner-avatar ${className}`.trim()}
      role="img"
      style={{
        alignItems: "center",
        background: tint(accent),
        borderRadius: "50%",
        color: accent,
        display: "inline-flex",
        flex: "0 0 auto",
        fontSize: Math.round(size * 0.38),
        fontWeight: 700,
        height: `${size}px`,
        justifyContent: "center",
        letterSpacing: "0.01em",
        width: `${size}px`,
      }}
      title={owner || "No owner"}
    >
      {normalizedImageUrl ? (
        <img alt="" src={normalizedImageUrl} style={{ width: "100%", height: "100%", borderRadius: "50%", objectFit: "cover" }} />
      ) : initials}
    </span>
  );
}

export function OwnerAvatarStack({ owners = [], limit = 3, size = 22 }) {
  if (!owners.length) return null;
  const visible = owners.slice(0, limit);
  const extra = owners.length - visible.length;
  return (
    <span className="ax-owner-avatar-stack" aria-label={owners.join(", ")}>
      {visible.map((o, i) => (
        <OwnerAvatar
          key={`${o}-${i}`}
          owner={o}
          size={size}
          className={i > 0 ? "ax-owner-avatar-overlap" : ""}
        />
      ))}
      {extra > 0 ? (
        <span
          aria-hidden="true"
          className="ax-owner-avatar ax-owner-avatar-overflow"
          style={{ width: `${size}px`, height: `${size}px`, fontSize: Math.round(size * 0.38) }}
          title={`+${extra} more`}
        >
          +{extra}
        </span>
      ) : null}
    </span>
  );
}
