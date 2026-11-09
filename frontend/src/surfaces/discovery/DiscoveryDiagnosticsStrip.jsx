import "./discovery.css";
import {
  labelForAuthMode,
  labelForDiscoveryState,
  labelForInventorySource,
  labelForRuntimeState,
} from "./discoveryPresentation";

/*
 * Compact diagnostics strip rendered alongside Discover empty/degraded
 * states (Wave C1 port, audit A1.4). One muted line of humanized runtime
 * facts — never raw enums ("no_matches") or ISO dumps — so an empty result
 * is explainable at a glance. Only rendered on empty-state paths.
 */

export function DiscoveryDiagnosticsStrip({
  runtimeState = "",
  authMode = "",
  visibilityScope = "",
  visibleAssets = null,
  observedAt = "",
  inventorySource = "",
  discoveryState = "",
}) {
  const runtimeLabel = labelForRuntimeState(runtimeState);
  const authLabel = labelForAuthMode(authMode);
  const sourceLabel = labelForInventorySource(inventorySource || visibilityScope, authMode);
  const stateLabel = labelForDiscoveryState(discoveryState);
  const visibleCountLabel =
    visibleAssets === null || visibleAssets === undefined || Number.isNaN(Number(visibleAssets))
      ? "—"
      : Number(visibleAssets).toLocaleString();
  const observedDate = observedAt ? new Date(String(observedAt)) : null;
  const observedLabel =
    observedDate && !Number.isNaN(observedDate.getTime())
      ? observedDate.toLocaleString("en-US", {
          month: "short",
          day: "numeric",
          year: "numeric",
          hour: "2-digit",
          minute: "2-digit",
          hour12: false,
          timeZone: "UTC",
          timeZoneName: "short",
        })
      : observedAt
        ? String(observedAt)
        : "—";

  const item = (label, value, testId, title) => (
    <span className="ax-disc-diagnostics-item">
      <span className="ax-disc-diagnostics-label">{label}</span>
      <span className="ax-disc-diagnostics-value" data-testid={testId} title={title}>
        {value}
      </span>
    </span>
  );
  const sep = <span aria-hidden="true" className="ax-disc-diagnostics-sep">·</span>;

  return (
    <div
      aria-label="Discovery diagnostics"
      className="ax-disc-diagnostics"
      data-testid="ax-disc-diagnostics"
      role="status"
    >
      {item("Runtime", runtimeLabel, "ax-disc-diagnostics-runtime")}
      {sep}
      {/* "Access", not "Auth mode": customer-facing wording, no OBO enum. */}
      {item("Access", authLabel, "ax-disc-diagnostics-auth")}
      {sep}
      {item("Inventory", sourceLabel, "ax-disc-diagnostics-source")}
      {sep}
      {item("Visible assets", visibleCountLabel, "ax-disc-diagnostics-visible")}
      {sep}
      {item(
        "Last observed",
        observedLabel,
        "ax-disc-diagnostics-observed",
        observedAt ? String(observedAt) : undefined,
      )}
      {stateLabel ? (
        <>
          {sep}
          {item("Status", stateLabel, "ax-disc-diagnostics-state")}
        </>
      ) : null}
    </div>
  );
}

export default DiscoveryDiagnosticsStrip;
