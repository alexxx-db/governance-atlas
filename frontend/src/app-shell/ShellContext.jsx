/*
 * app-shell/ShellContext.jsx — the shell → surface data channel (Wave B1).
 *
 * Replaces App.jsx's 10-22-prop drilling: route wrappers (SurfaceRoutes.jsx)
 * read bootstrap/shell/capability signals from here and pass ONLY the props
 * each legacy surface genuinely consumes. Navigation callbacks are NOT in the
 * context — they come from app-shell/legacyAdapters.js over useAxiomNavigate.
 */

import { createContext, useContext } from "react";

const ShellContext = createContext(null);

export function ShellProvider({ value, children }) {
  return <ShellContext.Provider value={value}>{children}</ShellContext.Provider>;
}

export function useShellContext() {
  const value = useContext(ShellContext);
  if (!value) {
    throw new Error("useShellContext must be used inside <AppShell>");
  }
  return value;
}

export default ShellContext;
