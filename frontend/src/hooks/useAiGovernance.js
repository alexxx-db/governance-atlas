// AI governance data hooks (docs/ai_extension/DESIGN.md 10).
//
// Every read goes through useAtlasQuery, so the shared envelope contract
// decides loading / degraded / unavailable from the backend's meta. The
// backend builds each view from the latest *succeeded* reconciliation run
// and reports a failed later run or an unavailable source as `degraded`
// with warnings; these hooks never invent zeros for missing data.
import {
  confirmAiFindingMatch,
  fetchAiAsset,
  fetchAiFindings,
  fetchAiIntake,
  fetchAiInventory,
  fetchAiSummary,
  importAiIntake,
  patchAiFinding,
} from "../lib/api";
import { useAtlasMutation, useAtlasQuery } from "./useAtlasQuery";

export const AI_KEY = ["atlas", "ai"];

const READ_OPTIONS = {
  placeholderData: (previousData) => previousData,
  retry: false,
  staleTime: 60_000,
};

export function useAiSummary(options = {}) {
  return useAtlasQuery({
    key: [...AI_KEY, "summary"],
    enabled: options.enabled !== false,
    fetch: (signal) => fetchAiSummary({ signal }),
    ...READ_OPTIONS,
  });
}

/** @param {{kind?: string, provider?: string, platform?: string, tier?: string, state?: string, hasOpenFindings?: boolean|null, q?: string, sort?: string, limit?: number, offset?: number}} [filters] */
export function useAiInventory(filters = {}, options = {}) {
  const normalized = {
    kind: filters.kind || "",
    provider: filters.provider || "",
    platform: filters.platform || "",
    tier: filters.tier || "",
    state: filters.state || "",
    hasOpenFindings: typeof filters.hasOpenFindings === "boolean" ? filters.hasOpenFindings : "",
    q: filters.q || "",
    sort: filters.sort || "findings",
    limit: filters.limit || 200,
    offset: filters.offset || 0,
  };
  return useAtlasQuery({
    key: [...AI_KEY, "inventory", normalized],
    enabled: options.enabled !== false,
    fetch: (signal) => fetchAiInventory(normalized, { signal }),
    ...READ_OPTIONS,
  });
}

export function useAiAsset(entityId, options = {}) {
  const id = String(entityId || "").trim();
  return useAtlasQuery({
    key: [...AI_KEY, "asset", id],
    enabled: Boolean(id) && options.enabled !== false,
    fetch: (signal) => fetchAiAsset(id, { signal }),
    ...READ_OPTIONS,
    // No placeholder: navigating between assets must not show the previous asset's data.
    placeholderData: undefined,
  });
}

/** Steward-only on the backend; callers pass enabled=false for readers. */
export function useAiFindings(filters = {}, options = {}) {
  const normalized = {
    state: filters.state || "open,acknowledged",
    findingType: filters.findingType || "",
    severity: filters.severity || "",
    limit: filters.limit || 200,
    offset: filters.offset || 0,
  };
  return useAtlasQuery({
    key: [...AI_KEY, "findings", normalized],
    enabled: options.enabled !== false,
    fetch: (signal) => fetchAiFindings(normalized, { signal }),
    ...READ_OPTIONS,
  });
}

export function useAiIntake(options = {}) {
  return useAtlasQuery({
    key: [...AI_KEY, "intake"],
    enabled: options.enabled !== false,
    fetch: (signal) => fetchAiIntake({ signal }),
    ...READ_OPTIONS,
  });
}

/**
 * Steward finding actions. variables: {findingId, action, note?, reason?,
 * assigneeEmail?} or {findingId, action: "confirm-match", intakeId, note?}.
 * Every AI view re-syncs from the server afterwards (no optimistic guess:
 * the backend audits before writing and may reject).
 */
export function useAiFindingAction() {
  return useAtlasMutation({
    mutate: ({ findingId, action, intakeId = "", note = "", reason = "", assigneeEmail = "" }) =>
      action === "confirm-match"
        ? confirmAiFindingMatch(findingId, { intakeId, note })
        : patchAiFinding(findingId, { action, note, reason, assigneeEmail }),
    invalidates: [AI_KEY],
  });
}

/** variables: {csvText, mode: "dry_run" | "commit"} */
export function useAiIntakeImport() {
  return useAtlasMutation({
    mutate: ({ csvText, mode }) => importAiIntake(csvText, mode),
    invalidates: [AI_KEY],
  });
}
