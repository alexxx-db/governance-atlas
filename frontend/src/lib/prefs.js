/*
 * lib/prefs.js — THE sanctioned browser-storage helper (Wave C1;
 * FRONTEND_BLUEPRINT §8.4, eslint guardrail scope 3).
 *
 * Preference-state ONLY lives here: density, layout, favorites, recents,
 * saved searches, and short-lived session caches. Anything worth restoring
 * on refresh/share belongs in the URL (nav/useSurfaceParams) — never here.
 *
 * This is the only module in src/ allowed to touch localStorage /
 * sessionStorage (eslint carves it out explicitly). Every accessor:
 *   - degrades to its fallback when storage is missing/blocked (the vitest
 *     environment ships no localStorage; private-mode browsers throw),
 *   - migrates the legacy pre-C1 keys forward on first read (backward-compatible
 *     reads: old browsers' data survives the C1 rename),
 *   - never throws.
 */

const LOCAL_PREFIX = "ax.prefs.";
const SESSION_PREFIX = "ga.session.";

/**
 * Registered preferences. `legacyKey` is the pre-C1 raw localStorage key the
 * value migrates from; `normalize` makes any stored/legacy value safe.
 */
const PREFS = {
  favoriteAssets: {
    legacyKey: "gh-favorite-assets",
    fallback: [],
    normalize: (value) =>
      Array.isArray(value) ? value.filter((item) => typeof item === "string" && item) : [],
  },
  recentAssets: {
    legacyKey: "gh-recent-assets",
    fallback: [],
    normalize: (value) =>
      Array.isArray(value)
        ? value.filter((item) => typeof item === "string" && item).slice(0, 20)
        : [],
  },
  // Last Asset 360 record the user opened. Powers the permanent rail entry's
  // no-context target (owner directive: Asset 360 is always visible — with no
  // route/peek context the entry returns you to where you last were).
  lastAssetFqn: {
    legacyKey: null,
    fallback: "",
    normalize: (value) => (typeof value === "string" ? value : ""),
  },
  savedSearches: {
    legacyKey: "gh-saved-searches",
    fallback: [],
    normalize: (value) =>
      Array.isArray(value)
        ? value
            .filter((entry) => entry && typeof entry === "object" && entry.name)
            .slice(0, 20)
        : [],
  },
  discoveryDensity: {
    legacyKey: "gh-discovery-density",
    fallback: "comfortable",
    // Legacy vocabulary was normal|compact|spacious; the system DataTable
    // knows comfortable|compact, so everything non-compact maps forward.
    normalize: (value) => (value === "compact" ? "compact" : "comfortable"),
  },
  discoveryLayout: {
    legacyKey: null,
    fallback: "list",
    normalize: (value) => (value === "grid" ? "grid" : "list"),
  },
  // Lineage wave: FQNs of lineage graphs the user actually opened, most
  // recent first. Powers the picker's "Recent lineage journeys" strip —
  // preference-state only (the canonical journey state is the URL).
  recentLineage: {
    legacyKey: null,
    fallback: [],
    normalize: (value) =>
      Array.isArray(value)
        ? value.filter((item) => typeof item === "string" && item).slice(0, 12)
        : [],
  },
  // Axiom AI dock layout: user-chosen size + maximize state, restored on
  // reopen/refresh. Bounds are enforced by the dock (min 320x360); the
  // normalizer only guards types so a corrupt value never breaks the dock.
  aiDockLayout: {
    legacyKey: null,
    fallback: { width: 0, height: 0, maximized: false },
    normalize: (value) => {
      const source = value && typeof value === "object" ? value : {};
      const num = (input) => {
        const parsed = Number(input);
        return Number.isFinite(parsed) && parsed > 0 ? Math.round(parsed) : 0;
      };
      return {
        width: num(source.width),
        height: num(source.height),
        maximized: Boolean(source.maximized),
      };
    },
  },
};

function storageFor(kind) {
  try {
    const store = kind === "session" ? window.sessionStorage : window.localStorage;
    // Some environments expose the property but throw on use.
    return store || null;
  } catch {
    return null;
  }
}

function readRaw(store, key) {
  try {
    return store.getItem(key);
  } catch {
    return null;
  }
}

function writeRaw(store, key, serialized) {
  try {
    store.setItem(key, serialized);
  } catch {
    /* quota / privacy mode — preferences are best-effort */
  }
}

function parseJson(raw) {
  if (raw == null) return undefined;
  try {
    return JSON.parse(raw);
  } catch {
    // Legacy density was stored as a bare string, not JSON.
    return raw;
  }
}

/** Read a registered preference (with one-time legacy-key migration). */
export function readPref(name, fallbackOverride) {
  const spec = PREFS[name];
  if (!spec) return fallbackOverride;
  const fallback = fallbackOverride === undefined ? spec.fallback : fallbackOverride;
  const store = storageFor("local");
  if (!store) return fallback;

  const raw = readRaw(store, `${LOCAL_PREFIX}${name}`);
  if (raw != null) {
    const parsed = parseJson(raw);
    return parsed === undefined ? fallback : spec.normalize(parsed);
  }

  if (spec.legacyKey) {
    const legacyRaw = readRaw(store, spec.legacyKey);
    if (legacyRaw != null) {
      const value = spec.normalize(parseJson(legacyRaw));
      // Migrate forward so the legacy key stops being load-bearing.
      writeRaw(store, `${LOCAL_PREFIX}${name}`, JSON.stringify(value));
      return value;
    }
  }
  return fallback;
}

/** Write a registered preference. Returns the normalized stored value. */
export function writePref(name, value) {
  const spec = PREFS[name];
  if (!spec) return value;
  const normalized = spec.normalize(value);
  const store = storageFor("local");
  if (store) writeRaw(store, `${LOCAL_PREFIX}${name}`, JSON.stringify(normalized));
  return normalized;
}

/* ------------------------------------------------------------------ */
/* Domain helpers (the shapes surfaces actually use)                    */
/* ------------------------------------------------------------------ */

export function readFavoriteAssets() {
  return readPref("favoriteAssets");
}

/** Toggle one FQN; returns the next favorites array. */
export function toggleFavoriteAsset(fqn) {
  const current = readFavoriteAssets();
  const next = current.includes(fqn)
    ? current.filter((item) => item !== fqn)
    : [...current, fqn];
  return writePref("favoriteAssets", next);
}

export function readRecentAssets() {
  return readPref("recentAssets");
}

/** Most-recent-first, deduped, capped at 20. Returns the next list. */
export function pushRecentAsset(fqn) {
  if (!fqn) return readRecentAssets();
  const current = readRecentAssets();
  return writePref("recentAssets", [fqn, ...current.filter((item) => item !== fqn)]);
}

export function readRecentLineage() {
  return readPref("recentLineage");
}

/** Most-recent-first, deduped, capped by the pref normalizer. */
export function pushRecentLineage(fqn) {
  if (!fqn) return readRecentLineage();
  const current = readRecentLineage();
  return writePref("recentLineage", [fqn, ...current.filter((item) => item !== fqn)]);
}

/** The FQN of the most recently opened Asset 360 record ("" when none). */
export function readLastAsset() {
  return readPref("lastAssetFqn");
}

/** Remember the last opened Asset 360 record; returns the normalized value. */
export function writeLastAsset(fqn) {
  return writePref("lastAssetFqn", String(fqn || ""));
}

export function readSavedSearches() {
  return readPref("savedSearches");
}

export function writeSavedSearches(entries) {
  return writePref("savedSearches", entries);
}

export function readDiscoveryDensity() {
  return readPref("discoveryDensity");
}

export function writeDiscoveryDensity(value) {
  return writePref("discoveryDensity", value);
}

export function readDiscoveryLayout() {
  return readPref("discoveryLayout");
}

export function writeDiscoveryLayout(value) {
  return writePref("discoveryLayout", value);
}

/*
 * Profile avatar (Wave C8: moved here from UserChip so the storage guardrail
 * holds). The key is per-identity and predates the ax.prefs. namespace —
 * kept verbatim so existing users' avatars survive.
 */
function avatarKey(identity) {
  const id = String(identity || "workspace-user").trim().toLowerCase();
  return `axiom:profile-avatar:${id}`;
}

export function readProfileAvatar(identity) {
  const store = storageFor("local");
  if (!store) return "";
  return readRaw(store, avatarKey(identity)) || "";
}

export function writeProfileAvatar(identity, dataUrl) {
  const store = storageFor("local");
  if (!store) return;
  writeRaw(store, avatarKey(identity), String(dataUrl || ""));
}

/* ------------------------------------------------------------------ */
/* Session caches (tab-scoped, TTL-bounded)                             */
/*                                                                      */
/* Used for ephemeral response caches (e.g. Axiom AI recommendations)   */
/* that should survive an in-tab remount but never a new session.       */
/* ------------------------------------------------------------------ */

export function readSessionCache(key, { ttlMs = null } = {}) {
  const store = storageFor("session");
  if (!store || !key) return null;
  const parsed = parseJson(readRaw(store, `${SESSION_PREFIX}${key}`));
  if (!parsed || typeof parsed !== "object" || !("value" in parsed)) return null;
  if (ttlMs != null && Number.isFinite(ttlMs)) {
    const age = Date.now() - Number(parsed.cachedAt || 0);
    if (!Number.isFinite(age) || age > ttlMs) {
      removeSessionCache(key);
      return null;
    }
  }
  return parsed.value;
}

export function writeSessionCache(key, value) {
  const store = storageFor("session");
  if (!store || !key) return;
  writeRaw(store, `${SESSION_PREFIX}${key}`, JSON.stringify({ cachedAt: Date.now(), value }));
}

export function removeSessionCache(key) {
  const store = storageFor("session");
  if (!store || !key) return;
  try {
    store.removeItem(`${SESSION_PREFIX}${key}`);
  } catch {
    /* best-effort */
  }
}
