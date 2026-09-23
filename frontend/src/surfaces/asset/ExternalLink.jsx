/*
 * surfaces/asset/ExternalLink.jsx — the "Open in Databricks" affordance
 * (owner directive 2: "I should be able to open any and all of these assets
 * directly in Databricks and the catalog explorer").
 *
 * ONE builder + ONE presentational anchor, reused by the Asset 360 header and
 * the ?peek= drawer so the two can never diverge. EntityChip stays pure (it is
 * an internal-route chip); external Databricks links live here instead.
 *
 * URL resolution (deep-link first, constructed fallback):
 *   1. Prefer the live access-explain deepLink (access.deepLinks.catalogExplorer)
 *      — the backend already emits the workspace-correct RELATIVE path
 *      (/explore/data/<catalog>/<schema>/<table>, capabilities.py). We only
 *      prepend the workspace host so the anchor opens Databricks, not the app
 *      origin.
 *   2. Otherwise construct the SAME shape from a real three-part FQN. Verified
 *      against the live workspace + the backend contract: catalog / schema /
 *      remaining name segments, exactly as system.information_schema names them.
 */

import { useContext } from "react";
import ShellContext from "../../app-shell/ShellContext";
import { workspaceHostFromBootstrap } from "../lineage/lineagePresentation";

/**
 * The Databricks workspace host this deployment is bound to, from the backend
 * bootstrap (DATABRICKS_HOST, injected by Databricks Apps). Never hard-code
 * it: a baked-in host sends every other install's links to the wrong
 * workspace. "" outside the shell or before bootstrap resolves.
 */
export function useWorkspaceHost() {
  const ctx = useContext(ShellContext);
  return String(ctx?.shell?.workspaceHost || workspaceHostFromBootstrap(ctx?.bootstrap) || "").trim();
}

/** Trim trailing slashes so host + path never double up. */
function trimHost(host) {
  return String(host || "").replace(/\/+$/, "");
}

/**
 * Absolute Catalog Explorer URL for an asset — deepLink preferred, constructed
 * from the FQN as a fallback. Returns "" when neither yields a usable target
 * (so callers can simply not render the affordance).
 *
 * @param {string} fqn        three-part Unity Catalog name (catalog.schema.table)
 * @param {string} [deepLink] live access.deepLinks.catalogExplorer (may be
 *                            relative "/explore/..." or already absolute)
 * @param {string} [host]     workspace host (useWorkspaceHost())
 */
export function catalogExplorerUrl(fqn, deepLink, host = "") {
  const base = trimHost(host);
  const dl = String(deepLink || "").trim();
  if (dl && /^https?:\/\//i.test(dl)) return dl; // already absolute — trust it
  // A relative path without a host would resolve against the Atlas app origin
  // and 404, so render no link rather than a broken one.
  if (!base) return "";
  if (dl) {
    return `${base}/${dl.replace(/^\/+/, "")}`;
  }
  const parts = String(fqn || "")
    .split(".")
    .map((part) => part.trim())
    .filter(Boolean);
  // Catalog Explorer needs at least catalog.schema.table. Anything shorter is
  // not an addressable data object, so there is no honest link to render.
  if (parts.length < 3) return "";
  // Match the backend construction verbatim (capabilities.py): catalog /
  // schema / the remaining segments joined — no re-encoding, so the URL shape
  // is byte-identical to the deepLink path Databricks itself serves.
  return `${base}/explore/data/${parts.join("/")}`;
}

const ExternalIcon = (
  <svg
    aria-hidden="true"
    viewBox="0 0 24 24"
    width="15"
    height="15"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.9"
    strokeLinecap="round"
    strokeLinejoin="round"
  >
    <path d="M14 5h5v5" />
    <path d="M19 5l-8 8" />
    <path d="M18 14v4a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4" />
  </svg>
);

/**
 * "Open in Databricks" anchor. Renders nothing without an href (a real FQN is
 * required upstream). Opens in a new tab with rel="noopener noreferrer" and the
 * contractual title. Styled as a secondary system button so it sits inline with
 * the header/peek controls; pass `variant="menu"` for a plain menu-item row.
 */
/**
 * @param {{ href?: any, label?: string, variant?: string, className?: string, onClick?: any }} props
 */
export function ExternalLink({
  href,
  label = "Open in Databricks",
  variant = "button",
  className = "",
  onClick,
}) {
  if (!href) return null;
  const classes =
    variant === "menu"
      ? ["ga-asset-menu-item", className].filter(Boolean).join(" ")
      : ["ga-sys-button", "is-secondary", "tone-neutral", "size-md", "ga-asset-open-databricks", className]
          .filter(Boolean)
          .join(" ");
  return (
    <a
      className={classes}
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      title="Open in Databricks Catalog Explorer"
      onClick={onClick}
    >
      <span className="ga-sys-button-icon" aria-hidden="true">
        {ExternalIcon}
      </span>
      <span className="ga-sys-button-label">{label}</span>
    </a>
  );
}

export default ExternalLink;
