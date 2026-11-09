import "./admin.css";
import { useMemo } from "react";
import { PageShell, TabStrip, UnavailableState } from "../../components/system";
import { useAdminControlCenter } from "../../hooks/useAdminControlCenter";
import { isNonAuthoritativeMockEvidence } from "../../lib/nonAuthoritativeEvidence";
import { useSurfaceParams } from "../../nav/useSurfaceParams";
import {
  adminRoleAllowed,
  collectWarnings,
  envelopeData,
  normalizeActivity,
  normalizeIntegrations,
  normalizeJobs,
  normalizePolicies,
  normalizePolicyCards,
  responseStatus,
  text,
} from "./adminPresentation";
import { DiagnosticsTab } from "./tabs/DiagnosticsTab";
import { IntegrationsTab } from "./tabs/IntegrationsTab";
import { OperationsTab } from "./tabs/OperationsTab";
import { PolicyTab } from "./tabs/PolicyTab";
import { RolesTab } from "./tabs/RolesTab";

/*
 * AdminPage — the Control Center surface rebuilt on the system layers
 * (Wave C6, COHESION_BLUEPRINT surface map row "Control Center").
 *
 * Contracts:
 *   - Admin-gated in the profile cluster: non-admin actors get an honest
 *     access card via the SAME predicate the rail uses (adminRoleAllowed —
 *     kept in lockstep with app-shell/Rail.jsx adminRailAllowed), and no
 *     admin endpoint is called for them.
 *   - Mission is runtime operations ONLY — integrations, scheduled jobs,
 *     coverage administration, capability truth. No governance claims;
 *     integration states derive from the same live probes the product uses.
 *   - Absorbs /capabilities as ?tab=diagnostics (nav/routes.js aliases
 *     /capabilities → /admin?tab=diagnostics); the URL is the state, so tab
 *     deep links restore on refresh/back.
 *   - Data loads only through hooks on useAxiomQuery (bounded polls);
 *     non-authoritative diagnostics are rejected wholesale (CLAUDE.md).
 */

const ADMIN_PARAMS_SCHEMA = { tab: { type: "string" } };

const TAB_KEYS = ["operations", "integrations", "policy", "roles", "diagnostics"];

const NON_AUTHORITATIVE_COPY =
  "Non-authoritative Control Center diagnostics were rejected. Live diagnostics are required for populated runtime, integration, and policy rows.";

const EMPTY_DASHBOARD = Object.freeze({});

function isNonAuthoritativeWarning(warning) {
  return isNonAuthoritativeMockEvidence(String(warning || ""));
}

export default function AdminPage({ shell = null, bootstrap = null }) {
  const [params, setParams] = useSurfaceParams(ADMIN_PARAMS_SCHEMA);
  const activeTab = TAB_KEYS.includes(text(params.tab)) ? text(params.tab) : "operations";

  const canReadAdmin = adminRoleAllowed(shell);
  const controlCenter = useAdminControlCenter({ enabled: canReadAdmin });

  const payload = controlCenter.data || null;
  const dashboard = useMemo(() => envelopeData(payload) || {}, [payload]);
  const rawWarnings = useMemo(() => collectWarnings(payload), [payload]);
  const nonAuthoritative = useMemo(
    () =>
      isNonAuthoritativeMockEvidence(
        payload,
        payload?.meta,
        dashboard,
        dashboard.meta,
        rawWarnings,
      ),
    [payload, dashboard, rawWarnings],
  );
  // Rejected payloads render as honest emptiness, never as governed truth.
  const safeDashboard = nonAuthoritative ? EMPTY_DASHBOARD : dashboard;

  const jobs = useMemo(() => normalizeJobs(safeDashboard), [safeDashboard]);
  const integrations = useMemo(() => normalizeIntegrations(safeDashboard), [safeDashboard]);
  const policies = useMemo(() => normalizePolicies(safeDashboard), [safeDashboard]);
  const policyCards = useMemo(() => normalizePolicyCards(safeDashboard), [safeDashboard]);
  const activity = useMemo(() => normalizeActivity(safeDashboard), [safeDashboard]);

  // Hydrating = the backend is still warming its payload or the first fetch
  // is in flight. In that window panels render skeletons — never
  // "Unavailable" rows, which would misreport a warm-up as missing
  // capability (COHESION law #3).
  const hydrating =
    canReadAdmin &&
    !nonAuthoritative &&
    (controlCenter.status === "loading" || controlCenter.status === "hydrating");

  // Genuinely-empty jobs table explains itself with the backend's own
  // jobsReason instead of a generic shrug.
  const jobsEmptyMessage = text(safeDashboard.jobsReason);

  const realWarnings = useMemo(
    () => rawWarnings.filter((warning) => !isNonAuthoritativeWarning(warning)),
    [rawWarnings],
  );

  const forbidden = !canReadAdmin || responseStatus(controlCenter.error) === 403;

  // Page-level status for PageShell's banner slot (the ONLY banner path).
  const pageStatus = useMemo(() => {
    if (forbidden) return null; // the access card carries the message
    if (nonAuthoritative) {
      return {
        status: "degraded",
        warnings: [NON_AUTHORITATIVE_COPY, ...realWarnings],
        refresh: controlCenter.refresh,
      };
    }
    if (controlCenter.status === "error") {
      return {
        status: "error",
        reason: controlCenter.errorMessage || "Runtime diagnostics could not be loaded.",
        refresh: controlCenter.refresh,
      };
    }
    // Payload warnings degrade the page banner so they are never silently
    // swallowed (legacy always surfaced them above the panels).
    if (controlCenter.status === "available" && realWarnings.length) {
      return { status: "degraded", warnings: realWarnings, refresh: controlCenter.refresh };
    }
    return {
      status: controlCenter.status,
      warnings: realWarnings,
      refresh: controlCenter.refresh,
    };
  }, [forbidden, nonAuthoritative, realWarnings, controlCenter.status, controlCenter.errorMessage, controlCenter.refresh]);

  return (
    <PageShell
      className="ax-admin-page"
      eyebrow="Control Center"
      status={pageStatus}
      subtitle="Integrations, scheduled jobs, policy signals, and capability truth reported by the live runtime. Runtime operations only — governance posture lives on the Command Center."
      tabs={
        forbidden ? null : (
          <TabStrip
            ariaLabel="Control Center sections"
            onChange={(key) => setParams({ tab: key === "operations" ? "" : key })}
            tabs={[
              { key: "operations", label: "Operations", controls: "ax-admin-panel-operations" },
              { key: "integrations", label: "Integrations", controls: "ax-admin-panel-integrations" },
              { key: "policy", label: "Policy", controls: "ax-admin-panel-policy" },
              { key: "roles", label: "Roles", controls: "ax-admin-panel-roles" },
              { key: "diagnostics", label: "Diagnostics", controls: "ax-admin-panel-diagnostics" },
            ]}
            value={activeTab}
          />
        )
      }
      title="Axiom runtime operations"
    >
      {forbidden ? (
        // Honest access card — same predicate the rail uses to hide the
        // entry; deep links land here instead of a broken fetch loop.
        <UnavailableState
          className="ax-admin-access-card"
          reason="Ask a workspace admin to grant administration access. Runtime operations expose workspace-wide diagnostics and are limited to platform admins."
          title="Control Center is admin-only"
        />
      ) : activeTab === "integrations" ? (
        <IntegrationsTab hydrating={hydrating} integrations={integrations} />
      ) : activeTab === "policy" ? (
        <PolicyTab hydrating={hydrating} policies={policies} policyCards={policyCards} />
      ) : activeTab === "roles" ? (
        <RolesTab />
      ) : activeTab === "diagnostics" ? (
        <DiagnosticsTab bootstrap={bootstrap} canReadAdmin={canReadAdmin} />
      ) : (
        <OperationsTab
          activity={activity}
          dashboard={safeDashboard}
          hydrating={hydrating}
          jobs={jobs}
          jobsEmptyMessage={jobsEmptyMessage}
        />
      )}
    </PageShell>
  );
}
