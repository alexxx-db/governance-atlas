/*
 * Axiom system component kit — Wave A1
 * (docs/architecture/FRONTEND_BLUEPRINT.md §6, COHESION_BLUEPRINT "Three
 * system layers" #1). One kit, one directory, one stylesheet, all
 * `ax-sys-*` classes on `--ax-*` tokens. Dependencies point inward only:
 * nothing in system/ imports from components/* outside system/.
 *
 * The kit ships unused in Wave A by design — consumers arrive in Waves B/C.
 * Do NOT import system.css from main.jsx in this wave; the components
 * import it themselves, so any consumer pulls the styles automatically.
 */
import "./system.css";

export { PageShell } from "./PageShell";
export { SectionCard } from "./SectionCard";
export { StatTile } from "./StatTile";
export { EntityChip } from "./EntityChip";
export { DataTable } from "./DataTable";
export {
  StateViews,
  LoadingState,
  EmptyState,
  UnavailableState,
  StatusBanner,
  ForQuery,
} from "./StateViews";
export { toast, ToastHost } from "./Toast";
export { Drawer } from "./Drawer";
export { TabStrip } from "./TabStrip";
export { FilterBar } from "./FilterBar";
export { Badge } from "./Badge";
export { Button } from "./Button";
export { SuggestInput } from "./SuggestInput";

// Shared contracts — Waves B/C compose against these, never re-derive them.
export { hrefForRef, defaultRefLabel } from "./refs";
export { normalizeStatus, statusShowsData, QUERY_STATUSES } from "./statusContract";
