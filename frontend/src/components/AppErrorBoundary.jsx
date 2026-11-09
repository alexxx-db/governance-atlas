import { Component } from "react";
import { ShellStateCard } from "../app-shell/ShellStateCard.jsx";
import { Button } from "./system";

function formatErrorMessage(error) {
  if (!error) return "Unknown frontend error.";
  if (typeof error === "string") return error;
  if (typeof error.message === "string" && error.message.trim()) return error.message.trim();
  return error.name || "Unknown frontend error.";
}

/** Detect the "stale chunk after redeploy" failure.
 *
 * When we ship a new bundle, the old index.js held by an open tab keeps its
 * pre-built references to chunk file names whose hashes no longer exist on
 * the CDN. The next lazy `import()` resolves to a 404, which React surfaces
 * as either "Failed to fetch dynamically imported module" (Chromium/Safari)
 * or a ChunkLoadError (Webpack-era terminology, but some bundles still
 * throw it). Both mean the same thing: the user's tab is simply out of
 * date. We render a gentle "Reload to load the latest workspace" card with
 * a one-click reload button instead of the generic "unexpected rendering
 * failure" page.
 */
function isStaleChunkError(error) {
  if (!error) return false;
  const message = typeof error === "string" ? error : error.message || "";
  const name = (error && error.name) || "";
  if (name === "ChunkLoadError") return true;
  return /Failed to fetch dynamically imported module/i.test(message)
    || /Importing a module script failed/i.test(message)
    || /error loading dynamically imported module/i.test(message);
}

// Global errors that must NEVER tear down the whole app: request
// cancellations, benign browser noise, and stale-chunk fetch failures from a
// background prefetch. A single async reject (a cancelled fetch, a browser
// extension, ResizeObserver noise) previously replaced the entire UI with a
// raw error string — the app looked crashed when nothing user-facing broke.
function isBenignGlobalError(error) {
  if (!error) return true;
  const name = (error && error.name) || "";
  const message = typeof error === "string" ? error : error.message || "";
  if (name === "AbortError") return true;
  if (/ResizeObserver loop/i.test(message)) return true;
  if (/The (?:user )?aborted a request|signal is aborted|aborted/i.test(message)) return true;
  return false;
}

export default class AppErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = {
      // Only a real React render error (getDerivedStateFromError /
      // componentDidCatch) replaces the app. Global window/promise errors are
      // logged but never tear down the tree.
      error: null,
      // Stale-chunk errors surfaced globally (e.g. a background prefetch
      // import 404) DO warrant the reload card, but nothing else does.
      staleChunkEventError: null,
    };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    console.error("Axiom render failure", error, info);
  }

  componentDidMount() {
    this.handleWindowError = (event) => {
      const error = event?.error || new Error(event?.message || "Unhandled window error.");
      if (isStaleChunkError(error)) {
        this.setState({ staleChunkEventError: error });
        return;
      }
      if (isBenignGlobalError(error)) {
        event?.preventDefault?.();
        return;
      }
      console.error("Axiom unhandled window error", error);
    };
    this.handleUnhandledRejection = (event) => {
      const reason = event?.reason;
      const error =
        reason instanceof Error ? reason : new Error(typeof reason === "string" ? reason : "Unhandled promise rejection.");
      if (isStaleChunkError(error)) {
        this.setState({ staleChunkEventError: error });
        return;
      }
      if (!isBenignGlobalError(error)) {
        console.error("Axiom unhandled promise rejection", error);
      }
    };
    window.addEventListener("error", this.handleWindowError);
    window.addEventListener("unhandledrejection", this.handleUnhandledRejection);
  }

  componentWillUnmount() {
    window.removeEventListener("error", this.handleWindowError);
    window.removeEventListener("unhandledrejection", this.handleUnhandledRejection);
  }

  render() {
    const activeError = this.state.error || this.state.staleChunkEventError;
    if (!activeError) return this.props.children;

    // Stale-chunk failure after a redeploy. This is not a bug — the user's
    // browser is just holding an old index.js that references chunk names
    // the CDN no longer serves. Render a one-click-reload card instead of
    // the generic "rendering failure" message so users don't think the
    // app itself broke.
    if (isStaleChunkError(activeError)) {
      return (
        <section className="ax-shell-route-state">
          <ShellStateCard
            actions={
              <Button
                onClick={() => {
                  try {
                    window.location.reload();
                  } catch (_) {
                    /* ignore */
                  }
                }}
                variant="primary"
              >
                Reload now
              </Button>
            }
            eyebrow="New version available"
            message="Axiom has been redeployed since you opened this tab. Reload to load the newest workspace bundle."
            title="Reload to pick up the latest build"
            tone="neutral"
          >
            <p className="ax-shell-state-card-message">
              Your session will be preserved — the reload only refreshes the
              client-side bundle.
            </p>
          </ShellStateCard>
        </section>
      );
    }

    return (
      <section className="ax-shell-route-state">
        <ShellStateCard
          actions={
            <Button
              onClick={() => {
                try {
                  window.location.reload();
                } catch (_) {
                  /* ignore */
                }
              }}
              variant="primary"
            >
              Reload workspace
            </Button>
          }
          eyebrow="Frontend Error"
          message={formatErrorMessage(activeError)}
          title="The workspace hit an unexpected rendering failure."
          tone="bad"
        >
          <p className="ax-shell-state-card-message">
            The page stayed reachable, but a client-side error interrupted rendering. Reloading usually recovers the workspace.
          </p>
        </ShellStateCard>
      </section>
    );
  }
}
