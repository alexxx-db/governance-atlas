/*
 * app-shell/Header.jsx — the global top bar (Wave B1).
 *
 * Absorbs components/primitives/GlobalHeader.jsx. Changes vs the original:
 *   - The inline TopbarSearch typeahead is gone: header search and ⌘K are
 *     unified on the one palette (usePaletteSearch) — the search box is a
 *     trigger that opens it (Wave B1 spec).
 *   - The bell no longer toggles a transient panel/dead InboxPanel: it links
 *     to /stewardship?assignee=me (the inbox's absorbed address). It stays a
 *     real anchor so it is middle-clickable.
 */

import { PRODUCT } from "../config/product";
import { isNonAuthoritativeMockEvidence } from "../lib/nonAuthoritativeEvidence";
import { refHref } from "../nav/refs.js";
import { useAxiomNavigate } from "../nav/useAxiomNavigate.js";
import { SHELL_CLASSNAMES } from "./legacyShellContract.js";

const BellIcon = () => (
  <svg aria-hidden="true" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <path d="M6 8a6 6 0 0 1 12 0c0 4 2 5 2 7H4c0-2 2-3 2-7Z" />
    <path d="M10 20a2 2 0 0 0 4 0" />
  </svg>
);

const SparkIcon = () => (
  <svg aria-hidden="true" viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="4.5" cy="7" r="1.35" fill="currentColor" stroke="none" />
    <circle cx="6.6" cy="16.2" r="1.05" fill="currentColor" stroke="none" opacity="0.82" />
    <path d="m12 3 1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3Z" />
    <path d="m18 15 .8 2.2L21 18l-2.2.8L18 21l-.8-2.2L15 18l2.2-.8L18 15Z" />
  </svg>
);

const WorkspaceIcon = () => (
  <svg aria-hidden="true" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <path d="M4 4h6v6H4z" />
    <path d="M14 4h6v6h-6z" />
    <path d="M4 14h6v6H4z" />
    <path d="M14 14h6v6h-6z" />
  </svg>
);

const HelpIcon = () => (
  <svg aria-hidden="true" viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="12" r="9" />
    <path d="M9.5 9a2.7 2.7 0 0 1 5 1.4c0 1.8-2.5 2.1-2.5 4" />
    <path d="M12 17.5h.01" />
  </svg>
);

const SearchIcon = () => (
  <svg aria-hidden="true" viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="11" cy="11" r="7" />
    <path d="m20 20-3.5-3.5" />
  </svg>
);

function resolveProductName(shell) {
  const shellProductName = shell?.product?.productName;
  return typeof shellProductName === "string" && shellProductName.trim()
    ? shellProductName.trim()
    : PRODUCT.productName;
}

function resolveEnvironmentTitle(shell) {
  const environment = shell?.environment || {};
  const parts = [
    environment.label ? `Target: ${environment.label}` : "",
    environment.catalog || environment.schema
      ? `Namespace: ${[environment.catalog, environment.schema].filter(Boolean).join(".")}`
      : "",
    environment.warehouseId ? `Warehouse: ${environment.warehouseId}` : "",
    environment.workspaceHost ? `Workspace: ${environment.workspaceHost}` : "",
  ].filter(Boolean);
  return parts.length ? parts.join(" | ") : "Workspace environment";
}

function resolveWorkspaceLabel(shell) {
  const environment = shell?.environment || {};
  const explicit =
    shell?.workspaceLabel ||
    shell?.workspaceName ||
    shell?.workspace?.name ||
    environment.workspaceLabel ||
    environment.workspaceName ||
    environment.target ||
    environment.label;
  return typeof explicit === "string" && explicit.trim() ? explicit.trim() : "Workspace";
}

function resolveUcStatusLabel(environmentTone = "", coverageScore = null, statusState = "") {
  const state = String(statusState || "").toLowerCase();
  if (state === "loading") return "UC status loading";
  const numericCoverage = Number(coverageScore);
  if (isNonAuthoritativeMockEvidence(state)) return "UC unavailable";
  if (state === "degraded") return "UC status degraded";
  if (state === "unavailable" || state === "error" || state === "failed") return "UC unavailable";
  if (environmentTone === "good" && Number.isFinite(numericCoverage) && numericCoverage > 0) {
    return `UC connected · ${numericCoverage.toFixed(1).replace(/\.0$/, "")}% coverage`;
  }
  if (environmentTone === "good" || environmentTone === "warn") {
    return environmentTone === "warn" ? "UC connected · coverage unavailable" : "UC connected";
  }
  if (environmentTone === "bad") return "UC unavailable";
  return "UC status unknown";
}

function isModifiedClick(event) {
  return event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey;
}

export function Header({
  shell,
  shellDisabled = false,
  shellDisabledReason = "",
  showInbox = false,
  inboxUnreadCount = 0,
  inboxState = "",
  inboxMessage = "",
  environmentTone = "",
  ucCoverageScore = null,
  ucStatusState = "",
  aiCopilotAvailable = false,
  aiUnavailableReason = "",
  onOpenPalette,
  onOpenAiCopilot,
}) {
  const navigate = useAxiomNavigate();
  const productName = resolveProductName(shell);
  const environmentTitle = resolveEnvironmentTitle(shell);
  const workspaceLabel = resolveWorkspaceLabel(shell);
  const environmentLabel = resolveUcStatusLabel(environmentTone, ucCoverageScore, ucStatusState);
  const inboxUnavailable = ["unavailable", "degraded", "error"].includes(
    String(inboxState || "").trim().toLowerCase(),
  );
  const notificationsLabel =
    inboxUnreadCount > 0
      ? `Notifications (${inboxUnreadCount} unread)`
      : inboxUnavailable
        ? "Notifications unavailable"
        : "Notifications";
  const notificationsTitle = inboxUnavailable
    ? inboxMessage || "Notification delivery health is unavailable. Open your work queue for details."
    : "Notifications — open your stewardship work";
  // The inbox surface was absorbed: its address is the queue scoped to me.
  const inboxTarget = { surface: "stewardship", params: { assignee: "me" } };
  const helpTarget = { surface: "help" };

  const anchorNav = (target) => (event) => {
    if (isModifiedClick(event)) return;
    event.preventDefault();
    if (shellDisabled) return;
    navigate(target);
  };

  return (
    <div className={`ax-topbar ${SHELL_CLASSNAMES.topbar}`}>
      <a
        aria-label={`Open ${productName} Command Center`}
        className="ax-workspace-breadcrumb"
        href={refHref({ surface: "home" })}
        onClick={anchorNav({ surface: "home" })}
        title={shellDisabledReason || "Open Command Center"}
      >
        <WorkspaceIcon />
        <span>Workspace</span>
        <span aria-hidden="true" className="ax-workspace-breadcrumb-separator">›</span>
        <strong>{workspaceLabel}</strong>
      </a>
      <div className="ax-topbar-search-slot">
        {/* Search and ⌘K are one system now: the box opens the palette with
            focus, so typing continues seamlessly. */}
        <button
          aria-haspopup="dialog"
          aria-label="Search assets, glossary terms, and owners"
          className="ax-shell-search-trigger"
          disabled={shellDisabled}
          onClick={() => onOpenPalette?.()}
          title={shellDisabled ? shellDisabledReason : "Search (⌘K)"}
          type="button"
        >
          <SearchIcon />
          <span>Search assets, terms, owners…</span>
          <span aria-hidden="true" className="ax-shell-search-kbd">
            <kbd>⌘</kbd>
            <kbd>K</kbd>
          </span>
        </button>
      </div>
      <div className="ax-topbar-actions">
        <span
          className={`ax-env-chip ${environmentTone ? `tone-${environmentTone}` : ""}`.trim()}
          title={environmentTitle}
        >
          {environmentTone ? <span aria-hidden="true" className="ax-status-dot" /> : null}
          <span>{environmentLabel}</span>
        </span>
        {showInbox ? (
          <a
            aria-label={notificationsLabel}
            className={`ax-icon-button ax-notifications-button ${inboxUnavailable ? "is-unavailable" : ""}`.trim()}
            href={refHref(inboxTarget)}
            onClick={anchorNav(inboxTarget)}
            title={notificationsTitle}
          >
            <BellIcon />
            {inboxUnreadCount > 0 ? (
              <span aria-hidden="true" className="ax-notification-count">
                {inboxUnreadCount > 9 ? "9+" : inboxUnreadCount}
              </span>
            ) : null}
          </a>
        ) : null}
        <a
          aria-label="Help"
          className="ax-icon-button ax-help-button"
          href={refHref(helpTarget)}
          onClick={anchorNav(helpTarget)}
          title="Help"
        >
          <HelpIcon />
        </a>
        <button
          aria-disabled={!aiCopilotAvailable}
          className="ax-ai-chip is-primary"
          disabled={!aiCopilotAvailable}
          onClick={aiCopilotAvailable ? onOpenAiCopilot : undefined}
          title={
            aiCopilotAvailable
              ? "Open Axiom AI"
              : aiUnavailableReason || "Axiom AI requires an evidence-backed endpoint before activation."
          }
          type="button"
        >
          <SparkIcon />
          <span>{PRODUCT.aiName}</span>
        </button>
      </div>
    </div>
  );
}

export default Header;
