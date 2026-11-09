// Workspace-roster hook — the real account principals used to autofill
// owner/steward pickers. Backed by GET /api/identity/workspace-roster, which
// the backend derives from Unity Catalog owners/grants (+ SCIM when the scope
// is present). The endpoint is steward/admin-gated; fetchWorkspaceRoster
// resolves an unavailable roster instead of throwing, so a non-approver simply
// gets free text with no suggestions rather than a broken form.
import { useMemo } from "react";
import { fetchWorkspaceRoster } from "../lib/api";
import { useAxiomQuery } from "./useAxiomQuery";

export function useWorkspaceRoster(options = {}) {
  const enabled = options.enabled !== false;
  const { query } = useAxiomQuery({
    key: ["axiom", "workspace-roster"],
    fetch: (signal) => fetchWorkspaceRoster({ signal }),
    enabled,
    // The account roster changes rarely; cache it generously so opening a
    // form doesn't re-hit the SCIM/UC derivation each time.
    staleTime: 5 * 60_000,
    retry: false,
  });

  const data = query.data || null;
  const emails = useMemo(() => {
    const members = Array.isArray(data?.members) ? data.members : [];
    return members
      .filter((m) => m.principalType !== "service_principal")
      .map((m) => m.principal)
      .filter(Boolean);
  }, [data]);

  return {
    available: Boolean(data?.available) && emails.length > 0,
    emails,
    source: data?.source || "",
    loading: enabled && query.isPending,
  };
}

export default useWorkspaceRoster;
