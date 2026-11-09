import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import AppErrorBoundary from "./components/AppErrorBoundary";
import { axiomQueryClient } from "./lib/queryClient";
// Design tokens first (they lived at the top of the deleted app.css).
import "./design/tokens/index.css";
// Cohesion follow-up 3: app.css / entity.css / governance.css are DEAD.
// Their base layer (reset, body, focus ring) moved to app-shell/shell.css;
// the one surviving legacy-classed rule lives in legacy-remnants.css.
import "./styles/legacy-remnants.css";
import "./styles/shell-rail.css";
import "./styles/northstar.css";
import "./styles/lineage-v2.css";
// New-shell chrome (Wave B1): loads AFTER the legacy sheets so ax-shell-*
// rules win where both target the same element during the migration.
import "./app-shell/shell.css";
// Narrow-viewport hardening (mini-rail inner chrome). Imported last so its
// ax-* rail rules win by source order without !important.
import "./styles/responsive.css";

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <BrowserRouter>
      <QueryClientProvider client={axiomQueryClient}>
        <AppErrorBoundary>
          <App />
        </AppErrorBoundary>
      </QueryClientProvider>
    </BrowserRouter>
  </React.StrictMode>
);
