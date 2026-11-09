// Wave C5 — quality findings for the Evidence surface's quality tab.
//
// GET /api/quality/findings (landed Wave A4) is visibility-scoped by asset —
// NOT steward-gated like audit evidence — so this hook carries no role gate.
// Rows carry stable QF-<hex8> findingIds and joined run metadata; the payload
// is a flat envelope whose state/reason/meta the shared useAxiomQuery
// contract resolves (lib/envelope.js flat-payload fallbacks).
import { fetchQualityFindings } from "../lib/api";
import { useAxiomQuery } from "./useAxiomQuery";

// Must match the backend cap (limit is clamped to 500 server-side).
export const QUALITY_FINDINGS_DEFAULT_LIMIT = 500;

function textFilter(value) {
  return String(value || "").trim();
}

/**
 * @param {{ asset?: string, severity?: string, outcome?: string, since?: string, until?: string, limit?: number }} [filters]
 * @param {{ enabled?: boolean }} [options]
 */
export function useQualityFindings(filters = {}, options = {}) {
  const asset = textFilter(filters.asset);
  // Severity accepts either the raw stored form ("critical") or the canonical
  // bucket ("high") — the backend resolves both, so risk-drill deep links
  // (?tab=quality&severity=high) pass through untranslated.
  const severity = textFilter(filters.severity);
  const outcome = textFilter(filters.outcome).toLowerCase();
  const since = textFilter(filters.since);
  const until = textFilter(filters.until);
  const limit = Number.isFinite(Number(filters.limit))
    ? Math.max(1, Math.trunc(Number(filters.limit)))
    : QUALITY_FINDINGS_DEFAULT_LIMIT;
  const enabled = options.enabled !== false;
  return useAxiomQuery({
    key: ["axiom", "quality-findings", asset, severity, outcome, since, until, limit],
    enabled,
    fetch: (signal) => fetchQualityFindings({ asset, severity, outcome, since, until, limit }, { signal }),
    // Keep the previous filter window's rows on screen while the next loads
    // (same stale-while-revalidate feel as the audit evidence feed).
    placeholderData: (previousData) => previousData,
    retry: false,
    staleTime: 60_000,
  });
}

export default useQualityFindings;
