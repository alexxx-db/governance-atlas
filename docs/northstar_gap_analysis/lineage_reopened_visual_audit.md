# Lineage Reopened Visual Audit

Status: reopened and blocking.

This audit is the route-specific Lineage response to the false visual signoff.
It does not sign off any row. It expands `full_page_audit.md` with the detailed
side-by-side findings for Lineage Atlas.

Current checkpoint note: the paths and findings below are historical Lineage
failure-analysis evidence. The active screenshot directory for any new review is
the `global_current_evidence_dir` pinned in
`docs/northstar_gap_analysis/reference_manifest.json`. Rows may only be checked
in `full_page_audit.md` or `functional_control_audit.md` when the guard accepts
current, structured evidence metadata.

## Evidence Compared

- Reference: `northstar/screenshots/prototype_lineage.png`
- Current all-route evidence: `docs/northstar_visual_qa/reopened-all-routes-provenance-guard-pass-local/lineage-3037x1269.png`
- Current responsive evidence:
  - `docs/northstar_visual_qa/reopened-all-routes-provenance-guard-pass-local/lineage-1536x1024.png`
  - `docs/northstar_visual_qa/reopened-all-routes-provenance-guard-pass-local/lineage-1440x900.png`
  - `docs/northstar_visual_qa/reopened-all-routes-provenance-guard-pass-local/lineage-1280x720.png`
- Dedicated Lineage side-by-side evidence:
  - `docs/northstar_visual_qa/reopened-lineage-current-local/lineage-side-by-side-3037x1269.png`
  - `docs/northstar_visual_qa/reopened-lineage-current-local/lineage-diff-3037x1269.png`
- Evidence type: local `prototype_mock`, not live Databricks proof.

## Objective Image Notes

- Prototype dimensions: `2933x1249`.
- Fresh current Lineage capture dimensions: `3037x1269`.
- Common-crop diff bounding box: full frame, so differences are not localized.
- Average graph-canvas color differs materially:
  - prototype graph canvas: approximately `rgb(13, 25, 38)`
  - current graph canvas: approximately `rgb(13, 43, 65)`
- Average right-side/AI region differs materially:
  - prototype right region: approximately `rgb(8, 22, 41)`
  - current right region: approximately `rgb(16, 39, 58)`

## Mismatches

- Shell: prototype left rail is `208px`-class and compact; current rail is wider at `240px`, changing the page proportions.
- Shell: prototype rail bottom user is `Marisol Reyes / Finance · Steward`; current local capture uses `Skyler Myers / Admin`.
- Shell: prototype Lineage active nav has a subtler selected fill; current selected rail has stronger cyan outline and icon emphasis.
- Shell: prototype rail groups are quieter and closer to the left edge; current group spacing and icon rhythm feel heavier.
- Topbar: prototype workspace breadcrumb is `prod`; current is `Dev`.
- Topbar: prototype search is centered and wider relative to the content frame; current search is narrower and pushed right by the wider rail/content layout.
- Topbar: prototype UC chip reads `UC connected · 87.4% coverage`; current local mock matches the text but still differs in height, spacing, and right-edge alignment.
- Topbar: prototype notification/help controls are light icon affordances; current help is a bordered square button.
- Topbar: prototype `Axiom AI` button is active but does not open a rail on Lineage; current capture opens the rail, changing the route balance.
- Header: prototype header starts farther left in the content frame; current header is more centered and leaves more dark unused space.
- Header: prototype title fits the visual hierarchy as a page headline; current title is similar text but larger/heavier and starts from a different x-origin.
- Header: prototype subtitle is a two-line permission-aware end-to-end statement; current copy is shorter and less operationally specific.
- Header: prototype action row uses `Column lineage` and `Run impact analysis`; current header uses `Compare versions` and `Run impact analysis`.
- Header: prototype header action buttons include icon rhythm; current header actions are plainer and differently spaced.
- Header chips: prototype includes Certified, freshness/SLA, `5 CDEs`, owner, upstream/downstream, and revenue-impact chip.
- Header chips: current drops the revenue-impact chip entirely.
- Header chips: current uses `8 upstream - 4 downstream`; prototype uses `5 upstream · 23 downstream`.
- Header chips: current chip palette and spacing differ from the prototype's tighter chips.
- Graph shell: prototype graph is a dark dotted freeform canvas; current graph is five equal vertical bands.
- Graph shell: prototype has a compact upper-left zoom/history/node-count toolbar; current has route tabs/search/export in the graph header.
- Graph shell: prototype graph counter says `19 nodes · 19 edges`; current lacks the graph count.
- Graph shell: prototype has no large top legend in the graph header; current uses pill legend badges in the graph header.
- Graph shell: prototype bottom legend is `NODE TYPES` with icons and source provenance; current bottom legend is absent from the first viewport.
- Graph shell: prototype has a horizontal scrollbar within the graph; current uses fixed bands with no matching scrollbar treatment.
- Graph nodes: prototype nodes are table-like cards with column rows, datatype labels, PK/FK chips, row counts, refresh ages, and status icons.
- Graph nodes: current nodes are simple horizontal cards with an icon square, title, subtitle, and kind pill.
- Graph nodes: prototype `charges_raw`, `invoices_raw`, `payments`, and dimmed `orders` have full schema previews; current nodes truncate names and hide column detail.
- Graph nodes: prototype has source/job/notebook/table/restricted glyphs that match the node type legend; current glyphs are generic colored squares.
- Graph nodes: prototype focus/selected behavior is represented by right-side details and highlighted paths; current focus node is a large cyan lane card.
- Graph nodes: prototype restricted downstream shape is partially visible and permission-bound; current restricted node is a plain card labeled `4 downstream assets`.
- Edges: prototype edges are curved, glowing, and routed around table cards with arrowheads; current edges are thinner, fewer-looking, and more schematic.
- Edges: prototype shows dim/hidden paths for unavailable segments; current does not preserve the same permission-limited continuation shape.
- Edges: prototype has multiple edge crossings around the notebook/job node; current edges mostly connect lane centers.
- Right context: prototype has an in-graph `Lineage Details` inspector for `payments`.
- Right context: current replaces that inspector with the global Axiom AI rail.
- Right context: prototype inspector includes last refresh, row count, owner, sources, consumers, and recent activity.
- Right context: current AI rail includes greeting, suggestions, and an input, but no selected-node lineage details.
- Right context: prototype global AI affordance is a small floating launcher; current has both a rail and launcher.
- Lower first viewport: prototype shows `NODE TYPES` and `LINEAGE AS OF 2026-04-27 Today` inside the first viewport.
- Lower first viewport: current shows impact and column-lineage cards instead of the prototype timeline/control row.
- Impact panel: prototype/source contract expects consumer rows with rich icons and risk/impact context; current rows are generic card rows under the graph.
- Column lineage: prototype/source contract expects a code-like tree and provenance footer; current column lineage is a flat list of repeated `net_revenue_usd` cards.
- Palette: prototype canvas is darker navy and lower-contrast in non-focus regions; current graph and AI regions are brighter teal-blue.
- Typography: prototype uses denser mono/schema typography inside graph nodes; current graph uses larger UI labels and truncation.
- Spacing: prototype graph fills the main area and anchors to the inspector; current graph leaves wider dark gutters and a detached AI rail.
- Responsive: at `1536x1024`, current workbench loses the reference's first-viewport graph/inspector balance.
- Responsive: at `1440x900`, current graph cards and bottom cards compete for vertical space too early.
- Responsive: at `1280x720`, current lower content/launcher crowd the first viewport instead of preserving a usable graph workspace.
- Full-page evidence: active `*-full.png` captures are byte-identical to viewport captures, so lower-scroll parity is not proven.
- Functional: `Compare versions` is status-only unless persisted snapshots are implemented or the control is disabled with a precise reason.
- Functional: `Run impact analysis` announces existing rows rather than running a backed analysis workflow.
- Functional: `Search` is status-only and does not find or highlight graph nodes.
- Functional: `Export` is client-side JSON and lacks PNG/export parity and complete provenance proof.
- Functional: graph node selection does not open a prototype-equivalent selected-node inspector.
- Functional: restricted node selection does not prove live Unity Catalog permission boundary behavior.
- Functional: impact row selection is local state, not navigation to a consumer/work item.
- Functional: the former `Notify owners` control routed to governance but did not
  open or execute a notification workflow; the control must remain renamed to its
  backed owner-review behavior or implement a real notification mutation.
- Functional: `Open asset` is locally validated only and still needs deployed/live proof.
- Truth/provenance: local mock graph data is useful for visual iteration but cannot be called live lineage truth.
- Truth/provenance: hidden downstream and column lineage completeness remain unproven against live Databricks system tables.
- Truth/provenance: current page can be visually richer with mock data, but live thin/no-edge data must preserve prototype regions with honest unavailable states.

## How It Was Missed

- Reviewers accepted capture health and route loading as if they were visual parity.
- Reviewers relied on local functional closure even though local prototype-mock interactions do not prove live workflows.
- The evidence directory in the manifest was treated as current without verifying whether it represented the latest code and route state.
- The Lineage route was not reviewed side by side at the reference aspect ratio before completion language was used.
- Reviewers did not compare the right-side inspector/AI region, lower first-viewport content, or responsive containment.
- The audit did not require each checked row to name screenshot/report evidence, viewport, reviewer role, date, and evidence type.
- Subagent unanimity was treated as a conclusion rather than as a summary of route-specific artifact-backed findings.
- Data unavailability was treated as permission to replace prototype structure with sparse degraded CTAs instead of preserving the graph/inspector/panel shapes honestly.
- Palette drift was not measured or sampled; the blue/teal brightness mismatch should have been caught by side-by-side and color sampling.
- Functional controls that only set status text were not kept as blockers in the page-level signoff path.
