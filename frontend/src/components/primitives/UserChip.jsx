import { useEffect, useMemo, useRef, useState } from "react";
import { readProfileAvatar, writeProfileAvatar } from "../../lib/prefs";
import { OwnerAvatar } from "./OwnerAvatar";

const BellIcon = () => (
  <svg aria-hidden="true" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <path d="M6 8a6 6 0 0 1 12 0c0 4 2 5 2 7H4c0-2 2-3 2-7Z" />
    <path d="M10 20a2 2 0 0 0 4 0" />
  </svg>
);

const ChevronDownIcon = () => (
  <svg aria-hidden="true" viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="m6 9 6 6 6-6" />
  </svg>
);

function prettyName(email = "") {
  const local = String(email).split("@")[0] || "";
  if (!local) return "Workspace user";
  return local
    .split(/[\s._+-]+/)
    .filter(Boolean)
    .map((part) => (part[0] ? part[0].toUpperCase() + part.slice(1) : part))
    .join(" ");
}

function prettyRole(role = "") {
  const value = String(role || "").trim();
  if (!value) return "Workspace user";
  // Preserve role casing but add a gentle tagline
  return value;
}

export const MAX_AVATAR_IMAGE_BYTES = 512 * 1024;

const ALLOWED_AVATAR_EXTENSIONS = new Set(["png", "jpg", "jpeg", "gif", "webp"]);
const SVG_MIME_TYPE = "image/svg+xml";

function fileExtension(name = "") {
  const normalized = String(name || "").trim().toLowerCase();
  const dotIndex = normalized.lastIndexOf(".");
  return dotIndex >= 0 ? normalized.slice(dotIndex + 1) : "";
}

function hasImageHint(file) {
  const type = String(file?.type || "").trim().toLowerCase();
  if (type.startsWith("image/")) return true;
  return ALLOWED_AVATAR_EXTENSIONS.has(fileExtension(file?.name));
}

function isSvgFile(file) {
  const type = String(file?.type || "").trim().toLowerCase();
  return type === SVG_MIME_TYPE || fileExtension(file?.name) === "svg";
}

function detectAvatarMime(bytes) {
  if (!bytes?.length) return "";
  if (
    bytes[0] === 0x89 &&
    bytes[1] === 0x50 &&
    bytes[2] === 0x4e &&
    bytes[3] === 0x47 &&
    bytes[4] === 0x0d &&
    bytes[5] === 0x0a &&
    bytes[6] === 0x1a &&
    bytes[7] === 0x0a
  ) {
    return "image/png";
  }
  if (bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff) return "image/jpeg";
  if (
    bytes[0] === 0x47 &&
    bytes[1] === 0x49 &&
    bytes[2] === 0x46 &&
    bytes[3] === 0x38 &&
    (bytes[4] === 0x37 || bytes[4] === 0x39) &&
    bytes[5] === 0x61
  ) {
    return "image/gif";
  }
  if (
    bytes[0] === 0x52 &&
    bytes[1] === 0x49 &&
    bytes[2] === 0x46 &&
    bytes[3] === 0x46 &&
    bytes[8] === 0x57 &&
    bytes[9] === 0x45 &&
    bytes[10] === 0x42 &&
    bytes[11] === 0x50
  ) {
    return "image/webp";
  }
  return "";
}

function looksLikeSvgPayload(bytes) {
  if (!bytes?.length) return false;
  const sample = String.fromCharCode(...bytes.slice(0, 256)).trimStart().toLowerCase();
  return sample.startsWith("<svg") || sample.startsWith("<?xml") || sample.includes("<svg");
}

function base64FromBytes(bytes) {
  let binary = "";
  for (let index = 0; index < bytes.length; index += 1) {
    binary += String.fromCharCode(bytes[index]);
  }
  return btoa(binary);
}

function isAllowedAvatarDataUrl(value) {
  const text = String(value || "").trim();
  if (!text || text.length > Math.ceil(MAX_AVATAR_IMAGE_BYTES * 1.4) + 64) return false;
  return /^data:image\/(?:png|jpeg|gif|webp);base64,/i.test(text);
}

function readFileBytes(file) {
  if (typeof file.arrayBuffer === "function") {
    return file.arrayBuffer().then((buffer) => new Uint8Array(buffer));
  }
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result;
      if (!(result instanceof ArrayBuffer)) {
        reject(new Error("Unable to read avatar file."));
        return;
      }
      resolve(new Uint8Array(result));
    };
    reader.onerror = () => reject(reader.error || new Error("Unable to read avatar file."));
    reader.readAsArrayBuffer(file);
  });
}

export async function readAvatarFileDataUrl(file) {
  if (!file) return { accepted: false, reason: "Choose an image file.", dataUrl: "" };
  if (isSvgFile(file)) {
    return { accepted: false, reason: "SVG avatars are not supported.", dataUrl: "" };
  }
  if (!hasImageHint(file)) {
    return { accepted: false, reason: "Choose a PNG, JPEG, GIF, or WebP image.", dataUrl: "" };
  }
  if (Number(file.size || 0) > MAX_AVATAR_IMAGE_BYTES) {
    return { accepted: false, reason: "Avatar image is too large.", dataUrl: "" };
  }

  const bytes = await readFileBytes(file);
  if (looksLikeSvgPayload(bytes)) {
    return { accepted: false, reason: "SVG avatars are not supported.", dataUrl: "" };
  }
  const detectedMime = detectAvatarMime(bytes);
  if (!detectedMime) {
    return { accepted: false, reason: "Choose a PNG, JPEG, GIF, or WebP image.", dataUrl: "" };
  }
  return {
    accepted: true,
    reason: "",
    dataUrl: `data:${detectedMime};base64,${base64FromBytes(bytes)}`,
  };
}

export function UserChip({
  userEmail = "",
  userName = "",
  role = "",
  roleProvisional = false,
  inboxUnreadCount = 0,
  inboxOpen = false,
  onToggleInbox = undefined,
  showInbox = false,
  onSignOut = undefined,
  onOpenSettings = undefined,
  onOpenCapabilities = undefined,
  variant = "topbar",
}) {
  const displayName = prettyName(userName || userEmail);
  const displayRole = prettyRole(role);
  const avatarLabel = userName || displayName || userEmail;
  // Storage goes through lib/prefs.js (the sanctioned storage module); the
  // identity string keys the stored avatar per user.
  const avatarIdentity = useMemo(
    () => String(userEmail || userName || displayName || "workspace-user").trim().toLowerCase(),
    [displayName, userEmail, userName],
  );
  const [menuOpen, setMenuOpen] = useState(false);
  const [avatarUrl, setAvatarUrl] = useState("");
  const menuRef = useRef(null);
  const avatarInputRef = useRef(null);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const storedAvatar = readProfileAvatar(avatarIdentity);
    setAvatarUrl(isAllowedAvatarDataUrl(storedAvatar) ? storedAvatar : "");
  }, [avatarIdentity]);

  useEffect(() => {
    if (!menuOpen) return undefined;
    const onClick = (event) => {
      if (!menuRef.current?.contains(event.target)) setMenuOpen(false);
    };
    const onKey = (event) => {
      if (event.key === "Escape") setMenuOpen(false);
    };
    document.addEventListener("pointerdown", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [menuOpen]);

  const handleAvatarFile = async (event) => {
    const input = event.target;
    const file = event.target.files?.[0];
    if (!file) {
      input.value = "";
      return;
    }
    try {
      const result = await readAvatarFileDataUrl(file);
      if (!result.accepted || !result.dataUrl) return;
      setAvatarUrl(result.dataUrl);
      // Best-effort persistence via lib/prefs.js; the in-memory preview
      // survives even when browser storage is unavailable.
      writeProfileAvatar(avatarIdentity, result.dataUrl);
    } catch {
      // Rejected or unreadable image payloads should not change stored state.
    } finally {
      input.value = "";
    }
  };

  return (
    <div className={`ax-user-chip is-${variant}`.trim()} ref={menuRef}>
      {showInbox ? (
        <button
          aria-label={
            inboxUnreadCount > 0
              ? `Notifications (${inboxUnreadCount} unread)`
              : "Notifications"
          }
          aria-pressed={inboxOpen}
          className="ax-user-chip-bell"
          onClick={onToggleInbox || (() => {})}
          type="button"
        >
          <BellIcon />
          {/* Unread dot only when there's a real unread count. Previously the
              dot rendered always "to match the mockup" — that read as a fake
              live-signal, which is exactly the kind of cosmetic-for-cosmetic's-
              sake copy the Tranche C cleanup removes elsewhere. */}
          {inboxUnreadCount > 0 ? (
            <span aria-hidden="true" className="ax-user-chip-bell-dot">
              {inboxUnreadCount > 9 ? "9+" : inboxUnreadCount}
            </span>
          ) : null}
        </button>
      ) : null}
      {/* Avatar BEFORE the name — matches the mockup silhouette. The wrapping
          button opens the identity menu so the chip is keyboard-reachable. */}
      <button
        aria-expanded={menuOpen}
        aria-haspopup="menu"
        aria-label={`Open profile menu for ${displayName}${roleProvisional ? ". Role verification pending." : ""}`}
        className="ax-user-chip-trigger"
        onClick={() => setMenuOpen((current) => !current)}
        type="button"
      >
        <OwnerAvatar owner={avatarLabel} size={42} className="ax-user-chip-avatar" imageUrl={avatarUrl} />
        {variant === "sidebar" ? (
          <span className="ax-user-chip-sidebar-copy">
            <strong>{displayName}</strong>
            <em>{displayRole}</em>
          </span>
        ) : null}
        {/* Chevron signals this is a dropdown trigger — operator 2026-04-19
            flagged the missing disclosure cue next to the name. */}
        <span
          className={`ax-user-chip-caret ${menuOpen ? "is-open" : ""}`.trim()}
          aria-hidden="true"
        >
          <ChevronDownIcon />
        </span>
      </button>
      <input
        accept="image/png,image/jpeg,image/gif,image/webp"
        aria-label="Upload profile avatar"
        className="ax-user-chip-avatar-input"
        onChange={handleAvatarFile}
        ref={avatarInputRef}
        type="file"
      />
      {menuOpen ? (
        <div className="ax-user-chip-menu" role="menu">
          <div className="ax-user-chip-menu-header">
            <div className="ax-user-chip-menu-name">{displayName}</div>
            <div className="ax-user-chip-menu-email">{userEmail || "Workspace user"}</div>
            {roleProvisional ? (
              <div className="ax-user-chip-menu-email">Role verification pending.</div>
            ) : null}
          </div>
          {onOpenSettings ? (
            <button
              className="ax-user-chip-menu-item"
              onClick={() => { setMenuOpen(false); onOpenSettings(); }}
              role="menuitem"
              type="button"
            >
              Settings &amp; diagnostics
            </button>
          ) : null}
          <button
            className="ax-user-chip-menu-item"
            onClick={() => {
              setMenuOpen(false);
              avatarInputRef.current?.click();
            }}
            role="menuitem"
            type="button"
            title="Stored only in this browser. This does not update a Databricks profile."
          >
            Upload local avatar
          </button>
          {onOpenCapabilities ? (
            <button
              className="ax-user-chip-menu-item"
              onClick={() => { setMenuOpen(false); onOpenCapabilities(); }}
              role="menuitem"
              type="button"
            >
              Capability dashboard
            </button>
          ) : null}
          {onSignOut ? (
            <button
              className="ax-user-chip-menu-item"
              onClick={() => { setMenuOpen(false); onSignOut(); }}
              role="menuitem"
              type="button"
            >
              Sign out
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

export default UserChip;
