import { LoadingState } from "../components/system";

/*
 * app-shell/ShellStateCard.jsx — the ONE pre-boot / route-level state card
 * (cohesion follow-up 3). Replaces components/ShellStatePrimitives.jsx's
 * WorkspaceStateCard for the shell's boot gating, Suspense fallbacks, and
 * the error boundary. Composes the system kit (LoadingState is the only
 * legal loading rendering — COHESION law #3); the card chrome itself is
 * ax-shell-state-card in shell.css because these render BEFORE any routed
 * surface exists, where PageShell would be a lie.
 */

const TONES = new Set(["neutral", "good", "warn", "bad"]);

export function ShellStateCard({
  eyebrow = "",
  title = "",
  message = "",
  tone = "neutral",
  loading = false,
  actions = null,
  children = null,
}) {
  const resolvedTone = TONES.has(tone) ? tone : "neutral";
  return (
    <div className={`ax-shell-state-card tone-${resolvedTone}`} role={resolvedTone === "bad" ? "alert" : undefined}>
      {eyebrow ? <div className="ax-sys-eyebrow">{eyebrow}</div> : null}
      {title ? <h2>{title}</h2> : null}
      {message ? <p className="ax-shell-state-card-message">{message}</p> : null}
      {loading ? <LoadingState label={title || "Loading"} lines={3} variant="card" /> : null}
      {children ? <div className="ax-shell-state-card-extra">{children}</div> : null}
      {actions ? <div className="ax-shell-state-card-actions">{actions}</div> : null}
    </div>
  );
}

export default ShellStateCard;
