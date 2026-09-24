/*
 * app-shell/SurfaceRoutes.jsx — the real react-router <Routes> tree (Wave B1),
 * generated against nav/routes.js ROUTES. The 13-branch if/else surface
 * switch in App.jsx is dead; each canonical route mounts a thin wrapper that
 * maps URL state + ShellContext + legacyAdapters onto exactly the props its
 * LEGACY surface genuinely consumes (dead props dropped — inventory in the
 * Wave B1 report). Alias resolution/redirects happen upstream in AppShell's
 * canonical gate (resolveUrl), so only canonical paths appear here.
 */

import { Suspense, lazy, useMemo } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";

import { normalizeLegacyDiscoverySearch } from "../surfaces/discovery/discoveryParams.js";
import { ShellStateCard } from "./ShellStateCard.jsx";
import { useShellContext } from "./ShellContext.jsx";
import { useLegacyNavAdapters } from "./legacyAdapters.js";

const DiscoveryPage = lazy(() => import("../surfaces/discovery/DiscoveryPage.jsx"));
const AssetHubPage = lazy(() => import("../surfaces/asset/AssetHubPage.jsx"));
const AssetPickerPage = lazy(() => import("../surfaces/asset/AssetPickerPage.jsx"));
const LineagePage = lazy(() => import("../surfaces/lineage/LineagePage.jsx"));
const StewardshipPage = lazy(() => import("../surfaces/stewardship/StewardshipPage.jsx"));
const DataPactPage = lazy(() => import("../surfaces/datapact/DataPactPage.jsx"));
const EvidencePage = lazy(() => import("../surfaces/evidence/EvidencePage.jsx"));
const GlossaryPage = lazy(() => import("../surfaces/glossary/GlossaryPage.jsx"));
const HomePage = lazy(() => import("../surfaces/home/HomePage.jsx"));
const AdminPage = lazy(() => import("../surfaces/admin/AdminPage.jsx"));
const HelpPage = lazy(() => import("../surfaces/help/HelpPage.jsx"));
const AiGovernancePage = lazy(() => import("../surfaces/ai/AiGovernancePage.jsx"));
const AiAssetPage = lazy(() => import("../surfaces/ai/AiAssetPage.jsx"));

function RouteFallback({ eyebrow, message }) {
  return (
    <section className="ga-shell-route-state">
      <ShellStateCard eyebrow={eyebrow} loading message={message} title="Preparing the workspace surface." />
    </section>
  );
}

/* ------------------------------------------------------------------ */
/* Home (Command Center)                                                */
/* ------------------------------------------------------------------ */

function HomeRoute() {
  // Wave-C2 flipped: the rebuilt Command Center is router-self-sufficient —
  // it calls useCommandCenter/useInsightsDashboard itself and renders real
  // anchors through the system refs contract, so no legacy adapter props or
  // bootstrap seed synthesis are threaded. (/insights is an alias of /home
  // in nav/routes.js; AppShell's canonical gate 301s it before this tree.)
  return (
    <Suspense fallback={<RouteFallback eyebrow="Loading home" message="Preparing your governance overview." />}>
      <HomePage />
    </Suspense>
  );
}

/* ------------------------------------------------------------------ */
/* Discovery (Wave C1)                                                  */
/* ------------------------------------------------------------------ */

function DiscoveryRoute() {
  const shellCtx = useShellContext();
  const location = useLocation();

  // Redirect-normalizer: the legacy grammar — ?filters=<JSON>, plural facet
  // shortcuts (?domains=…), ?views=, ?preview= — rewrites once into the flat
  // canonical params (?domain=…&view=…&peek=…) so old deep links keep working
  // while the URL the surface emits is always canonical. The old
  // sessionStorage snapshot and location.state.fresh channel are dead: the
  // URL is the state.
  const normalizedSearch = useMemo(
    () => normalizeLegacyDiscoverySearch(location.search),
    [location.search],
  );
  if (normalizedSearch !== null) {
    return <Navigate replace to={{ pathname: "/discovery", search: normalizedSearch }} />;
  }

  return (
    <Suspense
      fallback={
        <RouteFallback
          eyebrow="Loading discovery"
          message="Restoring the catalog, selected asset preview, and stacked filters."
        />
      }
    >
      {/* The rebuilt surface is router-self-sufficient (useSurfaceParams /
          usePeek); only shell-owned signals — bootstrap seed + boot state +
          Atlas AI availability — are threaded. */}
      <DiscoveryPage
        atlasAiAvailable={shellCtx.atlasAiAvailable}
        atlasAiUnavailableReason={shellCtx.atlasAiUnavailableReason}
        bootMessage={shellCtx.effectiveBootMessage}
        bootState={shellCtx.effectiveBootState}
        bootstrap={shellCtx.bootstrap}
      />
    </Suspense>
  );
}

/* ------------------------------------------------------------------ */
/* Asset 360 hub (/assets/:fqn)                                         */
/* ------------------------------------------------------------------ */

// Legacy ?tab= vocabulary → the rebuilt hub's lowercase tab keys (AssetHubPage
// PARAMS_SCHEMA: overview | columns | quality | access | activity | lineage).
// Old deep links carried EntityWorkspace-era names ("Schema", "queries", …);
// this map lets a one-shot redirect canonicalize them so the URL the hub
// emits is always in the new vocabulary. Unknown values pass through — the
// hub itself falls back to "overview".
const LEGACY_ASSET_TAB_KEYS = {
  overview: "overview",
  schema: "columns",
  columns: "columns",
  preview: "overview",
  sample: "overview",
  lineage: "lineage",
  queries: "activity",
  usage: "activity",
  quality: "quality",
  access: "access",
  activity: "activity",
};

// Bare /assets — the search-first Asset 360 picker (owner directive 1). The
// permanent rail entry lands here when no asset is in context or remembered.
function AssetPickerRoute() {
  return (
    <Suspense
      fallback={<RouteFallback eyebrow="Loading Asset 360" message="Preparing the asset picker." />}
    >
      <AssetPickerPage />
    </Suspense>
  );
}

function AssetHubRoute() {
  const location = useLocation();

  // Redirect-normalizer (same pattern as DiscoveryRoute): rewrite legacy
  // ?tab= spellings once into the canonical lowercase keys. The old
  // workspaceIntent sessionStorage staging is dead — the rebuilt hub reads
  // ?tab= from the URL directly (Wave C8 cleanup).
  const normalizedSearch = useMemo(() => {
    const search = new URLSearchParams(location.search);
    const raw = String(search.get("tab") || "").trim();
    if (!raw) return null;
    const canonical = LEGACY_ASSET_TAB_KEYS[raw.toLowerCase()] || raw;
    if (canonical === raw) return null;
    search.set("tab", canonical);
    return `?${search.toString()}`;
  }, [location.search]);
  if (normalizedSearch !== null) {
    return <Navigate replace to={{ pathname: location.pathname, search: normalizedSearch }} />;
  }

  return (
    <Suspense
      fallback={
        <RouteFallback
          eyebrow="Loading metadata record"
          message="Loading the selected asset record, schema, and lineage context."
        />
      }
    >
      {/* Wave-B2 flipped: the rebuilt hub is router-self-sufficient — it
          reads :fqn via useParams and ?tab=/?col= via useSurfaceParams, so
          no legacy adapter props are threaded. */}
      <AssetHubPage />
    </Suspense>
  );
}

/* ------------------------------------------------------------------ */
/* Stewardship (Wave C3 — absorbed /inbox as ?assignee=me)              */
/* ------------------------------------------------------------------ */

function StewardshipRoute() {
  const shellCtx = useShellContext();

  // Wave-C3 flipped: the rebuilt Stewardship surface is router-self-
  // sufficient — it reads ?assignee/?item/?asset/?lens via useSurfaceParams
  // and loads the ONE queue through useInboxWork (workbench + glossary on
  // the same canonical cache keys as the rail badge and bell popover). The
  // /inbox alias resolves upstream in nav/routes.js to ?assignee=me, so
  // InboxPage has no mount here — the queue IS the inbox. Only shell-owned
  // identity is threaded (for assign-to-me + role-gated triage).
  return (
    <Suspense
      fallback={
        <RouteFallback
          eyebrow="Loading governance"
          message="Preparing the stewardship work queue and request evidence."
        />
      }
    >
      <StewardshipPage
        currentUser={{
          email: shellCtx.shell.userEmail || "",
          name: shellCtx.shell.userName || "",
          role: shellCtx.shell.role || "",
        }}
      />
    </Suspense>
  );
}

/* ------------------------------------------------------------------ */
/* DataPact Control Center                                              */
/* ------------------------------------------------------------------ */

function DataPactRoute() {
  const shellCtx = useShellContext();
  // Router-self-sufficient: the surface reads ?tab/?run/?job via
  // useSurfaceParams and performs its own authoritative OBO detection. Only
  // shell-owned signals ride in: identity (steward gate for triggering runs),
  // the workspace host (for the embedded AI/BI dashboard iframe), and the
  // bootstrap capability snapshot.
  return (
    <Suspense
      fallback={
        <RouteFallback
          eyebrow="Loading DataPact"
          message="Detecting the DataPact control plane and loading validation results."
        />
      }
    >
      <DataPactPage shell={shellCtx.shell} />
    </Suspense>
  );
}

/* ------------------------------------------------------------------ */
/* Glossary & CDEs                                                      */
/* ------------------------------------------------------------------ */

function GlossaryRoute() {
  const shellCtx = useShellContext();
  // Wave-C4 flipped: the rebuilt Glossary & CDEs surface is
  // router-self-sufficient — it reads /glossary/:termId via useParams and
  // ?tab=/?cde=/?q=/?status= via useSurfaceParams, and renders real anchors
  // through the system refs contract. The legacy pending-term handoff
  // (ga-pending-glossary-term sessionStorage + ga:select-glossary-term
  // window event) is dead: nav/routes.js promotes legacy ?term= links to
  // the durable /glossary/<termId> path in the canonical gate upstream.
  // Only shell identity rides in — G6 term Approve/Reject is steward/admin-gated.
  return (
    <Suspense
      fallback={
        <RouteFallback
          eyebrow="Loading glossary"
          message="Preparing governed glossary terms and the CDE registry."
        />
      }
    >
      <GlossaryPage shell={shellCtx.shell} />
    </Suspense>
  );
}

/* ------------------------------------------------------------------ */
/* Lineage Atlas                                                        */
/* ------------------------------------------------------------------ */

function LineageRoute() {
  const shellCtx = useShellContext();

  // Wave-C7 flipped: the rebuilt Lineage Atlas surface is router-self-
  // sufficient — it reads /lineage/:fqn via the route splat and
  // ?context=/?selected= via useSurfaceParams, so the workspaceIntent
  // "lineageContext" sessionStorage staging that lived here is dead
  // (FRONTEND_BLUEPRINT §8 kill table) and no legacy adapter callbacks are
  // threaded. Bare /lineage mounts the search-first asset picker. Only
  // shell-owned signals ride in: bootstrap + seeds (capability gating and
  // seeded asset summaries) and runtime/workspace access gates.
  return (
    <Suspense
      fallback={
        <RouteFallback
          eyebrow="Loading lineage"
          message="Preparing the connected graph workspace and focus asset context."
        />
      }
    >
      <LineagePage
        bootstrap={shellCtx.bootstrap}
        contextSeedAssets={shellCtx.contextSeedAssets}
        runtimeFeatureFlags={shellCtx.runtimeFeatureFlags}
        workspaceAccess={shellCtx.surfaceWorkspaceAccess}
      />
    </Suspense>
  );
}

/* ------------------------------------------------------------------ */
/* Evidence / Admin / Help                                              */
/* ------------------------------------------------------------------ */

function EvidenceRoute() {
  const shellCtx = useShellContext();
  // Wave-C5 flipped: the unified Evidence surface (audit events + quality
  // findings) is router-self-sufficient — it reads ?tab/?event/?finding and
  // every filter via useSurfaceParams and renders real anchors through the
  // system refs contract, so no legacy adapter props are threaded. Only the
  // shell identity rides in (the audit-events tab is steward/admin gated).
  return (
    <Suspense
      fallback={
        <RouteFallback eyebrow="Loading evidence" message="Preparing audit events and quality findings." />
      }
    >
      <EvidencePage shell={shellCtx.shell} />
    </Suspense>
  );
}

function AdminRoute() {
  const shellCtx = useShellContext();

  // Wave-C6 flipped: the rebuilt Control Center is router-self-sufficient —
  // it reads ?tab= itself via useSurfaceParams (operations | integrations |
  // policy | diagnostics), and the /capabilities alias seeds ?tab=diagnostics
  // upstream in nav/routes.js, so the separate CapabilityDashboard mount is
  // gone. Only shell-owned signals are threaded: identity for the admin gate
  // (same predicate the rail uses) and bootstrap for the diagnostics
  // runtime-vs-bootstrap capability comparison.
  return (
    <Suspense
      fallback={
        <RouteFallback
          eyebrow="Loading Control Center"
          message="Preparing runtime, integration, and capability diagnostics."
        />
      }
    >
      <AdminPage bootstrap={shellCtx.bootstrap} shell={shellCtx.shell} />
    </Suspense>
  );
}

function HelpRoute() {
  const adapters = useLegacyNavAdapters();
  // Follow-up 3: HelpPage lives at surfaces/help on the system kit. The
  // legacy bootState prop was dead (never read) and is no longer threaded.
  return (
    <Suspense
      fallback={<RouteFallback eyebrow="Loading help" message="Preparing the in-app help and documentation page." />}
    >
      <HelpPage onBack={() => adapters.openDiscovery({}, { fresh: false })} />
    </Suspense>
  );
}

/* ------------------------------------------------------------------ */
/* AI governance (docs/ai_extension/DESIGN.md 10)                       */
/* ------------------------------------------------------------------ */

// Mounted only when the backend registered /api/ai (bootstrap
// shell.aiGovernance.enabled); otherwise a deep link lands on Home rather
// than a surface whose API does not exist.
function AiRoute({ detail = false }) {
  const shellCtx = useShellContext();
  const location = useLocation();
  if (!shellCtx.shell?.aiGovernance?.enabled) return <Navigate replace to="/home" />;
  const rawId = detail ? location.pathname.replace(/^\/ai\/assets\/?/, "") : "";
  let entityId = rawId;
  try {
    entityId = decodeURIComponent(rawId);
  } catch {
    // Malformed escapes: pass the raw text; the API rejects invalid ids (400).
  }
  return (
    <Suspense
      fallback={<RouteFallback eyebrow="Loading AI governance" message="Loading the AI inventory, findings, and intake records." />}
    >
      {detail ? <AiAssetPage entityId={entityId} shell={shellCtx.shell} /> : <AiGovernancePage shell={shellCtx.shell} />}
    </Suspense>
  );
}

/* ------------------------------------------------------------------ */
/* The tree                                                             */
/* ------------------------------------------------------------------ */

// Canonical paths only — AppShell's canonical gate (resolveUrl) has already
// 301'd every alias in nav/routes.js before this tree renders. Terminal
// `:fqn`/`:termId` params are greedy in the route table, so they mount as RR
// splats and the wrappers decode them (FQNs may carry "/" segments).
export function SurfaceRoutes() {
  return (
    <Routes>
      <Route element={<HomeRoute />} path="/home" />
      <Route element={<DiscoveryRoute />} path="/discovery" />
      <Route element={<AssetPickerRoute />} path="/assets" />
      <Route element={<AssetHubRoute />} path="/assets/*" />
      <Route element={<StewardshipRoute />} path="/stewardship" />
      <Route element={<DataPactRoute />} path="/datapact" />
      <Route element={<AiRoute />} path="/ai" />
      <Route element={<AiRoute detail />} path="/ai/assets/*" />
      <Route element={<GlossaryRoute />} path="/glossary/*" />
      <Route element={<GlossaryRoute />} path="/glossary" />
      <Route element={<LineageRoute />} path="/lineage/*" />
      <Route element={<LineageRoute />} path="/lineage" />
      <Route element={<EvidenceRoute />} path="/evidence" />
      <Route element={<AdminRoute />} path="/admin" />
      <Route element={<HelpRoute />} path="/help" />
      {/* resolveUrl redirects unknown paths too, but keep a terminal safety
          net so the router can never render a blank screen. */}
      <Route element={<Navigate replace to="/home" />} path="*" />
    </Routes>
  );
}

export default SurfaceRoutes;
