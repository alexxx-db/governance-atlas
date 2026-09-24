/*
 * app-shell/AppShell.jsx — the application shell (Wave B1).
 *
 * Replaces components/AppFrame.jsx (1,166 lines) + the shell halves of the
 * old App.jsx. Owns: the canonical-URL gate (every nav/routes.js alias 301s
 * through resolveUrl), the frame chrome (Rail + Header + main), the unified
 * ⌘K palette, the Atlas AI dock, the single ToastHost, the ?peek= asset
 * drawer, boot gating, and the workspace-setup diagnostics panel.
 *
 * The frame emits only ga-shell-* class names; the legacy stylesheets carry
 * selector aliases for them (see legacyShellContract.js) because their
 * surface-squeeze/sticky rules must keep applying until Wave C.
 */

import { Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Navigate, useLocation } from "react-router-dom";

import { StatusBanner, ToastHost } from "../components/system";
import { ShellStateCard } from "./ShellStateCard.jsx";
import WorkspaceDiagnosticsSurface from "./WorkspaceDiagnosticsSurface.jsx";
import WorkspaceSetupWizard from "./WorkspaceSetupWizard.jsx";
import { useCommandCenter } from "../hooks/useCommandCenter";
import { useGovernanceSummary } from "../hooks/useGovernanceSummary";
import { useInboxWork } from "../hooks/useInboxWork";
import { workspaceAccessBanner } from "../lib/capabilities";
import { isNonAuthoritativeMockEvidence } from "../lib/nonAuthoritativeEvidence";
import { readLastAsset } from "../lib/prefs";
import { resolveUrl } from "../nav/routes.js";
import { usePeek } from "../nav/useAtlasNavigate.js";
import { AtlasAiDock } from "./AtlasAiDock.jsx";
import { CommandPalette } from "./CommandPalette.jsx";
import { Header } from "./Header.jsx";
import { Rail } from "./Rail.jsx";
import { ShellProvider } from "./ShellContext.jsx";
import { useLegacyNavAdapters } from "./legacyAdapters.js";
import {
  LEGACY_OPEN_PALETTE_EVENT,
  SHELL_CLASSNAMES,
  SHELL_HEADER_HEIGHT_VAR,
} from "./legacyShellContract.js";
import { useShellRuntime } from "./useShellRuntime.js";

// Peek drawer content: the existing Asset 360 drawer, now URL-bound (?peek=).
const AssetPeekPanel = lazy(() =>
  import("../surfaces/asset/AssetPeekPanel.jsx").then((m) => ({ default: m.AssetPeekPanel ?? m.default }))
);

const GOOD_HEALTH_STATES = ["ready", "complete", "healthy", "available", "live"];

function shellHealthStateFor(bootState, shell, shellDisabled) {
  const shellTruthEnvelope =
    shell && typeof shell === "object"
      ? Object.fromEntries(Object.entries(shell).filter(([key]) => key !== "ai"))
      : {};
  const shellNonAuthoritative = isNonAuthoritativeMockEvidence(bootState, shellTruthEnvelope);
  return bootState === "live" && !shellDisabled
    ? "live"
    : shellNonAuthoritative
      ? "unavailable"
      : bootState === "error" || bootState === "unavailable"
        ? "unavailable"
        : bootState === "degraded"
          ? "degraded"
          : bootState === "loading"
            ? "loading"
            : "";
}

/**
 * @param {{ tone?: string, eyebrow?: string, title?: string, message?: string, loading?: boolean, children?: import('react').ReactNode }} props
 */
function BootStateCard({ tone, eyebrow, title, message, loading = false, children }) {
  return (
    <section className="ga-shell-route-state">
      <ShellStateCard eyebrow={eyebrow} loading={loading} message={message} title={title} tone={tone} />
      {children}
    </section>
  );
}

export function AppShell({ children }) {
  const location = useLocation();

  /* ---- canonical-URL gate (aliases, normalize hooks, unknown paths) ---- */
  const resolved = useMemo(
    () => resolveUrl(`${location.pathname}${location.search}`),
    [location.pathname, location.search],
  );
  const surface = resolved?.surface || "home";
  const routeAssetFqn =
    surface === "assets" || surface === "lineage" ? resolved?.pathParams?.fqn || "" : "";

  /* ---- data spine ---- */
  const runtime = useShellRuntime({ surface, assetFqn: routeAssetFqn });
  const {
    shell,
    bootstrapPending,
    bootstrapReady,
    bootstrapError,
    bootstrapRefreshError,
    effectiveBootState,
    effectiveBootMessage,
    summariesEnabled,
    shellDisabled,
    shellDisabledReason,
  } = runtime;

  // Bell + rail badge sources. Same query keys as the surfaces that render
  // the underlying lists, so react-query shares one cache entry.
  const governanceSummary = useGovernanceSummary({ enabled: summariesEnabled, sections: ["inbox"] });
  const inboxWork = useInboxWork({ enabled: summariesEnabled });
  const governanceInbox = governanceSummary.data?.inbox || null;
  const inboxUnreadCount = Number.isFinite(Number(governanceInbox?.unreadCount))
    ? Math.max(0, Math.trunc(Number(governanceInbox.unreadCount)))
    : 0;
  // Rail my-work badge = unread notifications + actionable work (legacy
  // composition). null until BOTH sources settle — never a definitive 0
  // while loading (cohesion law 3).
  const myWorkBadgeCount =
    summariesEnabled && !inboxWork.loading && !governanceSummary.loading
      ? inboxWork.badgeCount + inboxUnreadCount
      : null;

  // Header env chip coverage: same cache entry as the Command Center surface.
  const commandCenter = useCommandCenter({ enabled: bootstrapReady });
  const ucCoverageScore = commandCenter.hasLiveData
    ? commandCenter.data?.estate?.coverageScore ?? null
    : null;

  const adapters = useLegacyNavAdapters();
  const { peekFqn, closePeek } = usePeek();

  /* ---- chrome state ---- */
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [aiDockOpen, setAiDockOpen] = useState(false);
  const [diagnosticsOpen, setDiagnosticsOpen] = useState(false);
  const [shellHeaderHeight, setShellHeaderHeight] = useState(0);
  const shellHeaderRef = useRef(null);

  // The product ships dark; the attribute keeps legacy theme-scoped CSS honest.
  useEffect(() => {
    if (typeof document === "undefined") return;
    document.documentElement.setAttribute("data-theme", "dark");
  }, []);

  // ⌘K / Ctrl+K / "/" open the palette; Discovery's legacy window event
  // (see legacyShellContract) keeps working until Wave C1.
  useEffect(() => {
    if (typeof window === "undefined") return undefined;
    const onKey = (event) => {
      const activeTag = document.activeElement?.tagName;
      const isTypingField = activeTag === "INPUT" || activeTag === "TEXTAREA";
      const modKey = event.metaKey || event.ctrlKey;
      if (modKey && (event.key === "k" || event.key === "K") && !isTypingField) {
        event.preventDefault();
        setPaletteOpen((current) => !current);
      } else if (event.key === "/" && !isTypingField) {
        event.preventDefault();
        setPaletteOpen(true);
      }
    };
    const onOpenPalette = () => setPaletteOpen(true);
    window.addEventListener("keydown", onKey);
    window.addEventListener(LEGACY_OPEN_PALETTE_EVENT, onOpenPalette);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener(LEGACY_OPEN_PALETTE_EVENT, onOpenPalette);
    };
  }, []);

  // Diagnostics panel can only stay open while its surface is available.
  useEffect(() => {
    if (!runtime.diagnosticsAvailable) setDiagnosticsOpen(false);
  }, [runtime.diagnosticsAvailable]);

  // Close overlays on navigation (legacy behavior: module change closed
  // panels; the palette closes itself on run, this covers browser Back).
  useEffect(() => {
    setPaletteOpen(false);
  }, [location.pathname]);

  // Measure the sticky header and publish the legacy + new offset vars the
  // surface stylesheets consume (ported from AppFrame.jsx:795-856).
  useEffect(() => {
    const header = shellHeaderRef.current;
    if (!header) return undefined;
    let animationFrame = 0;
    const update = () => {
      const nextHeight = Math.max(
        0,
        Math.ceil(header.getBoundingClientRect?.().height || header.offsetHeight || 0),
      );
      setShellHeaderHeight((current) => (current === nextHeight ? current : nextHeight));
    };
    const schedule = () => {
      if (typeof window === "undefined") {
        update();
        return;
      }
      window.cancelAnimationFrame(animationFrame);
      animationFrame = window.requestAnimationFrame(update);
    };
    schedule();
    if (typeof ResizeObserver !== "undefined") {
      const observer = new ResizeObserver(schedule);
      observer.observe(header);
      return () => {
        if (typeof window !== "undefined") window.cancelAnimationFrame(animationFrame);
        observer.disconnect();
      };
    }
    if (typeof window !== "undefined") {
      window.addEventListener("resize", schedule);
    }
    return () => {
      if (typeof window !== "undefined") {
        window.cancelAnimationFrame(animationFrame);
        window.removeEventListener("resize", schedule);
      }
    };
  }, []);

  const handleSignOut = useCallback(() => {
    if (typeof window === "undefined") return;
    const workspaceHost = String(shell?.workspaceHost || shell?.workspace?.host || "").trim();
    const signOutUrl = workspaceHost
      ? `${workspaceHost.replace(/\/+$/, "")}/login.html?action=logOut`
      : "";
    const proceed =
      typeof window.confirm === "function"
        ? window.confirm(
            "Sign out?\n\nGovernance Atlas uses your Databricks workspace login. Continuing opens the Databricks sign-out page in a new tab.",
          )
        : true;
    if (!proceed) return;
    if (!signOutUrl) {
      window.alert?.(
        "Workspace sign-out is unavailable because the Databricks host was not provided by the runtime.",
      );
      return;
    }
    window.open(signOutUrl, "_blank", "noopener,noreferrer");
  }, [shell]);

  /* ---- derived chrome ---- */
  const shellHealthState = shellHealthStateFor(effectiveBootState, shell, shellDisabled);
  const numericUcCoverage = Number(ucCoverageScore);
  const hasUcCoverage = Number.isFinite(numericUcCoverage) && numericUcCoverage > 0;
  const environmentTone =
    GOOD_HEALTH_STATES.includes(shellHealthState) && hasUcCoverage
      ? "good"
      : GOOD_HEALTH_STATES.includes(shellHealthState) ||
          ["attention_required", "degraded", "warning", "loading", "pending"].includes(shellHealthState)
        ? "warn"
        : ["error", "failed", "unavailable"].includes(shellHealthState)
          ? "bad"
          : "";
  const showInbox = Boolean(
    shell?.userEmail && String(shell.userEmail).trim().toLowerCase() !== "unknown",
  );
  const accessBanner = workspaceAccessBanner({ workspaceAccess: runtime.workspaceAccess });
  const accessBannerMessage =
    accessBanner?.title === "Workspace-scoped metadata"
      ? "Workspace-scoped app-principal view; actor-scoped protected reads stay restricted."
      : accessBanner?.message || "";
  // Contextual Asset 360 rail entry: route focus first, then the peek.
  const contextAssetFqn = routeAssetFqn || peekFqn || "";
  // No-context target for the PERMANENT Asset 360 entry (owner directive 1):
  // the last record opened. Re-read on every navigation so leaving an asset
  // page immediately arms the entry to reopen it. Falls back to the picker
  // (bare /assets) inside the Rail when this is empty too.
  const lastAssetFqn = useMemo(() => readLastAsset(), [location.pathname]);

  const contextValue = useMemo(
    () => ({ ...runtime, surface, routeAssetFqn, governanceSummary, inboxWork }),
    [runtime, surface, routeAssetFqn, governanceSummary, inboxWork],
  );

  /* ---- canonical redirects (after all hooks; never after an early return) ---- */
  if (!resolved) {
    // Unknown path: same default the legacy parser applied.
    return <Navigate replace to="/home" />;
  }
  if (resolved.redirected) {
    return <Navigate replace to={`${resolved.pathname}${resolved.search}`} />;
  }

  /* ---- boot gating (ported from App.jsx) ---- */
  let content = children;
  if (bootstrapPending) {
    content = (
      <BootStateCard
        eyebrow="Preparing workspace shell"
        loading
        message="Confirming route handoff, identity headers, and shell capabilities before live surface hydration."
        title="Preparing the workspace surface."
      />
    );
  } else if (!bootstrapReady || bootstrapError) {
    content = (
      <BootStateCard
        eyebrow="Workspace Unavailable"
        message={
          bootstrapRefreshError ||
          bootstrapError ||
          "Verify warehouse access, Unity Catalog permissions, and governance configuration, then retry."
        }
        title="The live metadata workspace could not initialize."
        tone="bad"
      >
        {runtime.diagnosticsRecovery ? (
          <WorkspaceDiagnosticsSurface
            error={runtime.runtimeStatus.error}
            loading={runtime.runtimeStatus.loading}
            refreshError={runtime.runtimeStatus.refreshError}
            refreshing={runtime.runtimeStatus.refreshing}
            onRefresh={runtime.refreshDiagnostics}
            status={runtime.runtimeStatus.data}
            title="Setup Diagnostics"
          />
        ) : null}
      </BootStateCard>
    );
  } else if (effectiveBootState === "unavailable" || effectiveBootState === "error") {
    content = (
      <BootStateCard
        eyebrow="Workspace Unavailable"
        message={
          effectiveBootMessage ||
          "Verify warehouse access, Unity Catalog permissions, and governance configuration, then retry."
        }
        title="The live metadata workspace could not initialize."
        tone="bad"
      />
    );
  } else if (diagnosticsOpen) {
    content = (
      <section className="ga-shell-route-state">
        {/* Follow-up 3: the legacy SurfaceHeader primitive is gone — this is
            the one shell-owned header for the settings-entry readiness view. */}
        <header className="ga-shell-route-state-head">
          <div>
            <div className="ga-sys-eyebrow">Workspace setup</div>
            <h1>Workspace readiness guide</h1>
            <p>
              Operator-only setup truth. Read-only runtime guidance kept in the shell instead of a
              second readiness store.
            </p>
          </div>
          <button
            className="ga-shell-inline-link"
            onClick={() => setDiagnosticsOpen(false)}
            type="button"
          >
            Close workspace setup
          </button>
        </header>
        <WorkspaceSetupWizard
          error={runtime.runtimeStatus.error}
          loading={runtime.runtimeStatus.loading}
          refreshError={runtime.runtimeStatus.refreshError}
          refreshing={runtime.runtimeStatus.refreshing}
          onRefresh={runtime.refreshDiagnostics}
          status={runtime.runtimeStatus.data}
          title="Workspace setup"
        />
      </section>
    );
  }

  return (
    <ShellProvider value={contextValue}>
      <div
        className={SHELL_CLASSNAMES.app}
        data-active-module={surface}
        data-ai-open={aiDockOpen ? "true" : "false"}
        data-rail-collapsed="false"
        data-shell-sticky-ready={shellHeaderHeight > 0 ? "true" : "false"}
        style={/** @type {import('react').CSSProperties} */ ({ [SHELL_HEADER_HEIGHT_VAR]: `${shellHeaderHeight}px` })}
      >
        <Rail
          activeSurface={surface}
          contextAssetFqn={contextAssetFqn}
          lastAssetFqn={lastAssetFqn}
          myWorkBadgeCount={myWorkBadgeCount}
          shell={shell}
          shellDisabled={shellDisabled}
          shellDisabledReason={shellDisabledReason}
          onOpenSettings={() => setDiagnosticsOpen((current) => !current)}
          onOpenCapabilities={() => adapters.onNavigate("capabilities")}
          onSignOut={handleSignOut}
        />
        <header className={SHELL_CLASSNAMES.header} ref={shellHeaderRef}>
          <Header
            aiCopilotAvailable={runtime.atlasAiAvailable}
            aiUnavailableReason={runtime.atlasAiUnavailableReason}
            environmentTone={environmentTone}
            inboxMessage={governanceInbox?.message || ""}
            inboxState={governanceInbox?.state || ""}
            inboxUnreadCount={inboxUnreadCount}
            onOpenAiCopilot={() => setAiDockOpen(true)}
            onOpenPalette={() => setPaletteOpen(true)}
            shell={shell}
            shellDisabled={shellDisabled}
            shellDisabledReason={shellDisabledReason}
            showInbox={showInbox}
            ucCoverageScore={ucCoverageScore}
            ucStatusState={shellHealthState}
          />
        </header>

        <main className={SHELL_CLASSNAMES.main}>
          {accessBanner ? (
            /* The wrapper carries the full message as a hover/AT detail —
               the visible copy stays the condensed one-liner. */
            <div
              aria-label={accessBanner.message || undefined}
              className={SHELL_CLASSNAMES.accessBanner}
              title={accessBanner.message || undefined}
            >
              <StatusBanner
                message={accessBannerMessage}
                title={accessBanner.title}
                tone={accessBanner.tone === "bad" ? "danger" : accessBanner.tone === "good" ? "success" : "warning"}
              />
            </div>
          ) : null}
          {content}
        </main>

        <AtlasAiDock
          assetFqn={contextAssetFqn}
          available={runtime.atlasAiAvailable}
          onOpenChange={/** @type {any} */ (setAiDockOpen)}
          open={aiDockOpen}
          surface={surface}
          unavailableReason={runtime.atlasAiUnavailableReason}
        />

        {paletteOpen ? (
          <CommandPalette
            onClose={() => setPaletteOpen(false)}
            onNavigateRef={(ref) => adapters.navigate(ref)}
            onSearchDiscovery={(query) => adapters.openDiscovery({ q: query }, { fresh: true })}
            seedAssets={runtime.contextSeedAssets}
            shell={shell}
          />
        ) : null}

        {/* Global asset preview, URL-bound to ?peek= (usePeek) so it is
            addressable and shareable from ANY surface. Wave-B2 flipped: the
            rebuilt AssetPeekPanel owns its own system Drawer + shared hero. */}
        <Suspense fallback={null}>
          <AssetPeekPanel fqn={peekFqn} open={Boolean(peekFqn)} onClose={closePeek} />
        </Suspense>

        {/* One toast host for the whole product (system kit contract). */}
        <ToastHost />
      </div>
    </ShellProvider>
  );
}

export default AppShell;
