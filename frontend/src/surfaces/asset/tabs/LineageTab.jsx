import "../asset.css";
import { LineageCanvasV2 } from "../../../components/lineage-v2/LineageCanvasV2";

/*
 * Lineage tab — the resurrected in-page lineage canvas (teardown item 12:
 * the embed existed, worked, and was unreachable dead code). Same
 * useLineageGraphV2 adapter + LineageCanvasV2 as the Lineage Atlas, so the
 * embedded view stays in lock step with the full-page experience. The graph
 * hook lives in AssetHubPage (shared with the Overview mini-map) so the two
 * views can never disagree.
 */

export function LineageTab({ fqn, graph, onFocusChange }) {
  return (
    <div className="ax-asset-lineage-embed">
      <LineageCanvasV2
        graph={graph}
        focusId={fqn}
        error={graph?.error || ""}
        hydrating={Boolean(graph?.hydrating)}
        warming={Boolean(graph?.warming)}
        onRetry={graph?.refresh || null}
        onFocusChange={onFocusChange}
      />
    </div>
  );
}

export default LineageTab;
