import "./asset.css";
import { useEffect, useRef, useState } from "react";
import { createGovernanceRequest } from "../../lib/api";
import { Button, Drawer, toast } from "../../components/system";
import { useAtlasNavigate } from "../../nav/useAtlasNavigate";
import { ExternalLink, catalogExplorerUrl, useWorkspaceHost } from "./ExternalLink";
import { certifyGate, lineageGate, requestChangeGate } from "./gates";

/*
 * AssetHeaderActions — the four header controls, all honest (teardown P1-5
 * killed: Certify-with-no-menu, Request-Change-as-navigation, kebab-as-copy-
 * button, bootstrap-pessimistic lineage button).
 *
 *   Certify        real dropdown; writes via the metadata PATCH path when the
 *                  live contract allows, else stages a change request — and
 *                  the menu says which, before the click.
 *   Request Change dialog (summary + reason) → the real create-request API,
 *                  pre-scoped to this asset.
 *   Open lineage   navigates to /lineage/<fqn>; label/tooltip from the LIVE
 *                  per-asset graph (gates.js — never bootstrap pessimism).
 *   Kebab          real menu: Copy link, Open in Catalog Explorer (live
 *                  access deep link, honest disabled reason otherwise).
 */

/** Certification options: strict-certify, plus revoke. */
const CERTIFY_OPTIONS = [
  { key: "certify", label: "Mark as Certified", value: "Certified" },
  { key: "revoke", label: "Revoke certification", value: "" },
];

/** Small headless menu: outside-click + Escape close, roving menu items. */
function useMenu() {
  const [open, setOpen] = useState(false);
  const rootRef = useRef(null);
  useEffect(() => {
    if (!open) return undefined;
    const onPointerDown = (event) => {
      if (rootRef.current && !rootRef.current.contains(event.target)) setOpen(false);
    };
    const onKeyDown = (event) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);
  return { open, setOpen, rootRef };
}

async function copyText(text) {
  if (navigator?.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return true;
  }
  return false;
}

/**
 * @param {{
 *   fqn?: string,
 *   editor?: any,
 *   access?: any,
 *   graph?: any,
 *   onCertified?: (value?: any) => void,
 *   onAfterWrite?: () => void,
 * }} props
 */
export function AssetHeaderActions({
  fqn,
  editor,
  access,
  graph,
  onCertified = () => {},
  onAfterWrite = () => {},
}) {
  const navigate = useAtlasNavigate();
  const certifyMenu = useMenu();
  const kebabMenu = useMenu();
  const [certifying, setCertifying] = useState("");
  const [requestOpen, setRequestOpen] = useState(false);
  const [requestSummary, setRequestSummary] = useState("");
  const [requestReason, setRequestReason] = useState("");
  const [requestBusy, setRequestBusy] = useState(false);

  const certify = certifyGate(editor);
  const lineage = lineageGate(graph);
  const requestGate = requestChangeGate(fqn);
  // Owner directive 2: "Open in Databricks" is FIRST-CLASS — a visible header
  // button that always renders for a real FQN. Prefer the live access deepLink;
  // fall back to the constructed Catalog Explorer URL. The workspace host is
  // prepended so the anchor opens Databricks, not the app origin.
  const workspaceHost = useWorkspaceHost();
  const explorerHref = catalogExplorerUrl(fqn, access?.deepLinks?.catalogExplorer, workspaceHost);

  const handleCertify = async (option) => {
    certifyMenu.setOpen(false);
    if (certifying) return;
    setCertifying(option.key);
    try {
      if (certify.mode === "write") {
        // Real write through the existing metadata path — the backend
        // audit-logs metadata updates, so no parallel audit call is needed.
        await editor.save({ certification: option.value });
        onCertified(option.value); // optimistic badge until refetch confirms
        toast(
          option.value
            ? `Certification set to ${option.value}.`
            : "Certification revoked.",
          { tone: "success" },
        );
        onAfterWrite();
      } else {
        // No live write contract: stage a pre-filled change request via the
        // real create-request API — never a dead click (cohesion law 7).
        const response = await createGovernanceRequest(
          {
            assetFqn: fqn,
            title: option.value
              ? `Certification change requested: ${option.value}`
              : "Certification revocation requested",
            note: `Requested from the Asset 360 record for ${fqn}. ${certify.reason}`,
          },
          { fast: true },
        );
        const requestId = String(response?.requestId || "").trim();
        toast(
          `Direct writes are not enabled for this asset — filed change request${requestId ? ` ${requestId}` : ""} for steward review.`,
          { tone: "neutral" },
        );
        onAfterWrite();
      }
    } catch (error) {
      toast(error?.message || "Certification update failed.", { tone: "danger" });
    } finally {
      setCertifying("");
    }
  };

  const handleRequestSubmit = async (event) => {
    event.preventDefault();
    const summary = requestSummary.trim();
    const reason = requestReason.trim();
    if (!summary || requestBusy) return;
    setRequestBusy(true);
    try {
      const response = await createGovernanceRequest(
        { assetFqn: fqn, title: summary, note: reason },
        { fast: true },
      );
      const requestId = String(response?.requestId || "").trim();
      toast(`Change request${requestId ? ` ${requestId}` : ""} filed for ${fqn}.`, {
        tone: "success",
      });
      setRequestOpen(false);
      setRequestSummary("");
      setRequestReason("");
      onAfterWrite();
    } catch (error) {
      toast(error?.message || "Failed to file the change request.", { tone: "danger" });
    } finally {
      setRequestBusy(false);
    }
  };

  const handleCopyLink = async () => {
    kebabMenu.setOpen(false);
    const href = `${window.location.origin}/assets/${encodeURIComponent(fqn)}`;
    try {
      const copied = await copyText(href);
      toast(copied ? "Link copied to clipboard." : `Copy unavailable — link: ${href}`, {
        tone: copied ? "success" : "warning",
      });
    } catch {
      toast(`Copy failed — link: ${href}`, { tone: "warning" });
    }
  };

  return (
    <div className="ga-asset-actions">
      <Button
        variant="secondary"
        disabled={!requestGate.enabled}
        title={requestGate.reason || undefined}
        onClick={() => setRequestOpen(true)}
      >
        Request change
      </Button>

      <ExternalLink href={explorerHref} />

      <Button
        variant="secondary"
        title={lineage.reason || undefined}
        onClick={() => navigate({ kind: "lineage", fqn })}
      >
        {lineage.label}
      </Button>

      <div className="ga-asset-menu-root" ref={certifyMenu.rootRef}>
        <Button
          variant="primary"
          tone="accent"
          loading={Boolean(certifying)}
          aria-haspopup="menu"
          aria-expanded={certifyMenu.open}
          onClick={() => certifyMenu.setOpen((value) => !value)}
        >
          Certify
          {/* Real SVG chevron in the kit's icon slot — the old "⌄" glyph sat
              off the text baseline (flex centers an SVG, not a glyph). */}
          <span className="ga-sys-button-icon" aria-hidden="true">
            <svg
              viewBox="0 0 24 24"
              width="14"
              height="14"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="m6 9 6 6 6-6" />
            </svg>
          </span>
        </Button>
        {certifyMenu.open ? (
          <div className="ga-asset-menu" role="menu" aria-label="Certification actions">
            {certify.mode === "stage" ? (
              // Honesty before the click: the menu states that selections
              // stage a change request instead of writing directly.
              <p className="ga-asset-menu-note">{certify.reason}</p>
            ) : null}
            {CERTIFY_OPTIONS.map((option) => (
              <button
                key={option.key}
                type="button"
                role="menuitem"
                className="ga-asset-menu-item"
                onClick={() => handleCertify(option)}
              >
                {certify.mode === "stage" ? `${option.label} (via change request)` : option.label}
              </button>
            ))}
          </div>
        ) : null}
      </div>

      <div className="ga-asset-menu-root" ref={kebabMenu.rootRef}>
        <Button
          variant="secondary"
          aria-label="More asset actions"
          aria-haspopup="menu"
          aria-expanded={kebabMenu.open}
          onClick={() => kebabMenu.setOpen((value) => !value)}
        >
          ⋮
        </Button>
        {kebabMenu.open ? (
          <div className="ga-asset-menu" role="menu" aria-label="More asset actions">
            <button type="button" role="menuitem" className="ga-asset-menu-item" onClick={handleCopyLink}>
              Copy link
            </button>
            {/* "Open in Catalog Explorer" was promoted OUT of this menu into
                the first-class header button (owner directive 2). Kept here as
                a redundant menu-row too so the affordance is discoverable from
                either place — same absolute Databricks URL. */}
            <ExternalLink
              href={explorerHref}
              label="Open in Catalog Explorer"
              variant="menu"
              onClick={() => kebabMenu.setOpen(false)}
            />
          </div>
        ) : null}
      </div>

      <Drawer
        open={requestOpen}
        onClose={() => setRequestOpen(false)}
        title="Request a change"
        footer={
          <div className="ga-asset-dialog-footer">
            <Button variant="tertiary" onClick={() => setRequestOpen(false)}>
              Cancel
            </Button>
            <Button
              variant="primary"
              tone="accent"
              type="submit"
              form="ga-asset-request-form"
              loading={requestBusy}
              disabled={!requestSummary.trim()}
            >
              File request
            </Button>
          </div>
        }
      >
        <form id="ga-asset-request-form" className="ga-asset-dialog-form" onSubmit={handleRequestSubmit}>
          <p className="ga-asset-dialog-scope">
            Scoped to <strong>{fqn}</strong> — filed through the governance request queue.
          </p>
          <label className="ga-asset-field">
            <span>Summary</span>
            <input
              type="text"
              value={requestSummary}
              onChange={(event) => setRequestSummary(event.target.value)}
              placeholder="What should change on this asset?"
              required
            />
          </label>
          <label className="ga-asset-field">
            <span>Reason</span>
            <textarea
              value={requestReason}
              onChange={(event) => setRequestReason(event.target.value)}
              placeholder="Why is this change needed? Context helps the steward triage."
              rows={4}
            />
          </label>
        </form>
      </Drawer>
    </div>
  );
}

export default AssetHeaderActions;
